"""Load the collected week into `car_park_reading` and `connector_reading`. SYSTEM_DESIGN.md §4.1.

The readings were polled every 5 minutes from 7 to 14 Oct 2026 by
`Miscellaneous/collector/poll_ev_data.py` (see the README beside it). Only the raw files are
read. Each feed keeps the poll nearest every :00 and :30 SGT slot, and each slot is written in
one transaction together with its `stg_collect_slot` row, so a slot is either fully loaded or
not at all, and a re-run skips it.
"""

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from pydantic import ValidationError

from optev.assumptions import SNAPSHOT_MINUTES
from optev.contracts.enums import ConnectorStatus
from optev.contracts.observations import CarParkReading, ConnectorReading

log = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8))
SLOT = timedelta(minutes=SNAPSHOT_MINUTES)
MAX_OFFSET = timedelta(seconds=150)
EV_STATUS = {
    "0": ConnectorStatus.OCCUPIED,
    "1": ConnectorStatus.AVAILABLE,
    "": ConnectorStatus.UNAVAILABLE,
}
_POLLED_AT = re.compile(rb'^\{"polled_at": "([^"]+)"')


@dataclass(frozen=True)
class Poll:
    feed: str  # "car_park" or "ev", as in stg_collect_slot.feed
    polled_ts: datetime
    path: Path
    offset: int = 0  # byte offset of the line, for car park .jsonl files


def _sgt(text: str) -> datetime:
    """A naive or offset timestamp from either feed, read as Singapore time."""
    ts = datetime.fromisoformat(text.strip().replace(" ", "T"))
    return ts.replace(tzinfo=SGT) if ts.tzinfo is None else ts


def _ev_polls(root: Path) -> list[Poll]:
    polls = []
    for path in root.glob("ev_charging_points_raw_*/*.dat"):
        stamp = path.stem[:10] + path.stem[10:].replace("-", ":")  # 2026-10-10T12-01-10
        polls.append(Poll("ev", _sgt(stamp), path))
    return sorted(polls, key=lambda p: p.polled_ts)


def _car_park_polls(root: Path) -> list[Poll]:
    polls = []
    for path in sorted(root.glob("carpark_availability_raw_*.jsonl")):
        offset = 0
        with path.open("rb") as fh:
            for line in fh:
                found = _POLLED_AT.match(line)
                stamp = found.group(1).decode() if found else json.loads(line)["polled_at"]
                polls.append(Poll("car_park", _sgt(stamp), path, offset))
                offset += len(line)
    return sorted(polls, key=lambda p: p.polled_ts)


def _slots(polls: list[Poll], day: date | None = None) -> dict[datetime, Poll | None]:
    """Every :00 and :30 slot inside the polled window (or on `day`), mapped to the nearest
    poll within MAX_OFFSET, or to None when there is none. Missing slots are never filled."""
    if not polls:
        return {}
    first, last = polls[0].polled_ts, polls[-1].polled_ts
    slot = first.replace(minute=0, second=0, microsecond=0)
    slots: dict[datetime, Poll | None] = {}
    i = 0
    while slot <= last + MAX_OFFSET:
        if slot >= first - MAX_OFFSET and (day is None or slot.date() == day):
            while i + 1 < len(polls) and polls[i + 1].polled_ts <= slot:
                i += 1
            near = min(polls[i : i + 2], key=lambda p: abs(p.polled_ts - slot))
            slots[slot] = near if abs(near.polled_ts - slot) <= MAX_OFFSET else None
        slot += SLOT
    return slots


def _read(poll: Poll) -> dict[str, Any]:
    if poll.feed == "ev":
        payload: dict[str, Any] = json.loads(poll.path.read_bytes())
        return payload
    with poll.path.open("rb") as fh:
        fh.seek(poll.offset)
        line: dict[str, Any] = json.loads(fh.readline())
    return dict(line["data"])


def _parse_car_parks(
    payload: dict[str, Any], collected_ts: datetime
) -> tuple[list[CarParkReading], int]:
    """Car lots (`lot_type` C) of every HDB car park, keyed `hdb:<car_park_no>`, with the car
    park's own `update_datetime` as `provider_ts`. Returns (readings, records skipped)."""
    readings, skipped = [], 0
    for item in payload.get("items") or []:
        for cp in item.get("carpark_data") or []:
            for info in cp.get("carpark_info") or []:
                if info.get("lot_type") != "C":
                    continue
                try:
                    readings.append(CarParkReading(
                        car_park_id=f"hdb:{cp['carpark_number']}",
                        lots_available=int(info["lots_available"]),
                        total_lots=int(info["total_lots"]) if info.get("total_lots") else None,
                        provider_ts=_sgt(cp["update_datetime"]),
                        collected_ts=collected_ts,
                    ))
                except (KeyError, TypeError, ValueError, ValidationError) as err:
                    skipped += 1
                    log.warning("car park record skipped at %s: %s: %r",
                                collected_ts, type(err).__name__, cp)
    return readings, skipped


