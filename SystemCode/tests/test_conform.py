"""Stage 1 conform (SYSTEM_DESIGN.md §4.1 step 3), run on optev.sample."""

import math
import os

import pytest

from optev.contracts import CandidateSite, CarPark, Coordinate, SiteKind, Station
from optev.ingest import cli
from optev.ingest import conform as C
from optev.sample import car_park_readings, connector_readings, load

S = load()
SAMPLE_SITE = {s.car_park_id: s for s in S.sites if s.car_park_id}


def _prefixed(car_park_id: str) -> str:
    # §3.3 ids carry their source; the sample's don't, so give them one by sample kind
    kind = SAMPLE_SITE[car_park_id].kind
    return f"{'hdb' if kind is SiteKind.HDB_CAR_PARK else 'ura'}:{car_park_id}"


CAR_PARKS = [cp.model_copy(update={"car_park_id": _prefixed(cp.car_park_id)}) for cp in S.car_parks]
AMENITIES = [s for s in S.sites if s.car_park_id is None]
CONNECTORS = [c.model_copy(update={"ever_active": False}) for c in S.connectors]
OBSERVED = C.observed_connectors(connector_readings())
# latest lot count per car park, as conform() reads it from car_park_reading
FEED = {_prefixed(r.car_park_id): r.total_lots
        for r in sorted(car_park_readings(), key=lambda r: r.collected_ts)}
# sample site id for each conformed site id
TO_SAMPLE = {_prefixed(k): v.site_id for k, v in SAMPLE_SITE.items()} | {
    a.site_id: a.site_id for a in AMENITIES
}


def _run(**overrides):
    args = dict(car_parks=CAR_PARKS, amenities=AMENITIES, stations=S.stations,
                connectors=CONNECTORS, observed=OBSERVED, feed=FEED)
    return C.conform_records(**(args | overrides))


def _haversine(a: Coordinate, b: Coordinate) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.lon - a.lon) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


# Projection ---------------------------------------------------------------------------

def test_svy21_origin_maps_to_its_published_wgs84_point():
    c = C.svy21_to_wgs84(28_001.642, 38_744.572)
    assert c is not None
    assert c.lat == pytest.approx(1.366667, abs=1e-5)
    assert c.lon == pytest.approx(103.833333, abs=1e-5)


def test_svy21_round_trip_is_within_a_metre():
    for site in S.sites:
        (x, y), = C.to_svy21([site.coord])
        back = C.svy21_to_wgs84(x, y)
        assert back is not None and C.metres(site.coord, back) < 1


def test_svy21_outside_singapore_or_nan_gives_none():
    assert C.svy21_to_wgs84(0, 0) is None
    assert C.svy21_to_wgs84(float("nan"), 30_000) is None


def test_metres_agrees_with_great_circle_distance():
    a, b = S.sites[0].coord, S.sites[-1].coord
    # haversine assumes a sphere, which is ~0.5% off the ellipsoid at Singapore's latitude
    assert C.metres(a, b) == pytest.approx(_haversine(a, b), rel=1e-2)


# Connectors ---------------------------------------------------------------------------

def test_ever_active_from_readings_matches_the_sample():
    out = C.mark_ever_active(CONNECTORS, OBSERVED)
    assert [c.connector_id for c in out if not c.ever_active] == ["SYN-ST-02-9"]
    assert {c.connector_id: c.ever_active for c in out} == {
        c.connector_id: c.ever_active for c in S.connectors
    }


def test_ever_active_never_flips_back():
    out = C.mark_ever_active(S.connectors, {})
    assert [c.ever_active for c in out] == [c.ever_active for c in S.connectors]


# Registry <-> live feed ----------------------------------------------------------------

def test_every_sample_car_park_matches_the_feed():
    out = _run()
    assert all(cp.has_live_feed for cp in out.car_parks)
    assert "registry_without_feed" not in out.issues
    assert "feed_without_registry" not in out.issues


def test_unmatched_car_parks_are_counted_both_ways():
    no_feed = CAR_PARKS[0].car_park_id
    feed = {k: v for k, v in FEED.items() if k != no_feed} | {"hdb:ZZ99": 80, "hdb:ZZ98": None}
    out = _run(feed=feed)
    assert [cp.car_park_id for cp in out.car_parks if not cp.has_live_feed] == [no_feed]
    assert out.issues == {"registry_without_feed": 1, "feed_without_registry": 2}
    # still a candidate site: no feed is reported, never a reason to drop it
    assert no_feed in {s.site_id for s in out.sites}


