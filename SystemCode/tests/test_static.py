"""Static loads (SYSTEM_DESIGN.md §4.1 step 2, spec 004), on fixtures shaped like each source
and placed on optev.sample's car parks. No network. The live test runs only when DATABASE_URL
is in the environment itself, needs migration 004, and rolls back everything it writes."""

import contextlib
import json
import os
import re
from datetime import date

import httpx
import pytest

from optev.contracts import SiteKind
from optev.ingest import cli
from optev.ingest import conform as C
from optev.ingest import static as T
from optev.sample import load

S = load()
CAR_PARKS = S.car_parks[:3]


def _square(lon: float, lat: float, d: float = 0.01) -> dict:
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d],
            [lon - d, lat - d]]
    return {"type": "Polygon", "coordinates": [ring]}


def _point(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def _fc(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def _f(geometry: dict | None, **properties) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


TM = S.car_parks[0].coord
AREAS = _fc(
    _f(_square(TM.lon, TM.lat), PLN_AREA_C="TM", PLN_AREA_N="TAMPINES", REGION_N="EAST REGION"),
    _f(_square(103.95, 1.37), PLN_AREA_C="PR", PLN_AREA_N="PASIR RIS", REGION_N="EAST REGION"),
    _f(_square(103.9, 1.3), PLN_AREA_N="NO CODE"),
)


# Fetching -----------------------------------------------------------------------------


def test_download_retries_until_a_link_and_reuses_todays_file(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "RAW", tmp_path)
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    polls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "poll-download" in request.url.path:
            polls.append(request.url.path)
            if len(polls) == 1:
                return httpx.Response(201, json={"code": 0, "data": None})
            return httpx.Response(201, json={"data": {"url": "https://s3.example/d_x.geojson?sig=1"}})
        return httpx.Response(200, content=b'{"features": []}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = T.download(client, "hawker", date(2026, 10, 17))
        again = T.download(client, "hawker", date(2026, 10, 17))
    assert path == again == tmp_path / "hawker_2026-10-17.geojson"
    assert path.read_bytes() == b'{"features": []}'
    assert len(polls) == 2  # one retry, then the second call reused the file
    assert T.DATASETS["hawker"] in polls[0]


def test_raw_files_land_in_a_gitignored_folder():
    root = T.RAW.parents[1]
    assert (root / "SYSTEM_DESIGN.md").is_file()  # RAW is <repo>/data/raw
    rules = (root / ".gitignore").read_text(encoding="utf-8").split()
    assert "data/raw/" in rules  # anchored at the repo root because it contains a slash


def test_download_gives_up_without_a_link(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "RAW", tmp_path)
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    transport = httpx.MockTransport(lambda r: httpx.Response(429, text="slow down"))
    with httpx.Client(transport=transport) as client, pytest.raises(RuntimeError, match="hawker"):
        T.download(client, "hawker", date(2026, 10, 17))
    assert not list(tmp_path.iterdir())


# Parsing ------------------------------------------------------------------------------


def test_planning_areas_keep_code_name_region_and_polygon():
    rows, skipped = T.parse_planning_areas(AREAS)
    assert [(a.code, a.name, a.region) for a, _ in rows] == [
        ("TM", "TAMPINES", "EAST REGION"), ("PR", "PASIR RIS", "EAST REGION")]
    assert json.loads(rows[0][1])["type"] == "Polygon"
    assert skipped == 1


def test_hdb_car_parks_convert_svy21_and_leave_lots_to_conform():
    xy = C.to_svy21(cp.coord for cp in CAR_PARKS)
    rows = [{"car_park_no": f"T{i}", "address": f"BLK {i} TAMPINES ST 1", "x_coord": str(x),
             "y_coord": str(y), "car_park_type": "MULTI-STOREY CAR PARK"}
            for i, (x, y) in enumerate(xy)]
    rows += [{"car_park_no": "BAD", "address": "", "x_coord": "n/a", "y_coord": "1"},
             {"car_park_no": "SEA", "address": "", "x_coord": "0", "y_coord": "0"},
             dict(rows[0])]  # a duplicate id
    car_parks, skipped = T.parse_hdb_car_parks(rows)
    assert [c.car_park_id for c in car_parks] == ["hdb:T0", "hdb:T1", "hdb:T2"]
    assert all(c.total_lots is None and not c.has_live_feed for c in car_parks)
    for got, want in zip(car_parks, CAR_PARKS, strict=True):
        assert C.metres(got.coord, want.coord) < 1
    assert car_parks[0].name == "BLK 0 TAMPINES ST 1"
    assert skipped == 3


def test_ura_car_parks_keep_only_places_with_car_lots():
    c = CAR_PARKS[0].coord
    fc = _fc(_f(_point(c.lon, c.lat), PP_CODE="AB01", PARKING_PL="Tampines Lane", NO_CAR=42),
             _f(_point(c.lon, c.lat), PP_CODE="MC01", PARKING_PL="Motorcycles only", NO_CAR=0),
             _f(_point(c.lon, c.lat), PP_CODE="AB01", PARKING_PL="Duplicate", NO_CAR=5),
             _f(None, PP_CODE="AB02", NO_CAR=3))
    rows, skipped = T.parse_ura_car_parks(fc)
    assert [(r.car_park_id, r.name, r.total_lots) for r in rows] == [
        ("ura:AB01", "Tampines Lane", 42)]
    assert skipped == 2  # the duplicate and the one without geometry; NO_CAR=0 is filtered


def test_hawkers_keep_every_status_with_section_3_3_ids():
    c = S.sites[-1].coord
    fc = _fc(_f(_point(c.lon, c.lat), OBJECTID=7, NAME="Tampines Round Market ",
                ADDRESS_MYENV="137 Tampines St 11", STATUS="Under Construction"),
             _f(_point(c.lon, c.lat), OBJECTID=8, ADDRESS_MYENV="no name"))
    rows, skipped = T.parse_hawkers(fc)
    assert rows == [T.Amenity("hawker:7", SiteKind.HAWKER_CENTRE, "Tampines Round Market",
                              "137 Tampines St 11", "Under Construction", c)]
    assert skipped == 1


def test_community_clubs_leave_out_passion_wave_outlets():
    c = S.sites[-1].coord
    fc = _fc(_f(_point(c.lon, c.lat), OBJECTID=1, NAME="Tampines West CC", DESCRIPTION="CC",
                ADDRESSBLOCKHOUSENUMBER="5", ADDRESSSTREETNAME="Tampines Ave 3",
                ADDRESSPOSTALCODE="529705"),
             _f(_point(c.lon, c.lat), OBJECTID=2, NAME="PAssion WaVe @ Pasir Ris",
                DESCRIPTION="PAssionWave"))
    rows, skipped = T.parse_community_clubs(fc)
    assert [(r.amenity_id, r.kind, r.address) for r in rows] == [
        ("cc:1", SiteKind.COMMUNITY_FACILITY, "5 Tampines Ave 3, Singapore 529705")]
    assert skipped == 0


def _premise(name: str, company: str, x: float = 16821.7, y: float = 31613.9) -> dict:
    cells = "".join(f"<tr><th>{k}</th> <td>{v}</td></tr>" for k, v in
                    {"X": x, "Y": y, "COMPANY_NAME": company, "ROAD_NAME": "59 Penjuru Road",
                     "BUILDING_NAME": ""}.items())
    lon, lat = 103.7, 1.31
    return _f({"type": "Point", "coordinates": [lon, lat, 0.0]}, Name=name,
              Description=f"<center><table>{cells}</table></center>")


def test_petrol_keeps_only_service_stations_so_the_customs_list_yields_none():
    terminals = _fc(_premise("kml_1", "Vopak Terminals S'pore Pte Ltd"),
                    _premise("kml_2", "Shell Eastern Petroleum Pte Ltd"))
    assert T.parse_petrol(terminals) == ([], 0)
    rows, _ = T.parse_petrol(_fc(_premise("kml_3", "Sample Service Station")))
    assert [(r.amenity_id, r.kind) for r in rows] == [("petrol:kml_3", SiteKind.PETROL_STATION)]


def test_land_use_keeps_id_description_and_polygon_only():
    fc = _fc(_f(_square(TM.lon, TM.lat, 0.001), OBJECTID=692393, LU_DESC="RESIDENTIAL",
                GPR="LND", LU_TEXT=None),
             _f(_square(TM.lon, TM.lat, 0.001), OBJECTID=692394, LU_DESC=None),
             _f(_point(TM.lon, TM.lat), OBJECTID=692395, LU_DESC="ROAD"),
             _f(_square(TM.lon, TM.lat, 0.002), OBJECTID=692393, LU_DESC="PARK"))
    rows, skipped = T.parse_land_use(fc)
    assert [(i, d) for i, d, _ in rows] == [("692393", "RESIDENTIAL")]
    assert json.loads(rows[0][2])["type"] == "Polygon"
    assert skipped == 3


CENSUS = """Number,Total,HDBDwellings_Total,HDBDwellings_1_and2_RoomFlats1
Total,4044210,3152410,177360
Tampines - Total,"274,020",233580,8930
Tampines East,103430,86250,3600
Changi- Total,1850,360,-
Changi Bay - Total,-,-,-
Atlantis - Total,10,10,-
Pasir Ris - Total,147110,n/a,1
"""


def test_residents_use_area_totals_and_match_names_to_codes():
    areas = {"TAMPINES": "TM", "CHANGI": "CH", "CHANGI BAY": "CB", "PASIR RIS": "PR"}
    rows, skipped = T.parse_residents(CENSUS, areas)
    assert rows == [("TM", 274020, 233580), ("CH", 1850, 360), ("CB", 0, 0)]
    assert skipped == 2  # an area with no polygon, and a value that is not a number


# Writing ------------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, sizes: tuple[int, int] = (1, 1)) -> None:
        self.calls: list[tuple[str, object]] = []
        self.copied: list[tuple] = []
        self.rowcount = 0
        self.sizes = sizes

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, seq) -> None:
        seq = list(seq)
        self.calls.append((sql, seq))
        self.rowcount = len(seq)

    def fetchone(self) -> tuple[int, int]:
        return self.sizes

    @contextlib.contextmanager
    def copy(self, sql: str):
        self.calls.append((sql, None))

        class Copy:
            def write_row(_, row: tuple) -> None:
                self.copied.append(row)

        yield Copy()


def _values_are_parameters(sql: str, params: list[tuple]) -> None:
    assert params
    for row in params:
        assert sql.count("%s") == len(row)
        for value in row:
            if isinstance(value, str) and len(value) > 3:
                assert value not in sql


def test_car_park_upsert_keeps_conform_columns_and_skips_unchanged_rows():
    cur = FakeCursor()
    hdb = CAR_PARKS[0].model_copy(update={"car_park_id": "hdb:T0", "total_lots": None})
    assert T.write_car_parks(cur, [hdb]) == 1
    sql, params = cur.calls[0]
    _values_are_parameters(sql, params)
    assert "ON CONFLICT (car_park_id)" in sql and "IS DISTINCT FROM" in sql
    assert "has_live_feed" not in sql and "ever_active" not in sql
    assert "COALESCE(EXCLUDED.total_lots, t.total_lots)" in sql  # HDB's NULL keeps conform's
    assert re.search(r"ST_Contains\(pa\.geom, v\.geom\)", sql)
    assert params[0][0] == "hdb:T0" and params[0][3] is None


def test_area_amenity_and_residents_upserts_use_parameters():
    areas, _ = T.parse_planning_areas(AREAS)
    amenity = T.Amenity("hawker:7", SiteKind.HAWKER_CENTRE, "Market", None, "Existing", TM)
    for write, rows in ((T.write_planning_areas, areas), (T.write_amenities, [amenity]),
                        (T.write_residents, [("TM", 274020, 233580)])):
        cur = FakeCursor()
        assert write(cur, rows) == len(rows)
        sql, params = cur.calls[0]
        _values_are_parameters(sql, params)
        assert "ON CONFLICT" in sql and "IS DISTINCT FROM" in sql
    assert params == [("TM", 274020, 233580, T.RESIDENTS_YEAR)]


def test_land_use_is_copied_simplified_and_size_checked():
    cur = FakeCursor(sizes=(30 * 2**20, 720 * 2**20))
    rows = [("692393", "RESIDENTIAL", json.dumps(_square(TM.lon, TM.lat)))]
    T.write_land_use(cur, rows)
    assert cur.copied == rows
    upsert = next(sql for sql, p in cur.calls if "INSERT INTO stg_land_use" in sql)
    assert "ST_SimplifyPreserveTopology" in upsert and "ON CONFLICT (land_use_id)" in upsert
    assert (upsert, (T.LAND_USE_TOLERANCE_DEG,)) in cur.calls
    assert T.LAND_USE_TOLERANCE_DEG == 0.00001


def test_land_use_above_the_limit_stops_the_load():
    cur = FakeCursor(sizes=(T.LAND_USE_MAX_BYTES + 1, 800 * 2**20))
    with pytest.raises(T.LandUseTooLarge, match="above 60 MB"):
        T.write_land_use(cur, [("1", "ROAD", json.dumps(_square(TM.lon, TM.lat)))])


# Entry points -------------------------------------------------------------------------


def test_load_static_needs_a_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        T.load_static()


def test_cli_load_static(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "MIGRATIONS", tmp_path / "migrations")  # no .env beside it
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["optev-db", "load-static"])
    assert cli.main() == 1
    monkeypatch.setattr("sys.argv", ["optev-db", "load-static", "extra"])
    assert cli.main() == 2
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/x")
    monkeypatch.setattr(T, "load_static", lambda: {"planning_area": 55, "petrol": 0})
    monkeypatch.setattr("sys.argv", ["optev-db", "load-static"])
    assert cli.main() == 0
    assert capsys.readouterr().out.splitlines()[-2:] == ["planning_area: 55", "petrol: 0"]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not in environment")
def test_live_writes_twice_change_nothing_and_roll_back():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('stg_amenity')")
        row = cur.fetchone()
        if row is None or row[0] is None:
            pytest.skip("migration 004 is not applied")
        try:
            areas, _ = T.parse_planning_areas(AREAS)
            areas = [(a.model_copy(update={"code": f"SYN-{a.code}"}), g) for a, g in areas]
            car_parks = [cp.model_copy(update={"car_park_id": f"hdb:{cp.car_park_id}",
                                               "total_lots": None}) for cp in CAR_PARKS]
            assert T.write_planning_areas(cur, areas) == 2
            assert T.write_car_parks(cur, car_parks) == 3
            assert T.write_planning_areas(cur, areas) == 0
            assert T.write_car_parks(cur, car_parks) == 0
            cur.execute("SELECT planning_area FROM car_park WHERE car_park_id = %s",
                        (car_parks[0].car_park_id,))
            assert cur.fetchone() == ("SYN-TM",)
        finally:
            conn.rollback()
