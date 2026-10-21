"""Site indicators (SYSTEM_DESIGN.md §4.2 step 1): how busy each site's chargers were.

Both entry points count, per site and snapshot, the occupied and available connectors among
the site's matched active connectors, then measure from those counts. `compute_*` count from
contracts, so they run on optev.sample; `site_indicators` and `occupancy_by_bin` count in
Postgres, because the collected week is 3.8 M readings.
"""

import logging
import os
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from optev.assumptions import IDLE_BELOW, MIN_COVERAGE, SNAPSHOT_MINUTES
from optev.contracts import CandidateSite, Connector, ConnectorReading, SiteIndicators
from optev.contracts.enums import ConnectorStatus, SupplyState

log = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8))
SLOT = timedelta(minutes=SNAPSHOT_MINUTES)
MATCH_WITHIN_M = 100  # §4.2: a station counts at its nearest site, if within 100 m
MEASURED = {SupplyState.SUPPLY_ACTIVE, SupplyState.SUPPLY_IDLE}

Counts = dict[str, dict[datetime, tuple[int, int]]]
"""site_id -> snapshot slot -> (occupied, available). A slot present is a slot seen."""


def snapshot_slot(ts: datetime) -> datetime:
    """The snapshot a reading belongs to: the nearest SNAPSHOT_MINUTES slot, in SGT."""
    step = SLOT.total_seconds()
    return datetime.fromtimestamp(round(ts.timestamp() / step) * step, SGT)


