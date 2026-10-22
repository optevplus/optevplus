"""Stage 1 · conform (SYSTEM_DESIGN.md §4.1, method step 3).

Turns car parks, amenities, stations and connector readings into `candidate_site`,
`station_site` and `site_context`. `conform_records` is the pure core and runs on
`optev.sample`; `conform()` reads and writes the §3.2 tables.

Coordinates are stored as WGS84. Every distance is computed in SVY21 (EPSG:3414) metres.
A bad row is logged, counted and skipped; it never fails the run.
"""

import logging
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

import numpy as np
from pydantic import BaseModel, ValidationError
from pyproj import Transformer

from optev.assumptions import AMENITY_LINK_M, MATCH_THRESHOLDS_M
from optev.contracts import (
    CandidateSite,
    CarPark,
    Connector,
    ConnectorReading,
    ConnectorStatus,
    Coordinate,
    SiteKind,
    Station,
)

log = logging.getLogger(__name__)

_TO_WGS84 = Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)
_TO_SVY21 = Transformer.from_crs("EPSG:4326", "EPSG:3414", always_xy=True)

ACTIVE = frozenset({ConnectorStatus.AVAILABLE, ConnectorStatus.OCCUPIED})
# §3.3: a car park's site id is its source-prefixed id, and the source decides the kind
CAR_PARK_KIND = {
    "hdb": SiteKind.HDB_CAR_PARK,
    "ura": SiteKind.PUBLIC_CAR_PARK,
    "mall": SiteKind.PUBLIC_CAR_PARK,
}
AMENITY_KINDS = frozenset(
    {SiteKind.HAWKER_CENTRE, SiteKind.COMMUNITY_FACILITY, SiteKind.PETROL_STATION}
)

class StationSite(TypedDict):
    station_id: str
    site_id: str
    distance_m: float
    threshold_m: int


@dataclass
class Conformed:
    car_parks: list[CarPark]
    connectors: list[Connector]
    sites: list[CandidateSite]
    station_site: list[StationSite]
    amenities_nearby: dict[str, int]
    nearest_point_m: dict[str, float | None]
    issues: dict[str, int] = field(default_factory=dict)
    """Rows counted rather than raised: unknown sources, duplicates, unmatched car parks,
    unlinked stations."""


def _count(issues: dict[str, int], key: str) -> None:
    issues[key] = issues.get(key, 0) + 1


# Projection ---------------------------------------------------------------------------


def svy21_to_wgs84(x: float, y: float) -> Coordinate | None:
    """SVY21 easting and northing to WGS84. None when the point is not in Singapore."""
    lon, lat = _TO_WGS84.transform(x, y)
    try:
        return Coordinate(lat=lat, lon=lon)
    except ValidationError:
        return None


def to_svy21(coords: Iterable[Coordinate]) -> np.ndarray:
    """WGS84 coordinates to an (n, 2) array of SVY21 metres."""
    cs = list(coords)
    if not cs:
        return np.empty((0, 2))
    x, y = _TO_SVY21.transform([c.lon for c in cs], [c.lat for c in cs])
    return np.column_stack([x, y])


def metres(a: Coordinate, b: Coordinate) -> float:
    (ax, ay), (bx, by) = to_svy21([a, b])
    return float(np.hypot(ax - bx, ay - by))


def _distances(points: np.ndarray, origin: np.ndarray) -> np.ndarray:
    return np.asarray(np.hypot(points[:, 0] - origin[0], points[:, 1] - origin[1]))


# Defensive parsing --------------------------------------------------------------------


def parse_rows[M: BaseModel](
    model: type[M], rows: Iterable[Mapping[str, Any]], issues: dict[str, int], label: str
) -> list[M]:
    """Validate rows into contract objects. A malformed row is counted as `bad_<label>`."""
    out: list[M] = []
    for row in rows:
        try:
            out.append(model.model_validate(row))
        except ValidationError as e:
            _count(issues, f"bad_{label}")
            log.warning("skipped %s row: %d errors, first: %s", label, e.error_count(),
                        e.errors()[0]["msg"])
    return out