def test_lot_counts_come_from_the_feed():
    # the HDB registry has no lot counts; the availability feed is their only source
    blank = [cp.model_copy(update={"total_lots": None}) for cp in CAR_PARKS]
    out = _run(car_parks=blank)
    assert {cp.car_park_id: cp.total_lots for cp in out.car_parks} == {
        cp.car_park_id: cp.total_lots for cp in CAR_PARKS
    }
    assert all(s.total_lots is not None for s in out.sites if s.car_park_id)
    # a feed row with no lot count leaves the registry value alone
    out = _run(feed=dict.fromkeys(FEED))
    assert [cp.total_lots for cp in out.car_parks] == [cp.total_lots for cp in CAR_PARKS]


# Every collected row resolves to an id and a coordinate (WBS 1.4 done-when) -------------

def test_every_sample_reading_resolves_to_a_coordinate():
    out = _run()
    assert not {k for k in out.issues if "without" in k}
    # car park readings -> car park; connector readings -> connector -> station
    car_parks = {cp.car_park_id: cp.coord for cp in out.car_parks}
    assert all(cp_id in car_parks for cp_id in FEED)
    stations = {s.station_id: s.coord for s in S.stations}
    by_id = {c.connector_id: c.station_id for c in out.connectors}
    assert all(by_id[cid] in stations for cid in OBSERVED)


def test_observed_connectors_include_never_active_ones():
    assert len(OBSERVED) == len(S.connectors) == 46
    assert [k for k, active in OBSERVED.items() if not active] == ["SYN-ST-02-9"]


def test_broken_reading_chains_are_counted_not_dropped():
    lost = S.connectors[0].model_copy(update={"connector_id": "SYN-NO-READINGS"})
    stray = S.connectors[1].model_copy(update={"connector_id": "SYN-NO-STATION",
                                               "station_id": "SYN-ST-GONE"})
    observed = OBSERVED | {"SYN-NOT-REGISTERED": True, "SYN-NO-STATION": True}
    out = _run(connectors=[*CONNECTORS, lost, stray], observed=observed)
    assert out.issues == {"reading_without_connector": 1, "connector_without_reading": 1,
                          "connector_without_station": 1}
    assert "SYN-NO-READINGS" in {c.connector_id for c in out.connectors}


# Sites --------------------------------------------------------------------------------

def test_sites_reproduce_the_sample():
    out = _run()
    assert len(out.sites) == len(S.sites) == 30
    sample = {s.site_id: s for s in S.sites}
    for site in out.sites:
        want = sample[TO_SAMPLE[site.site_id]]
        assert (site.kind, site.coord, site.planning_area, site.total_lots,
                site.existing_connectors) == (want.kind, want.coord, want.planning_area,
                                              want.total_lots, want.existing_connectors)
    assert {s.site_id for s in out.sites if s.car_park_id} == {cp.car_park_id for cp in CAR_PARKS}


def test_car_park_site_id_and_kind_follow_the_source_prefix():
    cp = CAR_PARKS[0]
    for prefix, kind in (("hdb", SiteKind.HDB_CAR_PARK), ("ura", SiteKind.PUBLIC_CAR_PARK),
                         ("mall", SiteKind.PUBLIC_CAR_PARK)):
        site = C.car_park_site(cp.model_copy(update={"car_park_id": f"{prefix}:X1"}))
        assert site is not None and (site.site_id, site.kind) == (f"{prefix}:X1", kind)
    assert C.car_park_site(cp.model_copy(update={"car_park_id": "X1"})) is None
    assert C.car_park_site(cp.model_copy(update={"car_park_id": "foo:X1"})) is None


def test_sample_amenities_are_far_from_car_parks_so_stay_sites():
    out = _run()
    assert {a.site_id for a in AMENITIES} <= {s.site_id for s in out.sites}
    assert sum(out.amenities_nearby.values()) == 0


def test_amenity_near_a_car_park_links_instead_of_becoming_a_site():
    cp = CAR_PARKS[3]
    near = AMENITIES[0].model_copy(update={"coord": cp.coord})
    out = _run(amenities=[near, *AMENITIES[1:]])
    assert near.site_id not in {s.site_id for s in out.sites}
    assert out.amenities_nearby[cp.car_park_id] == 1
    assert len(out.sites) == 29