def _parse_ev(
    payload: dict[str, Any], collected_ts: datetime
) -> tuple[list[ConnectorReading], int]:
    """Every connector (`evCpId`) with its status, unavailable ones included, and the file's
    `LastUpdatedTime` as `provider_ts`. Returns (readings, records skipped)."""
    try:
        provider_ts: datetime | None = _sgt(payload["LastUpdatedTime"])
    except (KeyError, TypeError, ValueError):
        provider_ts = None
        log.warning("EV file at %s has no usable LastUpdatedTime", collected_ts)
    readings, skipped = [], 0
    for loc in payload.get("evLocationsData") or []:
        for point in loc.get("chargingPoints") or []:
            for plug in point.get("plugTypes") or []:
                for ev in plug.get("evIds") or []:
                    try:
                        readings.append(ConnectorReading(
                            connector_id=ev["evCpId"],
                            status=EV_STATUS[ev["status"]],
                            provider_ts=provider_ts,
                            collected_ts=collected_ts,
                        ))
                    except (KeyError, TypeError, ValidationError) as err:
                        skipped += 1
                        log.warning("EV record skipped at %s: %s: %r",
                                    collected_ts, type(err).__name__, ev)
    return readings, skipped


def _copy(cur: psycopg.Cursor[Any], rows: Iterable[CarParkReading | ConnectorReading]) -> int:
    """COPY readings into their table. Values go through psycopg, never string formatting."""
    rows = list(rows)
    if not rows:
        return 0
    if isinstance(rows[0], CarParkReading):
        sql = ("COPY car_park_reading (car_park_id, lots_available, total_lots, lot_type, "
               "provider_ts, collected_ts) FROM STDIN")
    else:
        sql = "COPY connector_reading (connector_id, status, provider_ts, collected_ts) FROM STDIN"
    with cur.copy(sql) as copy:
        for r in rows:
            if isinstance(r, CarParkReading):
                copy.write_row((r.car_park_id, r.lots_available, r.total_lots, r.lot_type,
                                r.provider_ts, r.collected_ts))
            else:
                copy.write_row((r.connector_id, r.status.value, r.provider_ts, r.collected_ts))
    return len(rows)


def _write_slot(conn: psycopg.Connection[Any], slot: datetime, poll: Poll) -> int:
    """Write one slot's readings and its manifest row, without committing. Returns rows
    written, or 0 when the slot is already in `stg_collect_slot`."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM stg_collect_slot WHERE feed = %s AND slot_ts = %s",
                    (poll.feed, slot))
        if cur.fetchone():
            return 0
        parse = _parse_ev if poll.feed == "ev" else _parse_car_parks
        readings, skipped = parse(_read(poll), poll.polled_ts)
        written = _copy(cur, readings)
        cur.execute(
            "INSERT INTO stg_collect_slot (feed, slot_ts, polled_ts, offset_s, rows_written,"
            " rows_skipped) VALUES (%s, %s, %s, %s, %s, %s)",
            (poll.feed, slot, poll.polled_ts,
             round(abs((poll.polled_ts - slot).total_seconds())), written, skipped),
        )
    return written


def load_collected(root: Path, day: date | None = None) -> dict[str, int]:
    """Load the collected week under `root` (or only the slots on `day`, SGT) into the reading
    tables. Returns rows written per reading table. Needs DATABASE_URL in the environment."""
    written = {"car_park_reading": 0, "connector_reading": 0}
    table = {"car_park": "car_park_reading", "ev": "connector_reading"}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for polls in (_car_park_polls(root), _ev_polls(root)):
            for slot, poll in _slots(polls, day).items():
                if poll is None:
                    log.warning("no poll within %s of %s", MAX_OFFSET, slot)
                    continue
                n = _write_slot(conn, slot, poll)
                conn.commit()
                written[table[poll.feed]] += n
                log.info("%s %s: %d rows", poll.feed, slot.isoformat(), n)
    return written