def unique[M: BaseModel](
    items: Iterable[M], key: str, issues: dict[str, int], label: str
) -> list[M]:
    """Keep the first row per id. Later copies are counted as `duplicate_<label>`."""
    seen: dict[str, M] = {}
    for item in items:
        k = getattr(item, key)
        if k in seen:
            _count(issues, f"duplicate_{label}")
        else:
            seen[k] = item
    return list(seen.values())


# Connectors ---------------------------------------------------------------------------


def observed_connectors(readings: Iterable[ConnectorReading]) -> dict[str, bool]:
    """Every connector in the readings, and whether it was ever seen available or occupied
    (invariant 3)."""
    seen: dict[str, bool] = {}
    for r in readings:
        seen[r.connector_id] = seen.get(r.connector_id, False) or r.status in ACTIVE
    return seen


def mark_ever_active(
    connectors: Iterable[Connector], observed: Mapping[str, bool]
) -> list[Connector]:
    """Set `ever_active`. Once true it stays true, so pruning old readings never
    un-installs a connector."""
    return [
        c if c.ever_active or not observed.get(c.connector_id, False)
        else c.model_copy(update={"ever_active": True})
        for c in connectors
    ]


def match_readings(
    connectors: Sequence[Connector], stations: Sequence[Station],
    observed: Mapping[str, bool], issues: dict[str, int],
) -> None:
    """A connector reading gets its coordinate through connector -> station. Every break in
    that chain is counted: `reading_without_connector`, `connector_without_reading` and
    `connector_without_station`."""
    known = {c.connector_id for c in connectors}
    orphans = set(observed) - known
    if orphans:
        issues["reading_without_connector"] = (
            issues.get("reading_without_connector", 0) + len(orphans))
        log.warning("%d connectors in the readings have no connector row, e.g. %s",
                    len(orphans), sorted(orphans)[0])
    station_ids = {s.station_id for s in stations}
    for c in connectors:
        if c.connector_id not in observed:
            _count(issues, "connector_without_reading")
        if c.station_id not in station_ids:
            _count(issues, "connector_without_station")


# Registry <-> live feed ----------------------------------------------------------------


def match_feed(
    car_parks: Iterable[CarPark], feed: Mapping[str, int | None], issues: dict[str, int]
) -> list[CarPark]:
    """Match registry car parks to the live feed by their §3.3 id. Sets `has_live_feed`, and
    `total_lots` from the feed's latest reading, since the HDB feed is the only source of lot
    counts. The match fails both ways, so both are counted: `registry_without_feed`, and
    `feed_without_registry` (no coordinate, so it cannot become a site)."""
    out = []
    for cp in car_parks:
        update: dict[str, Any] = {"has_live_feed": cp.car_park_id in feed}
        if cp.car_park_id not in feed:
            _count(issues, "registry_without_feed")
        elif feed[cp.car_park_id] is not None:
            update["total_lots"] = feed[cp.car_park_id]
        out.append(cp.model_copy(update=update))
    orphans = set(feed) - {cp.car_park_id for cp in out}
    if orphans:
        issues["feed_without_registry"] = issues.get("feed_without_registry", 0) + len(orphans)
        log.warning("%d feed car parks have no registry row, e.g. %s", len(orphans),
                    sorted(orphans)[0])
    return out


# Sites --------------------------------------------------------------------------------


def car_park_site(car_park: CarPark) -> CandidateSite | None:
    """A car park as a candidate site. None when its id carries no known source prefix."""
    prefix, sep, _ = car_park.car_park_id.partition(":")
    kind = CAR_PARK_KIND.get(prefix) if sep else None
    if kind is None:
        return None
    return CandidateSite(
        site_id=car_park.car_park_id,
        kind=kind,
        coord=car_park.coord,
        planning_area=car_park.planning_area,
        car_park_id=car_park.car_park_id,
        total_lots=car_park.total_lots,
    )