# station_site -------------------------------------------------------------------------

def test_station_site_keeps_every_pair_within_200m_at_the_smallest_threshold():
    pairs = {(p["station_id"], TO_SAMPLE[p["site_id"]]): p["threshold_m"]
             for p in _run().station_site}
    sample = {(n["station_id"], n["site_id"]): n["threshold_m"] for n in S.near}
    assert sample.items() <= pairs.items()
    # the design keeps every pair; the sample lists only each station's own car park
    assert {k: v for k, v in pairs.items() if k not in sample} == {
        ("SYN-ST-05", "SYN-S-07"): 200,
        ("SYN-ST-09", "SYN-S-30"): 200,
        ("SYN-ST-11", "SYN-S-26"): 100,
    }


def test_station_connectors_count_at_the_nearest_site_only():
    out = _run()
    by_sample = {TO_SAMPLE[s.site_id]: s.existing_connectors for s in out.sites}
    assert by_sample["SYN-S-05"] == 6 and by_sample["SYN-S-07"] == 0
    assert sum(by_sample.values()) == sum(c.ever_active for c in S.connectors)


def test_nearest_point_is_distance_to_closest_active_station():
    out = _run()
    by_sample = {TO_SAMPLE[k]: v for k, v in out.nearest_point_m.items()}
    assert by_sample["SYN-S-01"] == 0.0
    assert by_sample["SYN-S-26"] == pytest.approx(57, abs=1)
    assert C.nearest_point_m(S.sites[:2], S.stations, []) == {
        S.sites[0].site_id: None, S.sites[1].site_id: None
    }


# Defensive parsing and reruns ---------------------------------------------------------

def test_bad_rows_are_counted_not_raised():
    issues: dict[str, int] = {}
    good = CAR_PARKS[0].model_dump(mode="json")
    rows = [good, {**good, "coord": {"lat": 0, "lon": 0}}, {**good, "total_lots": -1}, {}]
    assert len(C.parse_rows(CarPark, rows, issues, "car_park")) == 1
    assert issues == {"bad_car_park": 3}


def test_unknown_sources_duplicates_and_unlinked_stations_are_counted():
    far = Station(station_id="SYN-ST-FAR", coord=Coordinate(lat=1.29, lon=103.85))
    odd = CandidateSite(site_id="x:1", kind=SiteKind.HDB_CAR_PARK, coord=far.coord)
    out = _run(car_parks=[*CAR_PARKS, CAR_PARKS[0], S.car_parks[0]],
               amenities=[*AMENITIES, odd], stations=[*S.stations, far])
    assert out.issues == {"duplicate_car_park": 1, "registry_without_feed": 1,
                          "unknown_source_car_park": 1, "unknown_kind_amenity": 1,
                          "station_unlinked": 1}
    assert len(out.sites) == 30


def test_rerun_gives_identical_output():
    assert _run() == _run()


# Database writes ----------------------------------------------------------------------

class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        for row in rows:
            assert sql.count("%s") == len(row), sql
        self.calls.append((sql, rows))


def test_write_binds_parameters_and_reports_rows_per_table():
    out = _run()
    cur = FakeCursor()
    written = C.write(cur, out)
    assert written == {"car_park": 26, "connector": 45, "candidate_site": 30, "station_site": 14,
                       "site_context": 30}
    assert [sql for sql, _ in cur.calls] == [
        C.MARK_FEED, C.SET_LOTS, C.MARK_ACTIVE, C.UPSERT_SITE, C.FILL_PLANNING_AREA,
        C.CLEAR_STATION_SITE, C.INSERT_STATION_SITE, C.UPSERT_CONTEXT,
    ]
    assert all("{" not in sql for sql, _ in cur.calls)


def test_with_coord_nests_lat_and_lon():
    row = {"car_park_id": "hdb:A1", "lat": 1.35, "lon": 103.9}
    assert C._with_coord(row) == {"car_park_id": "hdb:A1", "coord": {"lat": 1.35, "lon": 103.9}}


def test_cli_conform_needs_a_database(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "MIGRATIONS", tmp_path / "migrations")  # no .env beside it
    monkeypatch.setattr("sys.argv", ["optev-db", "conform"])
    assert cli.main() == 1
    monkeypatch.setattr("sys.argv", ["optev-db", "conform", "extra"])
    assert cli.main() == 2


