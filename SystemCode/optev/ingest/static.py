"""Load the static datasets into Postgres. SYSTEM_DESIGN.md §4.1 step 2, spec 004.

Each data.gov.sg file is fetched keyless through poll-download into `data/raw/` (gitignored)
and read by a pure parser, so the tests need no network. Each source is written in its own
transaction as upserts keyed on the primary key that skip unchanged rows, so a second run
changes nothing. A bad record is logged and skipped; it never fails the run. Columns that
conform owns (`car_park.has_live_feed`, `connector.ever_active`) are never written here.
"""

import csv
import io
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg

from optev.contracts import CarPark, Coordinate, PlanningArea, SiteKind
from optev.ingest.conform import svy21_to_wgs84

log = logging.getLogger(__name__)

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"  # repo root, as .gitignore anchors it
POLL = "https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download"
# data.gov.sg ids, found and checked on 17 Oct 2026 (spec 004)
DATASETS = {
    "planning_area": "d_2cc750190544007400b2cfd5d7f53209",  # MP2025 Planning Area Boundary
    "hdb_car_park": "d_23f946fa557947f93a8043bbef41dd09",   # HDB Carpark Information
    "ura_car_park": "d_9bf8620ecfdc8a5f8f77e3f02160af5c",   # Capacity of URA Parking Places
    "land_use": "d_a8c3546b26712e35021f3a681d0353ae",       # MP2025 Land Use Layer
    "hawker": "d_4a086da0a5553be1d89383cd90d07ecd",         # NEA Hawker Centres
    "community_club": "d_9de02d3fb33d96da1855f4fbef549a0f",  # PA Community Club / PAssion WaVe
    "petrol": "d_f5db74053e49ce79039f1b13549d1efb",         # Customs petroleum premises
    "residents": "d_7f243956483d5901f237e6f87b096636",      # Census 2020, area x dwelling
}
RETRY_WAIT_S = (0, 2, 5, 10, 20, 40)  # poll-download answers without a link when called fast
LAND_USE_TOLERANCE_DEG = 0.00001  # ~1.1 m, far below the 50 m match threshold (spec 004)
LAND_USE_MAX_BYTES = 60 * 1024 * 1024  # above this, stop and ask (spec 004)
RESIDENTS_YEAR = 2020
SERVICE_STATION = re.compile(r"service station|petrol station|filling station", re.I)
_AREA_TOTAL = re.compile(r"^(.+?)\s*-\s*Total$")  # the census writes "Changi- Total" once
_KML_FIELD = re.compile(r"<th>([^<]+)</th>\s*<td>([^<]*)</td>")
_BAD = (KeyError, IndexError, TypeError, ValueError)  # pydantic's ValidationError is a ValueError


class LandUseTooLarge(RuntimeError):
    """`stg_land_use` came out above LAND_USE_MAX_BYTES; the load is rolled back."""


@dataclass(frozen=True)
class Amenity:
    """A row of `stg_amenity`: somewhere that could become a candidate site."""

    amenity_id: str
    kind: SiteKind
    name: str
    address: str | None
    status: str | None
    coord: Coordinate


# Fetching -----------------------------------------------------------------------------


def download(client: httpx.Client, name: str, today: date | None = None) -> Path:
    """Fetch one dataset into RAW as `<name>_<date>.<ext>`. Reuses today's file if present."""
    stamp = (today or date.today()).isoformat()
    existing = sorted(RAW.glob(f"{name}_{stamp}.*"))
    if existing:
        return existing[0]
    link = ""
    for wait in RETRY_WAIT_S:
        time.sleep(wait)
        try:
            link = client.get(POLL.format(DATASETS[name])).json()["data"]["url"]
            break
        except (httpx.HTTPError, *_BAD):
            log.info("%s: no download link yet, retrying", name)
    if not link:
        raise RuntimeError(f"data.gov.sg gave no download link for {name}")
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{name}_{stamp}{Path(urlparse(link).path).suffix or '.dat'}"
    part = path.with_suffix(path.suffix + ".part")
    with client.stream("GET", link) as resp, part.open("wb") as fh:
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            fh.write(chunk)
    part.replace(path)
    log.info("%s: downloaded %s (%d bytes)", name, path.name, path.stat().st_size)
    return path