def build_sites(
    car_parks: Sequence[CarPark], amenities: Sequence[CandidateSite], issues: dict[str, int]
) -> tuple[list[CandidateSite], dict[str, int]]:
    """Car parks become sites. An amenity within AMENITY_LINK_M of a car park adds to that
    car park's `amenities_nearby` (the nearest one, ties by id); otherwise it is a site."""
    sites: list[CandidateSite] = []
    for cp in car_parks:
        site = car_park_site(cp)
        if site is None:
            _count(issues, "unknown_source_car_park")
            log.warning("car park %s has no known source prefix", cp.car_park_id)
        else:
            sites.append(site)
    sites.sort(key=lambda s: s.site_id)
    nearby = {s.site_id: 0 for s in sites}

    kept = []
    for a in amenities:
        if a.kind in AMENITY_KINDS:
            kept.append(a)
        else:
            _count(issues, "unknown_kind_amenity")
    car_park_xy = to_svy21(s.coord for s in sites)
    standalone = []
    for amenity, xy in zip(kept, to_svy21(a.coord for a in kept), strict=True):
        if len(sites):
            d = _distances(car_park_xy, xy)
            i = int(np.argmin(d))
            if d[i] <= AMENITY_LINK_M:
                nearby[sites[i].site_id] += 1
                continue
        standalone.append(amenity.model_copy(update={"car_park_id": None}))
    return sites + sorted(standalone, key=lambda s: s.site_id), nearby


def associate(stations: Sequence[Station], sites: Sequence[CandidateSite]) -> list[StationSite]:
    """Every station-site pair within the largest threshold, tagged with the smallest
    threshold it meets."""
    thresholds = sorted(MATCH_THRESHOLDS_M)
    site_xy = to_svy21(s.coord for s in sites)
    pairs: list[StationSite] = []
    for station, xy in zip(stations, to_svy21(s.coord for s in stations), strict=True):
        d = _distances(site_xy, xy)
        for i in np.flatnonzero(d <= thresholds[-1]):
            dist = round(float(d[i]), 1)
            pairs.append(StationSite(
                station_id=station.station_id,
                site_id=sites[int(i)].site_id,
                distance_m=dist,
                threshold_m=next(t for t in thresholds if dist <= t),
            ))
    return sorted(pairs, key=lambda p: (p["station_id"], p["site_id"]))


def count_existing(
    connectors: Iterable[Connector], pairs: Iterable[StationSite]
) -> dict[str, int]:
    """Active connectors per site. A station's connectors count at its nearest site only
    (ties by id), so a plug between two car parks is never counted twice."""
    home: dict[str, str] = {}
    for p in sorted(pairs, key=lambda p: (p["distance_m"], p["site_id"])):
        home.setdefault(p["station_id"], p["site_id"])
    counts: dict[str, int] = defaultdict(int)
    for c in connectors:
        if c.ever_active and c.station_id in home:
            counts[home[c.station_id]] += 1
    return dict(counts)


def nearest_point_m(
    sites: Sequence[CandidateSite], stations: Sequence[Station], connectors: Iterable[Connector]
) -> dict[str, float | None]:
    """Metres to the closest station with an active connector; None when there is none."""
    live_ids = {c.station_id for c in connectors if c.ever_active}
    live = [s for s in stations if s.station_id in live_ids]
    if not live:
        return {s.site_id: None for s in sites}
    live_xy = to_svy21(s.coord for s in live)
    return {
        s.site_id: round(float(_distances(live_xy, xy).min()), 1)
        for s, xy in zip(sites, to_svy21(s.coord for s in sites), strict=True)
    }


def conform_records(
    car_parks: Iterable[CarPark],
    amenities: Iterable[CandidateSite],
    stations: Iterable[Station],
    connectors: Iterable[Connector],
    observed: Mapping[str, bool],
    feed: Mapping[str, int | None],
    issues: dict[str, int] | None = None,
) -> Conformed:
    """Everything in step 3 except point-in-polygon, which needs PostGIS. `observed` maps
    each connector in the readings to whether it was ever active; `feed` maps each car park
    in the readings to its latest lot count."""
    issues = {} if issues is None else issues
    cps = match_feed(unique(car_parks, "car_park_id", issues, "car_park"), feed, issues)
    ams = unique(amenities, "site_id", issues, "amenity")
    sts = unique(stations, "station_id", issues, "station")
    cons = mark_ever_active(unique(connectors, "connector_id", issues, "connector"), observed)
    match_readings(cons, sts, observed, issues)

    sites, nearby = build_sites(cps, ams, issues)
    pairs = associate(sts, sites)
    linked = {p["station_id"] for p in pairs}
    for s in sts:
        if s.station_id not in linked:
            _count(issues, "station_unlinked")
    counts = count_existing(cons, pairs)
    sites = [s.model_copy(update={"existing_connectors": counts.get(s.site_id, 0)}) for s in sites]
    return Conformed(
        car_parks=cps,
        connectors=cons,
        sites=sites,
        station_site=pairs,
        amenities_nearby={s.site_id: nearby.get(s.site_id, 0) for s in sites},
        nearest_point_m=nearest_point_m(sites, sts, cons),
        issues=issues,
    )