# Static loads in conform (#11, spec 024) ------------------------------------------------

def _stg_amenity_rows() -> list[dict[str, object]]:
    """The sample's amenities shaped as `READ_AMENITIES` returns `stg_amenity` rows."""
    return [{"site_id": a.site_id, "kind": a.kind.value, "lat": a.coord.lat, "lon": a.coord.lon}
            for a in AMENITIES]


def test_staged_amenities_become_sites_or_link_to_a_car_park():
    issues: dict[str, int] = {}
    bad = {"site_id": "cc:9", "kind": "cc", "lat": 1.3, "lon": 103.8}  # not a SiteKind
    amenities = C.amenity_sites([*_stg_amenity_rows(), bad], issues)
    assert issues == {"bad_amenity": 1}
    assert [a.site_id for a in amenities] == [a.site_id for a in AMENITIES]
    def key(out):  # planning area comes later, from the polygons in the database
        return [(x.site_id, x.kind, x.coord) for x in out.sites]
    assert key(_run(amenities=amenities)) == key(_run())  # all > 150 m: standalone sites


class CountingCursor(FakeCursor):
    def __init__(self, counts: dict[str, int]) -> None:
        super().__init__()
        self.counts = counts

    def execute(self, sql: str, params: object = None) -> "CountingCursor":
        super().execute(sql, params)
        return self

    def fetchone(self) -> dict[str, int]:
        return self.counts


def test_fill_context_runs_the_polygon_fills_and_reports_unplaced_sites():
    cur = CountingCursor({"site_without_planning_area": 2, "site_without_land_use": 0})
    assert C.fill_context(cur) == {"site_without_planning_area": 2}
    assert [sql for sql, _ in cur.calls] == [C.FILL_LAND_USE, C.FILL_RESIDENTS, C.COUNT_UNPLACED]
    assert C.fill_context(CountingCursor({"site_without_planning_area": 0,
                                          "site_without_land_use": 0})) == {}


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not in environment")
def test_live_fill_context_sets_land_use_and_residents_and_rolls_back():
    import psycopg
    from psycopg.rows import dict_row

    square = ("SRID=4326;MULTIPOLYGON(((103.0 1.0, 103.1 1.0, 103.1 1.1, 103.0 1.1, "
              "103.0 1.0)))")
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        if not cur.execute(C.HAS_STAGING).fetchone()["staged"]:  # type: ignore[index]
            pytest.skip("migration 004 is not applied")
        try:
            cur.execute("INSERT INTO planning_area (code, name, region, geom) VALUES "
                        "('SYN-A', 'SYN AREA', 'SYN', ST_GeomFromEWKT(%s))", (square,))
            cur.execute("INSERT INTO stg_land_use (land_use_id, lu_desc, geom) VALUES "
                        "('SYN-2', 'COMMERCIAL', ST_GeomFromEWKT(%s)),"
                        "('SYN-1', 'RESIDENTIAL', ST_GeomFromEWKT(%s))", (square, square))
            cur.execute("INSERT INTO stg_residents (planning_area, residents, source_year) "
                        "VALUES ('SYN-A', 1234, 2020)")
            for site_id, lon in (("SYN-IN", 103.05), ("SYN-OUT", 103.5)):
                cur.execute("INSERT INTO candidate_site (site_id, kind, provenance, geom) "
                            "VALUES (%s, 'hawker_centre', 'observed', "
                            "ST_SetSRID(ST_MakePoint(%s, 1.05), 4326))", (site_id, lon))
                cur.execute("INSERT INTO site_context (site_id) VALUES (%s)", (site_id,))
            cur.execute(C.FILL_PLANNING_AREA)
            missing = C.fill_context(cur)
            rows = {r["site_id"]: r for r in cur.execute(
                "SELECT s.site_id, s.planning_area, sc.land_use, sc.residents_in_area "
                "FROM candidate_site s JOIN site_context sc USING (site_id) "
                "WHERE s.site_id LIKE 'SYN-%'")}
            assert rows["SYN-IN"] == {"site_id": "SYN-IN", "planning_area": "SYN-A",
                                      "land_use": "RESIDENTIAL", "residents_in_area": 1234}
            assert rows["SYN-OUT"]["planning_area"] is None
            assert rows["SYN-OUT"]["land_use"] is None
            assert missing["site_without_planning_area"] >= 1
        finally:
            conn.rollback()