def expected_slots(window_start: datetime, window_end: datetime) -> int:
    """Number of snapshot slots in [window_start, window_end)."""
    step = SLOT.total_seconds()
    first = -(-window_start.timestamp() // step)  # ceiling
    last = -(-window_end.timestamp() // step)
    return max(0, int(last - first))


def time_bin(slot: datetime) -> str:
    """`wd-HH` or `we-HH` (§3.4) for a snapshot, by its SGT hour."""
    t = slot.astimezone(SGT)
    return f"{'we' if t.weekday() >= 5 else 'wd'}-{t.hour:02d}"


def nearest_site(near: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each station's nearest station-site row (smallest `distance_m`, ties by `site_id`).
    A station's chargers are one queue, so it counts at one site only (§4.2)."""
    best: dict[str, dict[str, Any]] = {}
    for n in near:
        b = best.get(n["station_id"])
        if b is None or (n["distance_m"], n["site_id"]) < (b["distance_m"], b["site_id"]):
            best[n["station_id"]] = n
    return list(best.values())


def _matched(near: list[dict[str, Any]], connectors: list[Connector]) -> dict[str, set[str]]:
    """site_id -> its matched connectors that were ever active (invariant 3)."""
    by_station: dict[str, set[str]] = defaultdict(set)
    for c in connectors:
        if c.ever_active:
            by_station[c.station_id].add(c.connector_id)
    out: dict[str, set[str]] = defaultdict(set)
    for n in nearest_site(near):
        if n["threshold_m"] <= MATCH_WITHIN_M:
            out[n["site_id"]] |= by_station.get(n["station_id"], set())
    return {site: conns for site, conns in out.items() if conns}


def _count(matched: dict[str, set[str]], readings: Iterable[ConnectorReading],
           window_start: datetime, window_end: datetime) -> Counts:
    sites_of: dict[str, list[str]] = defaultdict(list)
    for site, conns in matched.items():
        for c in conns:
            sites_of[c].append(site)
    tally: dict[str, dict[datetime, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in readings:
        slot = snapshot_slot(r.collected_ts)
        if not window_start <= slot < window_end:
            continue
        for site in sites_of.get(r.connector_id, ()):
            cell = tally[site][slot]
            cell[0] += r.status == ConnectorStatus.OCCUPIED
            cell[1] += r.status == ConnectorStatus.AVAILABLE
    return {site: {s: (o, a) for s, (o, a) in slots.items()} for site, slots in tally.items()}


def _measure(site_ids: Iterable[str], active: dict[str, int], counts: Counts,
             window_start: datetime, window_end: datetime) -> list[SiteIndicators]:
    expected = expected_slots(window_start, window_end)
    window = {"window_start": window_start.isoformat(), "window_end": window_end.isoformat()}
    out = []
    for site in site_ids:
        n = active.get(site, 0)
        if n == 0:
            out.append(SiteIndicators(site_id=site, supply_state=SupplyState.NO_SUPPLY,
                                      observation_coverage=1.0, **window))
            continue
        snaps = counts.get(site, {})
        coverage = min(1.0, len(snaps) / expected) if expected else 0.0
        ratios = [o / (o + a) for o, a in snaps.values() if o + a]
        if coverage < MIN_COVERAGE.value or not ratios:
            out.append(SiteIndicators(site_id=site, supply_state=SupplyState.UNOBSERVED,
                                      active_connectors=n, observation_coverage=coverage,
                                      **window))
            continue
        utilisation = sum(ratios) / len(ratios)
        saturated = sum(1 for o, a in snaps.values() if a == 0 and o > 0) / len(ratios)
        state = (SupplyState.SUPPLY_IDLE if utilisation < IDLE_BELOW.value
                 else SupplyState.SUPPLY_ACTIVE)
        out.append(SiteIndicators(site_id=site, supply_state=state, active_connectors=n,
                                  utilisation=utilisation, saturated_fraction=saturated,
                                  observation_coverage=coverage, **window))
    return out


def _bins(indicators: list[SiteIndicators], counts: Counts) -> dict[str, dict[str, float]]:
    """Mean occupancy per time bin for measured sites, plus `all` (§3.4). With only weekday
    or only weekend snapshots in the window, `all` is the mean of the bins there are."""
    out: dict[str, dict[str, float]] = {}
    for ind in indicators:
        if ind.supply_state not in MEASURED:
            continue
        per_bin: dict[str, list[float]] = defaultdict(list)
        for slot, (o, a) in counts.get(ind.site_id, {}).items():
            if o + a:
                per_bin[time_bin(slot)].append(o / (o + a))
        means = {b: sum(v) / len(v) for b, v in sorted(per_bin.items())}
        wd = [v for b, v in means.items() if b.startswith("wd")]
        we = [v for b, v in means.items() if b.startswith("we")]
        if wd and we:
            means["all"] = (5 * sum(wd) / len(wd) + 2 * sum(we) / len(we)) / 7
        elif wd or we:
            means["all"] = sum(wd or we) / len(wd or we)
        out[ind.site_id] = means
    return out


def _prepare(sites: list[CandidateSite], near: list[dict[str, Any]],
             connectors: list[Connector], readings: list[ConnectorReading],
             window_start: datetime, window_end: datetime
             ) -> tuple[list[str], dict[str, int], Counts]:
    matched = _matched(near, connectors)
    active = {site: len(conns) for site, conns in matched.items()}
    return ([s.site_id for s in sites], active,
            _count(matched, readings, window_start, window_end))


def compute_indicators(sites: list[CandidateSite], near: list[dict[str, Any]],
                       connectors: list[Connector], readings: list[ConnectorReading],
                       window_start: datetime, window_end: datetime) -> list[SiteIndicators]:
    """One SiteIndicators per site for the window. `near` holds station-site rows with
    `station_id`, `site_id` and `threshold_m`, as `station_site` does."""
    site_ids, active, counts = _prepare(sites, near, connectors, readings,
                                        window_start, window_end)
    return _measure(site_ids, active, counts, window_start, window_end)


def compute_occupancy_by_bin(sites: list[CandidateSite], near: list[dict[str, Any]],
                             connectors: list[Connector], readings: list[ConnectorReading],
                             window_start: datetime, window_end: datetime
                             ) -> dict[str, dict[str, float]]:
    """site_id -> time_bin -> mean occupancy, for sites with measured supply only."""
    site_ids, active, counts = _prepare(sites, near, connectors, readings,
                                        window_start, window_end)
    return _bins(_measure(site_ids, active, counts, window_start, window_end), counts)


# --- Postgres -------------------------------------------------------------------------------

# Each station's nearest site only, as nearest_site does.
_NEAREST_SQL = """(SELECT DISTINCT ON (station_id) station_id, site_id, threshold_m
     FROM station_site ORDER BY station_id, distance_m, site_id)"""

_ACTIVE_SQL = f"""
SELECT ss.site_id, count(*)
FROM {_NEAREST_SQL} ss JOIN connector c ON c.station_id = ss.station_id
WHERE c.ever_active AND ss.threshold_m <= %(within)s
GROUP BY ss.site_id
"""

# Readings are put in the nearest slot, so the query window is shifted back half a slot.
_COUNTS_SQL = f"""
SELECT ss.site_id,
       to_timestamp(round(extract(epoch FROM r.collected_ts) / %(step)s) * %(step)s) AS slot,
       count(*) FILTER (WHERE r.status = 'occupied'),
       count(*) FILTER (WHERE r.status = 'available')
FROM connector_reading r
JOIN connector c ON c.connector_id = r.connector_id
JOIN {_NEAREST_SQL} ss ON ss.station_id = c.station_id
WHERE c.ever_active AND ss.threshold_m <= %(within)s
  AND r.collected_ts >= %(start)s AND r.collected_ts < %(end)s
GROUP BY 1, 2
"""

_UPSERT_SQL = """
INSERT INTO site_indicators (site_id, window_start, window_end, supply_state, active_connectors,
    utilisation, saturated_fraction, dwell_opportunity, observation_coverage)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (site_id, window_start, window_end) DO UPDATE SET
    supply_state = EXCLUDED.supply_state, active_connectors = EXCLUDED.active_connectors,
    utilisation = EXCLUDED.utilisation, saturated_fraction = EXCLUDED.saturated_fraction,
    dwell_opportunity = EXCLUDED.dwell_opportunity,
    observation_coverage = EXCLUDED.observation_coverage
"""


def read_counts(conn: psycopg.Connection, window_start: datetime, window_end: datetime
                ) -> tuple[list[str], dict[str, int], Counts]:
    """Site ids, active connectors per site and snapshot counts, from Postgres."""
    params = {"within": MATCH_WITHIN_M, "step": SLOT.total_seconds(),
              "start": window_start - SLOT / 2, "end": window_end - SLOT / 2}
    with conn.cursor() as cur:
        cur.execute("SELECT site_id FROM candidate_site ORDER BY site_id")
        site_ids = [row[0] for row in cur.fetchall()]
        cur.execute(_ACTIVE_SQL, params)
        active = {site: int(n) for site, n in cur.fetchall()}
        cur.execute(_COUNTS_SQL, params)
        counts: Counts = defaultdict(dict)
        for site, slot, occupied, available in cur.fetchall():
            counts[site][slot.astimezone(SGT)] = (int(occupied), int(available))
    return site_ids, active, dict(counts)


def write_indicators(conn: psycopg.Connection, indicators: list[SiteIndicators],
                     window_start: datetime, window_end: datetime) -> int:
    """Upsert into `site_indicators` without committing. Returns rows written."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, [
            (i.site_id, window_start, window_end, i.supply_state.value, i.active_connectors,
             i.utilisation, i.saturated_fraction, i.dwell_opportunity, i.observation_coverage)
            for i in indicators
        ])
    return len(indicators)


def site_indicators(window_start: datetime, window_end: datetime) -> list[SiteIndicators]:
    """Measure every candidate site over the window and upsert `site_indicators`.
    Needs DATABASE_URL in the environment."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        site_ids, active, counts = read_counts(conn, window_start, window_end)
        indicators = _measure(site_ids, active, counts, window_start, window_end)
        n = write_indicators(conn, indicators, window_start, window_end)
        conn.commit()
    log.info("site_indicators: %d rows for %s to %s", n, window_start, window_end)
    return indicators


def occupancy_by_bin(window_start: datetime, window_end: datetime) -> dict[str, dict[str, float]]:
    """site_id -> time_bin -> mean occupancy over the window, from Postgres."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        site_ids, active, counts = read_counts(conn, window_start, window_end)
    return _bins(_measure(site_ids, active, counts, window_start, window_end), counts)