# Database -----------------------------------------------------------------------------

READ_CAR_PARKS = """SELECT car_park_id, name, ST_Y(geom) AS lat, ST_X(geom) AS lon,
    planning_area, total_lots, car_park_type, has_live_feed FROM car_park"""
READ_STATIONS = """SELECT station_id, ST_Y(geom) AS lat, ST_X(geom) AS lon, operator,
    address, planning_area, provenance FROM station"""
READ_CONNECTORS = "SELECT connector_id, station_id, plug_type, power_kw, ever_active FROM connector"
READ_OBSERVED = """SELECT connector_id,
    bool_or(status IN ('available', 'occupied')) AS active
    FROM connector_reading GROUP BY connector_id"""

# the latest reading per car park: its lot count is the only one for HDB car parks
READ_FEED = """SELECT DISTINCT ON (car_park_id) car_park_id, total_lots
    FROM car_park_reading WHERE lot_type = 'C' ORDER BY car_park_id, collected_ts DESC"""

MARK_FEED = "UPDATE car_park SET has_live_feed = (car_park_id = ANY(%s))"
SET_LOTS = "UPDATE car_park SET total_lots = %s WHERE car_park_id = %s"
MARK_ACTIVE = "UPDATE connector SET ever_active = true WHERE connector_id = ANY(%s)"
UPSERT_SITE = """INSERT INTO candidate_site (site_id, kind, planning_area, car_park_id,
    total_lots, existing_connectors, provenance, geom)
    VALUES (%s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    ON CONFLICT (site_id) DO UPDATE SET kind = EXCLUDED.kind,
    planning_area = EXCLUDED.planning_area, car_park_id = EXCLUDED.car_park_id,
    total_lots = EXCLUDED.total_lots, existing_connectors = EXCLUDED.existing_connectors,
    provenance = EXCLUDED.provenance, geom = EXCLUDED.geom"""
FILL_PLANNING_AREA = """UPDATE candidate_site s SET planning_area = pa.code
    FROM planning_area pa WHERE s.planning_area IS NULL AND ST_Contains(pa.geom, s.geom)"""
CLEAR_STATION_SITE = "DELETE FROM station_site"
INSERT_STATION_SITE = """INSERT INTO station_site (station_id, site_id, distance_m, threshold_m)
    VALUES (%s, %s, %s, %s)"""
UPSERT_CONTEXT = """INSERT INTO site_context (site_id, amenities_nearby, nearest_point_m)
    VALUES (%s, %s, %s) ON CONFLICT (site_id) DO UPDATE SET
    amenities_nearby = EXCLUDED.amenities_nearby, nearest_point_m = EXCLUDED.nearest_point_m"""

# the static loads (migration 004, spec 004): amenities, land-use plots, residents per area
HAS_STAGING = "SELECT to_regclass('stg_amenity') IS NOT NULL AS staged"
READ_AMENITIES = """SELECT amenity_id AS site_id, kind, ST_Y(geom) AS lat, ST_X(geom) AS lon
    FROM stg_amenity"""
# overlapping plots: the smallest id wins, so a rerun gives the same answer
FILL_LAND_USE = """UPDATE site_context sc SET land_use = (
    SELECT l.lu_desc FROM stg_land_use l JOIN candidate_site s ON ST_Contains(l.geom, s.geom)
    WHERE s.site_id = sc.site_id ORDER BY l.land_use_id LIMIT 1)"""
FILL_RESIDENTS = """UPDATE site_context sc SET residents_in_area = (
    SELECT r.residents FROM stg_residents r JOIN candidate_site s
    ON s.planning_area = r.planning_area WHERE s.site_id = sc.site_id)"""
