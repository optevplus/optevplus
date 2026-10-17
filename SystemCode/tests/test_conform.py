"""Stage 1 conform (SYSTEM_DESIGN.md §4.1 step 3), run on optev.sample."""

import math

import pytest

from optev.contracts import CandidateSite, CarPark, Coordinate, SiteKind, Station
from optev.ingest import cli
from optev.ingest import conform as C
from optev.sample import connector_readings, load

S = load()
SAMPLE_SITE = {s.car_park_id: s for s in S.sites if s.car_park_id}


def _prefixed(car_park_id: str) -> str:
    # §3.3 ids carry their source; the sample's don't, so give them one by sample kind
    kind = SAMPLE_SITE[car_park_id].kind
    return f"{'hdb' if kind is SiteKind.HDB_CAR_PARK else 'ura'}:{car_park_id}"


CAR_PARKS = [cp.model_copy(update={"car_park_id": _prefixed(cp.car_park_id)}) for cp in S.car_parks]
AMENITIES = [s for s in S.sites if s.car_park_id is None]
CONNECTORS = [c.model_copy(update={"ever_active": False}) for c in S.connectors]
ACTIVE = C.seen_active(connector_readings())
# sample site id for each conformed site id
TO_SAMPLE = {_prefixed(k): v.site_id for k, v in SAMPLE_SITE.items()} | {
    a.site_id: a.site_id for a in AMENITIES
}


def _run(**overrides):
    args = dict(car_parks=CAR_PARKS, amenities=AMENITIES, stations=S.stations,
                connectors=CONNECTORS, active_ids=ACTIVE)
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
    out = C.mark_ever_active(CONNECTORS, ACTIVE)
    assert [c.connector_id for c in out if not c.ever_active] == ["SYN-ST-02-9"]
    assert {c.connector_id: c.ever_active for c in out} == {
        c.connector_id: c.ever_active for c in S.connectors
    }


def test_ever_active_never_flips_back():
    out = C.mark_ever_active(S.connectors, set())
    assert [c.ever_active for c in out] == [c.ever_active for c in S.connectors]


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
    assert out.issues == {"duplicate_car_park": 1, "unknown_source_car_park": 1,
                          "unknown_kind_amenity": 1, "station_unlinked": 1}
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
    assert written == {"connector": 45, "candidate_site": 30, "station_site": 14,
                       "site_context": 30}
    assert [sql for sql, _ in cur.calls] == [
        C.MARK_ACTIVE, C.UPSERT_SITE, C.FILL_PLANNING_AREA, C.CLEAR_STATION_SITE,
        C.INSERT_STATION_SITE, C.UPSERT_CONTEXT,
    ]
    assert all("{" not in sql for sql, _ in cur.calls)


def test_with_coord_nests_lat_and_lon():
    row = {"car_park_id": "hdb:A1", "lat": 1.35, "lon": 103.9}
    assert C._with_coord(row) == {"car_park_id": "hdb:A1", "coord": {"lat": 1.35, "lon": 103.9}}


def test_cli_rejects_unknown_verbs_and_needs_a_database(monkeypatch):
    monkeypatch.setattr("sys.argv", ["optev-db"])
    assert cli.main() == 2
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["optev-db", "conform"])
    assert cli.main() == 1
