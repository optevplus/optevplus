"""Put the sample into an empty, migrated Postgres as if it were the collected week.

    DATABASE_URL=postgresql://localhost:5433/optev uv run python -m optev.sample.seed_db

For running the whole pipeline (#35) without Neon: a local database, a marker's machine, or
a test. It writes only what collection and the static loads would write (planning areas, car
parks, stations, connectors, readings, the slot manifest, amenities); every later table is
left for the pipeline to fill. Every id starts with SYN-. Refuses a database that already
holds real readings.
"""

import os
import sys
from datetime import timedelta
from typing import Any

import psycopg

from optev.sample import car_park_readings, connector_readings
from optev.sample import load as sample
from optev.sample.generate import AREAS, HOURS, SNAP_EVERY, START

AMENITY_KINDS = {"hawker_centre", "community_facility", "petrol_station"}


def car_park_ids() -> dict[str, str]:
    """Sample car park id -> an id in the real §3.3 format, which conform recognises:
    `hdb:` for HDB car parks, `ura:` for public ones, still carrying SYN-."""
    s = sample()
    kind = {x.car_park_id: x.kind.value for x in s.sites if x.car_park_id}
    return {c.car_park_id: ("hdb:" if kind.get(c.car_park_id) == "hdb_car_park" else "ura:")
            + c.car_park_id for c in s.car_parks}


def _square(code: str) -> str:
    """A planning area as a WKT polygon around the sample's centre and spread."""
    area = next(a for a in AREAS if a["code"] == code)
    (lat, lon), (dlat, dlon) = area["centre"], area["spread"]
    lat0, lat1, lon0, lon1 = lat - 2 * dlat, lat + 2 * dlat, lon - 2 * dlon, lon + 2 * dlon
    return (f"MULTIPOLYGON((({lon0} {lat0}, {lon1} {lat0}, {lon1} {lat1}, {lon0} {lat1}, "
            f"{lon0} {lat0})))")


def seed(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Insert the sample; does not commit."""
    real = conn.execute("SELECT count(*) FROM connector_reading WHERE connector_id NOT LIKE "
                        "'SYN-%'").fetchone()
    if real and real[0]:
        raise RuntimeError("this database holds real readings: seed a scratch database instead")
    s = sample()
    ids = car_park_ids()
    point = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO planning_area (code, name, region, geom) VALUES "
            "(%s, %s, %s, ST_GeomFromText(%s, 4326)) ON CONFLICT (code) DO NOTHING",
            [(a.code, a.name, a.region, _square(a.code)) for a in s.planning_areas])
        cur.executemany(
            f"INSERT INTO car_park (car_park_id, name, total_lots, car_park_type, planning_area, "
            f"geom) VALUES (%s, %s, %s, %s, %s, {point}) ON CONFLICT (car_park_id) DO NOTHING",
            [(ids[c.car_park_id], c.name, c.total_lots, c.car_park_type, c.planning_area,
              c.coord.lon, c.coord.lat) for c in s.car_parks])
        cur.executemany(
            f"INSERT INTO station (station_id, operator, address, provenance, planning_area, "
            f"geom) VALUES (%s, %s, %s, %s, %s, {point}) ON CONFLICT (station_id) DO NOTHING",
            [(st.station_id, st.operator, st.address, st.provenance.value, st.planning_area,
              st.coord.lon, st.coord.lat) for st in s.stations])
        cur.executemany(
            "INSERT INTO connector (connector_id, station_id, plug_type, power_kw) VALUES "
            "(%s, %s, %s, %s) ON CONFLICT (connector_id) DO NOTHING",
            [(c.connector_id, c.station_id, c.plug_type, c.power_kw) for c in s.connectors])
        ev = connector_readings()
        cur.executemany(
            "INSERT INTO connector_reading (connector_id, status, provider_ts, collected_ts) "
            "VALUES (%s, %s, %s, %s)",
            [(r.connector_id, r.status.value, r.provider_ts, r.collected_ts) for r in ev])
        cp = car_park_readings()
        cur.executemany(
            "INSERT INTO car_park_reading (car_park_id, lots_available, total_lots, lot_type, "
            "provider_ts, collected_ts) VALUES (%s, %s, %s, %s, %s, %s)",
            [(ids.get(r.car_park_id, r.car_park_id), r.lots_available, r.total_lots,
              r.lot_type, r.provider_ts, r.collected_ts) for r in cp])
        slots = [START + timedelta(minutes=m) for m in range(0, HOURS * 60, SNAP_EVERY)]
        cur.executemany(
            "INSERT INTO stg_collect_slot (feed, slot_ts, polled_ts, offset_s, rows_written, "
            "rows_skipped) VALUES (%s, %s, %s, 0, 0, 0) ON CONFLICT DO NOTHING",
            [(feed, t, t) for feed in ("ev", "car_park") for t in slots])
        amenities = [x for x in s.sites if x.kind.value in AMENITY_KINDS]
        cur.executemany(
            f"INSERT INTO stg_amenity (amenity_id, kind, name, geom) VALUES (%s, %s, %s, "
            f"{point}) ON CONFLICT (amenity_id) DO NOTHING",
            [(x.site_id, x.kind.value, x.site_id, x.coord.lon, x.coord.lat) for x in amenities])
    return {"planning_area": len(s.planning_areas), "car_park": len(s.car_parks),
            "station": len(s.stations), "connector": len(s.connectors),
            "connector_reading": len(ev), "car_park_reading": len(cp),
            "stg_collect_slot": 2 * len(slots), "stg_amenity": len(amenities)}


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Set DATABASE_URL to a scratch database (migrated with optev-db migrate).")
        return 1
    with psycopg.connect(url) as conn:
        written = seed(conn)
        conn.commit()
    for table, n in written.items():
        print(f"{table:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
