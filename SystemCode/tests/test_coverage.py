"""Coverage is measured, never assumed (#12). The live tests build a small known week in a
transaction that is rolled back, so they need DATABASE_URL in the environment itself
(`uv run --env-file .env pytest`)."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from optev.ingest import coverage as C

SGT = timezone(timedelta(hours=8))
T0 = datetime(1999, 1, 1, 0, 0, tzinfo=SGT)  # far from the real week, and rolled back anyway


def test_expected_slots_count_half_hours_in_the_window():
    assert C.expected_slots(T0, T0 + timedelta(hours=2)) == 4
    assert C.expected_slots(T0, T0 + timedelta(minutes=30)) == 1
    assert C.expected_slots(T0 + timedelta(minutes=10), T0 + timedelta(hours=1)) == 1  # :30
    assert C.expected_slots(T0, T0 + timedelta(minutes=1)) == 1
    # The collected week: 7 Oct 14:00 to 14 Oct 10:30 inclusive, as Sushant reported.
    week = datetime(2026, 10, 7, 14, 0, tzinfo=SGT)
    assert C.expected_slots(week, datetime(2026, 10, 14, 11, 0, tzinfo=SGT)) == 330
    with pytest.raises(ValueError):
        C.expected_slots(T0, T0)


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@pytest.fixture
def known_week():
    """4 slots; the EV feed misses one; connector B is seen in only 2 slots."""
    import psycopg

    slots = [T0 + C.SLOT * i for i in range(4)]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for feed in ("ev", "car_park"):
            for i, s in enumerate(slots):
                if feed == "ev" and i == 3:
                    continue
                conn.execute("INSERT INTO stg_collect_slot VALUES (%s, %s, %s, 0, 1, 0)",
                             (feed, s, s))
        for i, s in enumerate(slots[:3]):
            conn.execute("INSERT INTO connector_reading (connector_id, status, provider_ts,"
                         " collected_ts) VALUES ('SYN-A', 'available', %s, %s)",
                         (s - timedelta(seconds=60), s))
            if i < 2:
                conn.execute("INSERT INTO connector_reading (connector_id, status,"
                             " provider_ts, collected_ts) VALUES ('SYN-B', 'occupied', %s, %s)",
                             (s - timedelta(seconds=120), s))
        try:
            yield conn
        finally:
            conn.rollback()


@live
def test_measures_completeness_freshness_and_presence(known_week):
    metrics, skipped = C.measure(known_week, T0, T0 + C.SLOT * 4)
    assert metrics["ev_slot_completeness"][0] == 0.75
    assert metrics["car_park_slot_completeness"][0] == 1.0
    assert metrics["ev_freshness_median_s"][0] == 60.0  # five readings: 60, 60, 60, 120, 120
    assert metrics["connector_presence_median"][0] == pytest.approx((3 / 4 + 2 / 4) / 2)
    assert metrics["connectors_in_every_slot"][0] == 0.0
    assert "car_park_freshness_median_s" in skipped  # no car park readings in this window


@live
def test_unmeasured_metrics_are_skipped_not_written_as_zero(known_week):
    metrics, skipped = C.measure(known_week, T0, T0 + C.SLOT * 4)
    empty = {name for name in skipped}
    assert not empty & set(metrics)
    for name, (value, _) in metrics.items():
        assert value is not None, name


@live
def test_a_run_writes_one_row_per_metric_with_one_timestamp(known_week):
    metrics, _ = C.measure(known_week, T0, T0 + C.SLOT * 4)
    run_at = C.write(known_week, metrics)
    rows = known_week.execute("SELECT metric, value FROM coverage_report WHERE run_at = %s",
                              (run_at,)).fetchall()
    assert dict(rows) == {name: value for name, (value, _) in metrics.items()}
