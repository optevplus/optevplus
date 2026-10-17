"""`optev.ingest.collect` on small hand-written payloads in the real feeds' shapes. The live
tests write to the shared Neon database inside a transaction that is rolled back, and run only
when DATABASE_URL is in the environment itself (`uv run --env-file .env pytest`)."""

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from optev import sample
from optev.contracts.enums import ConnectorStatus
from optev.ingest import cli, collect
from optev.ingest.collect import SGT, Poll

T0 = datetime(2026, 10, 10, 0, 0, tzinfo=SGT)


def car_park_payload(**info: str) -> dict:
    lot = {"total_lots": "105", "lots_available": "102", "lot_type": "C"} | info
    return {"items": [{"timestamp": "2026-10-10T00:00:36+08:00", "carpark_data": [
        {"carpark_number": "SYN1", "update_datetime": "2026-10-09T23:59:47",
         "carpark_info": [lot, {"total_lots": "9", "lots_available": "3", "lot_type": "Y"}]},
    ]}]}


def ev_payload(*statuses: object) -> dict:
    ids = [{"evCpId": f"SYN-CP-{i}", "status": s} for i, s in enumerate(statuses)]
    return {"LastUpdatedTime": "2026-10-10 00:00:00", "evLocationsData": [
        {"name": "SYN", "chargingPoints": [{"plugTypes": [{"plugType": "Type 2", "evIds": ids}]}]},
    ]}


def write_week(root: Path, minutes: list[int]) -> None:
    """A collected_data folder with one poll of each feed at T0 + each minute, 51 s past."""
    lines = []
    for m in minutes:
        ts = T0 + timedelta(minutes=m, seconds=51)
        day = ts.date().isoformat()
        folder = root / f"ev_charging_points_raw_{day}"
        folder.mkdir(exist_ok=True)
        stamp = ts.strftime("%Y-%m-%dT%H-%M-%S")
        (folder / f"{stamp}.dat").write_text(json.dumps(ev_payload("1", "0", "")))
        lines.append(json.dumps({"polled_at": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "data": car_park_payload()}))
    (root / "carpark_availability_raw_2026-10-10.jsonl").write_text("\n".join(lines) + "\n")


def polls(*minutes: float) -> list[Poll]:
    return [Poll("ev", T0 + timedelta(minutes=m), Path("x")) for m in minutes]


def test_slots_pick_the_nearest_poll_within_150_seconds():
    slots = collect._slots(polls(-4, 1, 6, 26, 31, 61.5))
    assert [s - T0 for s in slots] == [timedelta(0), timedelta(minutes=30), timedelta(hours=1)]
    assert slots[T0] is not None and slots[T0].polled_ts == T0 + timedelta(minutes=1)
    hour = slots[T0 + timedelta(hours=1)]
    assert hour is not None and hour.polled_ts == T0 + timedelta(minutes=61.5)


def test_a_slot_without_a_poll_is_missing_not_filled():
    slots = collect._slots(polls(0, 5, 10, 55, 60))
    assert slots[T0 + timedelta(minutes=30)] is None
    assert slots[T0] is not None and slots[T0 + timedelta(hours=1)] is not None


def test_slots_on_one_day_only():
    slots = collect._slots(polls(-60, -30, 0, 30), day=date(2026, 10, 10))
    assert list(slots) == [T0, T0 + timedelta(minutes=30)]
    assert collect._slots([]) == {}


def test_car_parks_keep_car_lots_with_their_own_update_time():
    readings, skipped = collect._parse_car_parks(car_park_payload(), T0)
    assert skipped == 0
    [r] = readings
    assert (r.car_park_id, r.lots_available, r.total_lots) == ("hdb:SYN1", 102, 105)
    assert r.lot_type == "C"
    assert r.provider_ts == datetime(2026, 10, 9, 23, 59, 47, tzinfo=SGT)
    assert r.collected_ts == T0


