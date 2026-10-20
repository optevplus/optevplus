"""Coverage and freshness (#12, SYSTEM_DESIGN.md §4.1 step 4).

The proposal promises that data coverage is reported alongside the analysis rather than
assumed. Each run writes one row per metric to `coverage_report`, all with the same `run_at`,
so the history of runs stays queryable.

A metric whose inputs are not loaded yet (no stations, no amenities) is left out and named in
`skipped`, never written as 0: a zero would read as "nothing matched" when the truth is
"not measured".
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from optev.assumptions import AMENITY_LINK_M, MATCH_THRESHOLDS_M, SNAPSHOT_MINUTES

log = logging.getLogger(__name__)

SLOT = timedelta(minutes=SNAPSHOT_MINUTES)
FEEDS = {"ev": "connector_reading", "car_park": "car_park_reading"}
_ENV = Path(__file__).resolve().parents[2] / ".env"

Metric = tuple[float, str]  # (value, detail)


def expected_slots(window_start: datetime, window_end: datetime) -> int:
    """Half-hour slots in [start, end): the snapshots a complete feed would have."""
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    first = window_start
    if first.minute % SNAPSHOT_MINUTES or first.second or first.microsecond:
        first = first.replace(minute=first.minute - first.minute % SNAPSHOT_MINUTES,
                              second=0, microsecond=0) + SLOT
    if first >= window_end:
        return 0
    return int((window_end - first - timedelta(microseconds=1)) / SLOT) + 1


def _scalar(conn: psycopg.Connection[Any], sql: str, *params: object) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _exists(conn: psycopg.Connection[Any], table: str) -> bool:
    return _scalar(conn, "SELECT to_regclass(%s) IS NOT NULL", table) is True


def measure(conn: psycopg.Connection[Any], window_start: datetime,
            window_end: datetime) -> tuple[dict[str, Metric], list[str]]:
    """Every metric that can be measured now, and the names of those that cannot."""
    out: dict[str, Metric] = {}
    skipped: list[str] = []
    want = expected_slots(window_start, window_end)

    for feed, table in FEEDS.items():
        got = _scalar(conn, "SELECT count(*) FROM stg_collect_slot WHERE feed = %s"
                      " AND slot_ts >= %s AND slot_ts < %s", feed, window_start, window_end)
        out[f"{feed}_slot_completeness"] = (got / want, f"{got} of {want} half-hour slots")
        fresh = conn.execute(
            f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY s),"
            f" percentile_cont(0.95) WITHIN GROUP (ORDER BY s), count(*)"
            f" FROM (SELECT extract(epoch FROM collected_ts - provider_ts) AS s FROM {table}"
            f"       WHERE collected_ts >= %s AND collected_ts < %s"
            f"       AND provider_ts IS NOT NULL) t",
            (window_start, window_end)).fetchone()
        if fresh and fresh[2]:
            out[f"{feed}_freshness_median_s"] = (
                float(fresh[0]), f"p95 {fresh[1]:.0f} s over {fresh[2]} readings")
        else:
            skipped.append(f"{feed}_freshness_median_s")

    present = conn.execute(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n), count(*),"
        " count(*) FILTER (WHERE n >= %s) FROM"
        " (SELECT count(DISTINCT collected_ts)::float AS n FROM connector_reading"
        "  WHERE collected_ts >= %s AND collected_ts < %s GROUP BY connector_id) t",
        (want, window_start, window_end)).fetchone()
    if present and present[1] and want:
        out["connector_presence_median"] = (
            float(present[0]) / want, f"median share of slots a charging point appears in, "
                                      f"over {present[1]} charging points")
        out["connectors_in_every_slot"] = (
            present[2] / present[1], f"{present[2]} of {present[1]} charging points appear in "
                                     f"all {want} slots; the rest were added or removed")

    stations = _scalar(conn, "SELECT count(*) FROM station")
    if stations:
        for t in MATCH_THRESHOLDS_M:
            matched = _scalar(conn, "SELECT count(DISTINCT station_id) FROM station_site"
                                    " WHERE threshold_m <= %s", t)
            out[f"stations_matched_{t}m"] = (matched / stations,
                                             f"{matched} of {stations} stations within {t} m")
    else:
        skipped += [f"stations_matched_{t}m" for t in MATCH_THRESHOLDS_M]

    sites = _scalar(conn, "SELECT count(*) FROM candidate_site")
    if sites:
        with_area = _scalar(conn, "SELECT count(*) FROM candidate_site"
                                  " WHERE planning_area IS NOT NULL")
        out["sites_with_planning_area"] = (with_area / sites, f"{with_area} of {sites} sites")
    else:
        skipped.append("sites_with_planning_area")

    car_parks = _scalar(conn, "SELECT count(*) FROM car_park")
    if car_parks:
        live = _scalar(conn, "SELECT count(*) FROM car_park WHERE has_live_feed")
        out["car_parks_with_live_feed"] = (live / car_parks, f"{live} of {car_parks} car parks")
    else:
        skipped.append("car_parks_with_live_feed")

    amenities = _scalar(conn, "SELECT count(*) FROM stg_amenity") if _exists(
        conn, "stg_amenity") else 0
    if amenities and car_parks:
        linked = _scalar(
            conn, "SELECT count(*) FROM stg_amenity a WHERE EXISTS (SELECT 1 FROM car_park c"
                  " WHERE ST_DWithin(ST_Transform(a.geom, 3414), ST_Transform(c.geom, 3414), %s))",
            AMENITY_LINK_M)
        out["amenities_linked_to_car_park"] = (
            linked / amenities, f"{linked} of {amenities} within {AMENITY_LINK_M} m")
    else:
        skipped.append("amenities_linked_to_car_park")
    return out, skipped


def write(conn: psycopg.Connection[Any], metrics: dict[str, Metric]) -> datetime:
    """One row per metric, all sharing one run_at. Returns run_at."""
    run_at: datetime = conn.execute("SELECT now()").fetchone()[0]  # type: ignore[index]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO coverage_report (run_at, metric, value, detail) VALUES (%s, %s, %s, %s)",
            [(run_at, name, value, detail) for name, (value, detail) in metrics.items()])
    return run_at


def coverage_report(window_start: datetime, window_end: datetime) -> dict[str, float]:
    """Measure, write to `coverage_report`, return metric → value. Design §4.1 signature."""
    from dotenv import load_dotenv

    load_dotenv(_ENV)  # never overrides a variable already set
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        metrics, skipped = measure(conn, window_start, window_end)
        write(conn, metrics)
    if skipped:
        log.info("not measured yet (inputs not loaded): %s", ", ".join(skipped))
    return {name: value for name, (value, _) in metrics.items()}


def collected_window(conn: psycopg.Connection[Any]) -> tuple[datetime, datetime]:
    """The collected week: first slot to one slot after the last."""
    first, last = conn.execute("SELECT min(slot_ts), max(slot_ts) FROM stg_collect_slot"
                               ).fetchone() or (None, None)
    if first is None or last is None:
        raise ValueError("stg_collect_slot is empty: load the collected week first")
    return first, last + SLOT
