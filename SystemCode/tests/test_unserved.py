"""Demand at sites with no chargers (§4.2 step 4) on optev.sample. The sample has no
`site_context`, so the context here is car park occupancy from `car_park_readings()` and the
distance to the nearest station from coordinates. Scores against `truth()` are recorded in
spec 015, not asserted: the generator gives served and no-charger sites unrelated demand.
The live test runs only when DATABASE_URL is in the environment and is rolled back."""

import math
import os
from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from optev import sample
from optev.analysis import demand as D
from optev.analysis import indicators as I
from optev.analysis import unserved as U
from optev.contracts import CandidateSite, Coordinate, DemandEstimate
from optev.contracts.enums import EstimateKind, SiteKind, SupplyState

START = datetime(2026, 10, 1, tzinfo=I.SGT)
END = START + timedelta(hours=48)
S = sample.load()
READINGS = sample.connector_readings()
INDICATORS = I.compute_indicators(S.sites, S.near, S.connectors, READINGS, START, END)
OCCUPANCY = I.compute_occupancy_by_bin(S.sites, S.near, S.connectors, READINGS, START, END)
STATE = {i.site_id: i.supply_state for i in INDICATORS}
ACTIVE = {s for s, st in STATE.items() if st == SupplyState.SUPPLY_ACTIVE}
NO_SUPPLY = {s for s, st in STATE.items() if st == SupplyState.NO_SUPPLY}
SITES = [s for s in S.sites if s.site_id in ACTIVE | NO_SUPPLY]
OBSERVED = [e for e in D.infer_demand(INDICATORS, OCCUPANCY) if e.site_id in ACTIVE]


def _metres(a: Coordinate, b: Coordinate) -> float:
    dy = (a.lat - b.lat) * 111_320
    dx = (a.lon - b.lon) * 111_320 * math.cos(math.radians(a.lat))
    return math.hypot(dx, dy)


def _context() -> dict[str, dict[str, float]]:
    """What `unserved_context` reads from Postgres, built from the sample's contracts."""
    occ: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in sample.car_park_readings():
        t = r.collected_ts.astimezone(I.SGT)
        if r.total_lots and t.weekday() < 5:
            band = "night" if t.hour <= 5 else "day" if 9 <= t.hour <= 17 else None
            if band:
                occ[r.car_park_id][band].append(1 - r.lots_available / r.total_lots)
    out = {}
    for s in S.sites:
        c = {"nearest_point_m": min(_metres(s.coord, st.coord) for st in S.stations)}
        for band, values in occ.get(s.car_park_id or "", {}).items():
            c[f"cp_occupancy_{band}"] = sum(values) / len(values)
        out[s.site_id] = c
    return out


CONTEXT = _context()
ROWS = U.estimate_unserved(SITES, OBSERVED, CONTEXT)
ALL = {e.site_id: e for e in ROWS if e.time_bin == "all"}


def test_every_no_supply_site_and_only_those_gets_all_and_the_training_bins():
    assert set(ALL) == NO_SUPPLY
    training_bins = {e.time_bin for e in OBSERVED if e.time_bin != "all"}
    for site in NO_SUPPLY:
        bins = {e.time_bin for e in ROWS if e.site_id == site and e.time_bin != "all"}
        assert bins == training_bins
    assert all(e.kind == EstimateKind.POINT and e.arrivals_per_hour >= 0 for e in ROWS)


def test_lower_bounds_and_idle_sites_do_not_train_the_model():
    bound = {e.site_id for e in OBSERVED if e.time_bin == "all"
             and e.kind == EstimateKind.LOWER_BOUND}
    assert bound == {"SYN-S-04"}
    assert "SYN-S-14" not in {s.site_id for s in SITES}
    assert all("9 sites" in e.note for e in ROWS if e.note)


def test_bins_average_back_to_all():
    for site, a in ALL.items():
        bins = {e.time_bin: e.arrivals_per_hour for e in ROWS
                if e.site_id == site and e.time_bin != "all"}
        assert D._all(bins) == pytest.approx(a.arrivals_per_hour)


def test_a_kind_with_no_training_sites_uses_the_overall_profile():
    notes = {e.site_id: e.note or "" for e in ALL.values()}
    assert "profile from 7 hdb_car_park sites" in notes["SYN-S-06"]
    assert "profile from 9 training sites" in notes["SYN-S-27"]  # a hawker centre


def test_the_note_names_the_model_kept_and_its_validation_error():
    note = ALL["SYN-S-06"].note or ""
    assert note.startswith("regression: hgb, 9 sites, leave-area-out MAE ")


def test_runs_are_identical_and_missing_features_do_not_fail():
    assert U.estimate_unserved(SITES, OBSERVED, CONTEXT) == ROWS
    bare = U.estimate_unserved(SITES, OBSERVED, {})
    assert {e.site_id for e in bare if e.time_bin == "all"} == NO_SUPPLY


def test_land_use_and_site_context_keys_are_used():
    context = {k: {**v, "residents_in_area": 1000.0, "amenities_nearby": 1.0,
                   U.LAND_USE + ("RESIDENTIAL" if i % 2 else "COMMERCIAL"): 1.0}
               for i, (k, v) in enumerate(CONTEXT.items())}
    x = U._features(SITES, context)
    assert x.shape == (len(SITES), len(U.NUMERIC) + 1 + len(SiteKind) + 2)
    assert {e.site_id for e in U.estimate_unserved(SITES, OBSERVED, context)
            if e.time_bin == "all"} == NO_SUPPLY


def test_one_training_area_is_an_error_and_nothing_to_predict_is_empty():
    tm = [s for s in SITES if s.planning_area == "TM"]
    with pytest.raises(ValueError, match="two planning areas"):
        U.estimate_unserved(tm, OBSERVED, CONTEXT)
    served = [s for s in SITES if s.site_id in ACTIVE]
    assert U.estimate_unserved(served, OBSERVED, CONTEXT) == []


def test_ties_keep_the_linear_baseline():
    sites = [CandidateSite(site_id=f"x{i}", kind=SiteKind.HDB_CAR_PARK, total_lots=100,
                           coord=Coordinate(lat=1.35, lon=103.9), planning_area=a)
             for i, a in enumerate(["A", "A", "B", "B", "C"])]
    observed = [DemandEstimate(site_id=f"x{i}", time_bin="all", arrivals_per_hour=2.0,
                               kind=EstimateKind.POINT) for i in range(4)]
    (row,) = U.estimate_unserved(sites, observed, {})
    assert row.arrivals_per_hour == pytest.approx(2.0)
    assert (row.note or "").startswith("regression: linear, 4 sites")


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@live
def test_write_unserved_upserts_with_method_regression_and_context_reads():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO candidate_site (site_id, kind, geom) VALUES"
                    " (%s, %s, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326))",
                    [(s.site_id, s.kind.value) for s in S.sites])
            for _ in range(2):
                assert U.write_unserved(conn, ROWS) == len(ROWS)
            got = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE method = 'regression')"
                " FROM demand_estimate WHERE site_id LIKE 'SYN-%%'").fetchone()
            assert got == (len(ROWS), len(ROWS))
            conn.execute(U._CONTEXT_SQL, {"start": START, "end": END}).fetchall()
        finally:
            conn.rollback()