COUNT_UNPLACED = """SELECT
    count(*) FILTER (WHERE s.planning_area IS NULL) AS site_without_planning_area,
    count(*) FILTER (WHERE sc.land_use IS NULL) AS site_without_land_use
    FROM candidate_site s JOIN site_context sc USING (site_id)"""


def _with_coord(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("lat", "lon")}
    out["coord"] = {"lat": row["lat"], "lon": row["lon"]}
    return out


def write(cur: Any, result: Conformed) -> dict[str, int]:
    """Upsert the conformed rows. Keyed on primary keys, so a rerun gives the same tables.
    `station_site` is rebuilt whole, since pairs can disappear when a station moves.
    `land_use` and `residents_in_area` are filled afterwards by `fill_context`."""
    live = [cp for cp in result.car_parks if cp.has_live_feed]
    cur.execute(MARK_FEED, ([cp.car_park_id for cp in live],))
    cur.executemany(SET_LOTS, [(cp.total_lots, cp.car_park_id) for cp in live
                               if cp.total_lots is not None])
    active = [c.connector_id for c in result.connectors if c.ever_active]
    cur.execute(MARK_ACTIVE, (active,))
    cur.executemany(UPSERT_SITE, [
        (s.site_id, s.kind.value, s.planning_area, s.car_park_id, s.total_lots,
         s.existing_connectors, s.provenance.value, s.coord.lon, s.coord.lat)
        for s in result.sites
    ])
    cur.execute(FILL_PLANNING_AREA)
    cur.execute(CLEAR_STATION_SITE)
    cur.executemany(INSERT_STATION_SITE, [
        (p["station_id"], p["site_id"], p["distance_m"], p["threshold_m"])
        for p in result.station_site
    ])
    cur.executemany(UPSERT_CONTEXT, [
        (s.site_id, result.amenities_nearby[s.site_id], result.nearest_point_m[s.site_id])
        for s in result.sites
    ])
    return {
        "car_park": len(result.car_parks),
        "connector": len(active),
        "candidate_site": len(result.sites),
        "station_site": len(result.station_site),
        "site_context": len(result.sites),
    }


def amenity_sites(rows: Iterable[Mapping[str, Any]], issues: dict[str, int]) -> list[CandidateSite]:
    """`stg_amenity` rows as candidate sites; `build_sites` links or keeps each one."""
    return parse_rows(CandidateSite, map(_with_coord, rows), issues, "amenity")


def fill_context(cur: Any) -> dict[str, int]:
    """Point-in-polygon land use and residents per planning area into `site_context`, after
    `write`. Returns the sites left outside every planning area or land-use plot: they stay
    NULL (design §4.1), so the run says how many."""
    cur.execute(FILL_LAND_USE)
    cur.execute(FILL_RESIDENTS)
    counts = cur.execute(COUNT_UNPLACED).fetchone()
    return {k: int(n) for k, n in counts.items() if n}


def conform() -> dict[str, int]:
    """Rows upserted per table. Needs DATABASE_URL and migrations 001-002; with 004 (the
    static loads) it also adds amenity sites, land use and residents."""
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    issues: dict[str, int] = {}
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        car_parks = parse_rows(
            CarPark, map(_with_coord, cur.execute(READ_CAR_PARKS)), issues, "car_park")
        row = cur.execute(HAS_STAGING).fetchone()
        staged = bool(row and row["staged"])
        if staged:
            amenities = amenity_sites(cur.execute(READ_AMENITIES), issues)
        else:
            amenities = []
            log.info("conform: migration 004 not applied, car park sites only")
        stations = parse_rows(
            Station, map(_with_coord, cur.execute(READ_STATIONS)), issues, "station")
        connectors = parse_rows(Connector, cur.execute(READ_CONNECTORS), issues, "connector")
        observed = {r["connector_id"]: r["active"] for r in cur.execute(READ_OBSERVED)}
        feed = {r["car_park_id"]: r["total_lots"] for r in cur.execute(READ_FEED)}
        result = conform_records(car_parks, amenities, stations, connectors, observed, feed,
                                 issues)
        written = write(cur, result)
        if staged:
            issues.update(fill_context(cur))
        conn.commit()
    for key, n in sorted(result.issues.items()):
        log.warning("conform: %d %s", n, key)
    return written