def test_a_bad_car_park_record_is_logged_and_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        for bad in ({"lots_available": "-1"}, {"lots_available": "x"}, {"total_lots": "-5"}):
            readings, skipped = collect._parse_car_parks(car_park_payload(**bad), T0)
            assert (readings, skipped) == ([], 1)
    assert caplog.text.count("car park record skipped") == 3
    assert collect._parse_car_parks({}, T0) == ([], 0)


def test_ev_maps_every_status_and_keeps_unavailable_connectors():
    readings, skipped = collect._parse_ev(ev_payload("0", "1", ""), T0)
    assert skipped == 0
    assert [r.status for r in readings] == [
        ConnectorStatus.OCCUPIED, ConnectorStatus.AVAILABLE, ConnectorStatus.UNAVAILABLE]
    assert {r.provider_ts for r in readings} == {T0}
    assert [r.connector_id for r in readings] == ["SYN-CP-0", "SYN-CP-1", "SYN-CP-2"]


def test_an_unknown_ev_status_is_logged_and_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        readings, skipped = collect._parse_ev(ev_payload("1", "7", None), T0)
    assert len(readings) == 1 and skipped == 2
    assert caplog.text.count("EV record skipped") == 2


def test_ev_without_last_updated_time_keeps_readings_without_provider_ts():
    payload = ev_payload("1")
    del payload["LastUpdatedTime"]
    [r] = collect._parse_ev(payload, T0)[0]
    assert r.provider_ts is None


def test_polls_are_found_in_the_raw_files_and_read_back(tmp_path):
    write_week(tmp_path, [0, 5, 30])
    for found in (collect._car_park_polls(tmp_path), collect._ev_polls(tmp_path)):
        assert [p.polled_ts.minute for p in found] == [0, 5, 30]
        payload = collect._read(found[1])
        assert "items" in payload or "evLocationsData" in payload


def test_load_collected_writes_each_slot_once(tmp_path, monkeypatch):
    write_week(tmp_path, [0, 5, 30, 35])
    written: list[tuple[str, datetime]] = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def commit(self):
            pass

    def fake_write(conn, slot, poll):
        written.append((poll.feed, slot))
        return 3

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/x")
    monkeypatch.setattr(collect.psycopg, "connect", lambda url: Conn())
    monkeypatch.setattr(collect, "_write_slot", fake_write)
    assert collect.load_collected(tmp_path) == {"car_park_reading": 6, "connector_reading": 6}
    assert sorted(written) == sorted(
        (feed, T0 + timedelta(minutes=m)) for feed in ("car_park", "ev") for m in (0, 30))


def test_cli_load_collected_usage(monkeypatch, tmp_path, capsys):
    for args in ([], [str(tmp_path / "nope")], [str(tmp_path), "--day"],
                 [str(tmp_path), "--day", "10 Oct"]):
        monkeypatch.setattr("sys.argv", ["optev-db", "load-collected", *args])
        assert cli.main() == 2
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "MIGRATIONS", tmp_path / "migrations")  # no .env beside it
    monkeypatch.setattr("sys.argv", ["optev-db", "load-collected", str(tmp_path)])
    assert cli.main() == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().out


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@live
def test_sample_readings_copy_into_the_reading_tables():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                assert collect._copy(cur, sample.car_park_readings()) > 0
                assert collect._copy(cur, sample.connector_readings()) > 0
                cur.execute("SELECT count(*) FROM connector_reading"
                            " WHERE connector_id LIKE 'SYN-%'")
                row = cur.fetchone()
                assert row is not None and row[0] == len(sample.connector_readings())
        finally:
            conn.rollback()


@live
def test_a_slot_is_written_once_with_its_manifest_row(tmp_path):
    import psycopg

    write_week(tmp_path, [0])
    [poll] = collect._ev_polls(tmp_path)
    slot = datetime(1999, 1, 1, tzinfo=SGT)  # far from the real week, and rolled back anyway
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            assert collect._write_slot(conn, slot, poll) == 3
            assert collect._write_slot(conn, slot, poll) == 0
            row = conn.execute(
                "SELECT rows_written, rows_skipped FROM stg_collect_slot"
                " WHERE feed = 'ev' AND slot_ts = %s", (slot,)).fetchone()
            assert row == (3, 0)
        finally:
            conn.rollback()