# Parsing ------------------------------------------------------------------------------


def _skip(label: str, record: Any, err: Exception) -> None:
    log.warning("%s record skipped: %s: %s: %.200r", label, type(err).__name__, err, record)


def _text(value: Any) -> str | None:
    s = str(value).replace("\xa0", " ").strip() if value is not None else ""
    return s or None


def _point(feature: Mapping[str, Any]) -> Coordinate:
    geom = feature["geometry"]
    if geom["type"] != "Point":
        raise ValueError(f"expected a Point, got {geom['type']}")
    lon, lat = geom["coordinates"][:2]
    return Coordinate(lat=lat, lon=lon)


def _polygon(feature: Mapping[str, Any]) -> str:
    geom = feature["geometry"]
    if geom["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"expected a polygon, got {geom['type']}")
    return json.dumps(geom)


def _parse[T](
    label: str, records: Iterable[Any], build: Callable[[Any], T | None], key: Callable[[T], str]
) -> tuple[list[T], int]:
    """Build a row from each record; None filters a record out without counting it. A bad
    record, or a second record with the same key, is logged and counted as skipped."""
    rows: dict[str, T] = {}
    skipped = 0
    for record in records:
        try:
            row = build(record)
            if row is None:
                continue
            if key(row) in rows:
                raise ValueError(f"duplicate id {key(row)}")
            rows[key(row)] = row
        except _BAD as err:
            skipped += 1
            _skip(label, record, err)
    return list(rows.values()), skipped


def parse_planning_areas(geojson: Mapping[str, Any]) -> tuple[list[tuple[PlanningArea, str]], int]:
    """MP2025 boundaries: (PlanningArea, GeoJSON polygon) per area, keyed `PLN_AREA_C`."""
    def build(f: Mapping[str, Any]) -> tuple[PlanningArea, str]:
        p = f["properties"]
        code = _text(p["PLN_AREA_C"])
        if not code:
            raise ValueError("no PLN_AREA_C")
        return PlanningArea(code=code, name=p["PLN_AREA_N"], region=_text(p.get("REGION_N"))), \
            _polygon(f)
    return _parse("planning_area", geojson["features"], build, lambda r: r[0].code)


def parse_hdb_car_parks(rows: Iterable[Mapping[str, str]]) -> tuple[list[CarPark], int]:
    """HDB registry rows, SVY21 x/y converted to WGS84. `total_lots` stays None: the HDB
    registry has no lot count, conform takes it from the readings."""
    def build(r: Mapping[str, str]) -> CarPark:
        number = r["car_park_no"].strip()
        coord = svy21_to_wgs84(float(r["x_coord"]), float(r["y_coord"]))
        if not number or coord is None:
            raise ValueError("no car_park_no" if not number else "x/y outside Singapore")
        return CarPark(car_park_id=f"hdb:{number}", name=_text(r.get("address")) or number,
                       coord=coord, car_park_type=_text(r.get("car_park_type")))
    return _parse("hdb_car_park", rows, build, lambda c: c.car_park_id)


def parse_ura_car_parks(geojson: Mapping[str, Any]) -> tuple[list[CarPark], int]:
    """URA parking places with `NO_CAR > 0` only (§4.1 step 2); `NO_CAR` is the lot count."""
    def build(f: Mapping[str, Any]) -> CarPark | None:
        p = f["properties"]
        lots = int(p.get("NO_CAR") or 0)
        if lots <= 0:
            return None
        code = _text(p["PP_CODE"])
        if not code:
            raise ValueError("no PP_CODE")
        return CarPark(car_park_id=f"ura:{code}", name=_text(p.get("PARKING_PL")) or code,
                       coord=_point(f), total_lots=lots)
    return _parse("ura_car_park", geojson["features"], build, lambda c: c.car_park_id)


def parse_hawkers(geojson: Mapping[str, Any]) -> tuple[list[Amenity], int]:
    """NEA hawker centres, every STATUS kept (including under construction), as published."""
    def build(f: Mapping[str, Any]) -> Amenity:
        p = f["properties"]
        return Amenity(f"hawker:{p['OBJECTID']}", SiteKind.HAWKER_CENTRE, p["NAME"].strip(),
                       _text(p.get("ADDRESS_MYENV")), _text(p.get("STATUS")), _point(f))
    return _parse("hawker", geojson["features"], build, lambda a: a.amenity_id)


def parse_community_clubs(geojson: Mapping[str, Any]) -> tuple[list[Amenity], int]:
    """PA outlets with DESCRIPTION 'CC'; PAssion WaVe outlets are left out."""
    def build(f: Mapping[str, Any]) -> Amenity | None:
        p = f["properties"]
        if _text(p.get("DESCRIPTION")) != "CC":
            return None
        parts = [_text(p.get("ADDRESSBLOCKHOUSENUMBER")), _text(p.get("ADDRESSSTREETNAME"))]
        postal = _text(p.get("ADDRESSPOSTALCODE"))
        address = " ".join(s for s in parts if s) + (f", Singapore {postal}" if postal else "")
        return Amenity(f"cc:{p['OBJECTID']}", SiteKind.COMMUNITY_FACILITY, p["NAME"].strip(),
                       address.strip(", ") or None, "CC", _point(f))
    return _parse("community_club", geojson["features"], build, lambda a: a.amenity_id)


def parse_petrol(geojson: Mapping[str, Any]) -> tuple[list[Amenity], int]:
    """Customs premises whose name says service station. The list holds terminals, refineries
    and power stations, so this keeps none today; the source is dropped (spec 004)."""
    def build(f: Mapping[str, Any]) -> Amenity | None:
        fields = dict(_KML_FIELD.findall(f["properties"]["Description"]))
        name = _text(fields.get("COMPANY_NAME")) or ""
        if not SERVICE_STATION.search(f"{name} {fields.get('BUILDING_NAME', '')}"):
            return None
        return Amenity(f"petrol:{f['properties']['Name']}", SiteKind.PETROL_STATION, name,
                       _text(fields.get("ROAD_NAME")), None, _point(f))
    return _parse("petrol", geojson["features"], build, lambda a: a.amenity_id)


def parse_land_use(geojson: Mapping[str, Any]) -> tuple[list[tuple[str, str, str]], int]:
    """(OBJECTID, LU_DESC, GeoJSON polygon) per plot; every other attribute is dropped."""
    def build(f: Mapping[str, Any]) -> tuple[str, str, str]:
        p = f["properties"]
        desc = _text(p.get("LU_DESC"))
        if not desc:
            raise ValueError("no LU_DESC")
        return str(p["OBJECTID"]), desc, _polygon(f)
    return _parse("land_use", geojson["features"], build, lambda r: r[0])


def parse_residents(
    text: str, areas: Mapping[str, str]
) -> tuple[list[tuple[str, int, int]], int]:
    """(planning area code, residents, residents in HDB flats) from the census `<Area> - Total`
    rows. `areas` maps upper-case planning-area names to codes; '-' in the census means 0."""
    def build(row: Sequence[str]) -> tuple[str, int, int] | None:
        found = _AREA_TOTAL.match(row[0].strip()) if row else None
        if not found:
            return None
        count = [0 if v.strip() == "-" else int(v.replace(",", "")) for v in row[1:3]]
        return areas[found.group(1).strip().upper()], count[0], count[1]
    return _parse("residents", csv.reader(io.StringIO(text)), build, lambda r: r[0])


# Writing ------------------------------------------------------------------------------

UPSERT_AREA = """INSERT INTO planning_area AS t (code, name, region, geom)
    VALUES (%s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))
    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, region = EXCLUDED.region,
    geom = EXCLUDED.geom
    WHERE (t.name, t.region, t.geom) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.region,
    EXCLUDED.geom)"""
# planning area by point-in-polygon; a NULL lot count (HDB) keeps the one conform set
UPSERT_CAR_PARK = """INSERT INTO car_park AS t (car_park_id, name, car_park_type, total_lots,
    planning_area, geom)
    SELECT v.id, v.name, v.kind, v.lots, (SELECT code FROM planning_area pa
        WHERE ST_Contains(pa.geom, v.geom) ORDER BY code LIMIT 1), v.geom
    FROM (SELECT %s AS id, %s AS name, %s AS kind, %s::integer AS lots,
        ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom) v
    ON CONFLICT (car_park_id) DO UPDATE SET name = EXCLUDED.name,
    car_park_type = EXCLUDED.car_park_type,
    total_lots = COALESCE(EXCLUDED.total_lots, t.total_lots),
    planning_area = EXCLUDED.planning_area, geom = EXCLUDED.geom
    WHERE (t.name, t.car_park_type, t.total_lots, t.planning_area, t.geom)
    IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.car_park_type,
    COALESCE(EXCLUDED.total_lots, t.total_lots), EXCLUDED.planning_area, EXCLUDED.geom)"""
UPSERT_AMENITY = """INSERT INTO stg_amenity AS t (amenity_id, kind, name, address, status, geom)
    VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    ON CONFLICT (amenity_id) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name,
    address = EXCLUDED.address, status = EXCLUDED.status, geom = EXCLUDED.geom
    WHERE (t.kind, t.name, t.address, t.status, t.geom) IS DISTINCT FROM
    (EXCLUDED.kind, EXCLUDED.name, EXCLUDED.address, EXCLUDED.status, EXCLUDED.geom)"""
STAGE_LAND_USE = """CREATE TEMP TABLE land_use_in (land_use_id text, lu_desc text,
    geojson text) ON COMMIT DROP"""
UPSERT_LAND_USE = """INSERT INTO stg_land_use AS t (land_use_id, lu_desc, geom)
    SELECT land_use_id, lu_desc,
    ST_Multi(ST_SimplifyPreserveTopology(ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326), %s))
    FROM land_use_in
    ON CONFLICT (land_use_id) DO UPDATE SET lu_desc = EXCLUDED.lu_desc, geom = EXCLUDED.geom
    WHERE (t.lu_desc, t.geom) IS DISTINCT FROM (EXCLUDED.lu_desc, EXCLUDED.geom)"""
UPSERT_RESIDENTS = """INSERT INTO stg_residents AS t (planning_area, residents, residents_hdb,
    source_year) VALUES (%s, %s, %s, %s)
    ON CONFLICT (planning_area) DO UPDATE SET residents = EXCLUDED.residents,
    residents_hdb = EXCLUDED.residents_hdb, source_year = EXCLUDED.source_year
    WHERE (t.residents, t.residents_hdb, t.source_year) IS DISTINCT FROM
    (EXCLUDED.residents, EXCLUDED.residents_hdb, EXCLUDED.source_year)"""


def write_planning_areas(cur: Any, rows: Sequence[tuple[PlanningArea, str]]) -> int:
    cur.executemany(UPSERT_AREA, [(a.code, a.name, a.region, g) for a, g in rows])
    return int(cur.rowcount)


def write_car_parks(cur: Any, rows: Sequence[CarPark]) -> int:
    cur.executemany(UPSERT_CAR_PARK, [
        (c.car_park_id, c.name, c.car_park_type, c.total_lots, c.coord.lon, c.coord.lat)
        for c in rows
    ])
    return int(cur.rowcount)


def write_amenities(cur: Any, rows: Sequence[Amenity]) -> int:
    cur.executemany(UPSERT_AMENITY, [
        (a.amenity_id, a.kind.value, a.name, a.address, a.status, a.coord.lon, a.coord.lat)
        for a in rows
    ])
    return int(cur.rowcount)


def write_land_use(cur: Any, rows: Sequence[tuple[str, str, str]]) -> int:
    """Stage the plots with COPY, simplify them on insert, then check the table's size."""
    cur.execute(STAGE_LAND_USE)
    with cur.copy("COPY land_use_in (land_use_id, lu_desc, geojson) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
    cur.execute(UPSERT_LAND_USE, (LAND_USE_TOLERANCE_DEG,))
    changed = int(cur.rowcount)
    cur.execute("SELECT pg_total_relation_size('stg_land_use'), "
                "pg_database_size(current_database())")
    table_bytes, db_bytes = cur.fetchone()
    log.info("stg_land_use is %.1f MB; database %.1f MB", table_bytes / 2**20, db_bytes / 2**20)
    if table_bytes > LAND_USE_MAX_BYTES:
        raise LandUseTooLarge(f"stg_land_use would be {table_bytes / 2**20:.1f} MB, above "
                              f"{LAND_USE_MAX_BYTES / 2**20:.0f} MB; rolled back")
    return changed


def write_residents(cur: Any, rows: Sequence[tuple[str, int, int]]) -> int:
    cur.executemany(UPSERT_RESIDENTS, [(c, n, hdb, RESIDENTS_YEAR) for c, n, hdb in rows])
    return int(cur.rowcount)


# Orchestration ------------------------------------------------------------------------


def _write[T](conn: psycopg.Connection[Any], label: str,
              writer: Callable[[Any, Sequence[T]], int], rows: Sequence[T], skipped: int) -> int:
    """One source in one transaction; rolled back whole if the writer raises."""
    with conn.transaction(), conn.cursor() as cur:
        changed = writer(cur, rows)
    log.info("%s: %d rows, %d inserted or changed, %d skipped", label, len(rows), changed,
             skipped)
    return len(rows)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_static() -> dict[str, int]:
    """Rows loaded per static source. Needs DATABASE_URL and migrations 001-004."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    loaded: dict[str, int] = {}
    headers = {"User-Agent": "optev-static/0.1"}
    with httpx.Client(timeout=300, follow_redirects=True, headers=headers) as client, \
            psycopg.connect(url, autocommit=True) as conn:
        areas, bad = parse_planning_areas(_json(download(client, "planning_area")))
        loaded["planning_area"] = _write(conn, "planning_area", write_planning_areas, areas, bad)
        hdb_text = download(client, "hdb_car_park").read_text(encoding="utf-8-sig")
        hdb, bad = parse_hdb_car_parks(csv.DictReader(io.StringIO(hdb_text)))
        loaded["hdb_car_park"] = _write(conn, "hdb_car_park", write_car_parks, hdb, bad)
        ura, bad = parse_ura_car_parks(_json(download(client, "ura_car_park")))
        loaded["ura_car_park"] = _write(conn, "ura_car_park", write_car_parks, ura, bad)
        amenity_parsers = (("hawker", parse_hawkers), ("community_club", parse_community_clubs),
                           ("petrol", parse_petrol))
        for name, parse in amenity_parsers:
            amenities, bad = parse(_json(download(client, name)))
            loaded[name] = _write(conn, name, write_amenities, amenities, bad)
        if not loaded["petrol"]:
            log.warning("petrol: no service stations in the Customs list; source dropped")
        plots, bad = parse_land_use(_json(download(client, "land_use")))
        loaded["land_use"] = _write(conn, "land_use", write_land_use, plots, bad)
        names: dict[str, str] = dict(
            conn.execute("SELECT upper(name), code FROM planning_area").fetchall())
        census = download(client, "residents").read_text(encoding="utf-8-sig")
        residents, bad = parse_residents(census, names)
        loaded["residents"] = _write(conn, "residents", write_residents, residents, bad)
    return loaded
