"""Planned capacity stays out of the observed layer (#29). Unit tests need no database; the
live ones run only when DATABASE_URL is in the environment itself
(`uv run --env-file .env pytest`) and roll back everything they write."""

import os

import pytest

from optev.contracts import CandidateSite, Coordinate, PlannedCapacity, SiteKind
from optev.sample import load
from optev.scenario import planned

S = load()


def _site(site_id: str, existing: int) -> CandidateSite:
    return CandidateSite(site_id=site_id, kind=SiteKind.HDB_CAR_PARK,
                         coord=Coordinate(lat=1.35, lon=103.9), existing_connectors=existing)


def test_effective_connectors_add_only_this_scenarios_picks():
    sites = [_site("A", 2), _site("B", 0), _site("C", 5)]
    picks = [PlannedCapacity(site_id="A", connectors=3), PlannedCapacity(site_id="B", connectors=1)]
    assert planned.combine(sites, picks) == {"A": 5, "B": 1, "C": 5}
    assert planned.combine(sites, []) == {"A": 2, "B": 0, "C": 5}


def test_a_pick_for_a_site_outside_the_list_is_ignored():
    assert planned.combine([_site("A", 2)], [PlannedCapacity(site_id="Z", connectors=4)]) == {
        "A": 2}


def test_the_samples_planned_pick_lands_on_its_scenario_only():
    base = next(sc for sc in S.scenarios if sc.planned)
    others = [sc for sc in S.scenarios if not sc.planned]
    pick = base.planned[0]
    with_pick = planned.combine(S.sites, base.planned)
    without = planned.combine(S.sites, others[0].planned)
    existing = {s.site_id: s.existing_connectors for s in S.sites}
    assert with_pick[pick.site_id] == existing[pick.site_id] + pick.connectors
    assert without == existing
    assert {k: v for k, v in with_pick.items() if k != pick.site_id} == {
        k: v for k, v in existing.items() if k != pick.site_id}


def test_a_pick_must_add_at_least_one_point():
    with pytest.raises(ValueError):
        PlannedCapacity(site_id="A", connectors=0)


# Live ---------------------------------------------------------------------------------

live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")

OBSERVED = (
    "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {table} t"
)
COUNTED = "SELECT count(*), coalesce(max(id), 0) FROM {table}"  # 3.8M rows: no full hash


def _observed_state(conn) -> tuple:
    hashed = tuple(conn.execute(OBSERVED.format(table=t)).fetchone()[0]
                   for t in ("candidate_site", "station", "connector"))
    counted = tuple(conn.execute(COUNTED.format(table=t)).fetchone()
                    for t in ("car_park_reading", "connector_reading"))
    return hashed + counted


@pytest.fixture
def conn():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute(
            "INSERT INTO candidate_site (site_id, kind, existing_connectors, geom) VALUES"
            " ('SYN-T-01', 'hdb_car_park', 2, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326)),"
            " ('SYN-T-02', 'hdb_car_park', 0, ST_SetSRID(ST_MakePoint(103.91, 1.36), 4326))"
        )
        c.execute("INSERT INTO scenario (scenario_id, growth_multiplier, horizon_months)"
                  " VALUES ('syn-test', 1.8, 51)")
        try:
            yield c
        finally:
            c.rollback()


@live
def test_select_then_clear_leaves_observed_data_unchanged(conn):
    before = _observed_state(conn)
    planned._select_site(conn, "syn-test", "SYN-T-01", 3, "pytest")
    planned._select_site(conn, "syn-test", "SYN-T-01", 4, "pytest")  # replaces, never adds
    assert [(p.site_id, p.connectors) for p in planned._planned(conn, "syn-test")] == [
        ("SYN-T-01", 4)]
    assert _observed_state(conn) == before  # the pick never touched the observed layer
    assert planned._clear_selection(conn, "syn-test", "SYN-T-01") == 1
    assert planned._planned(conn, "syn-test") == []
    assert _observed_state(conn) == before


@live
def test_picks_count_only_in_their_own_scenario(conn):
    planned._select_site(conn, "syn-test", "SYN-T-02", 2, "pytest")
    sites = [_site("SYN-T-01", 2), _site("SYN-T-02", 0)]
    assert planned.combine(sites, planned._planned(conn, "syn-test")) == {
        "SYN-T-01": 2, "SYN-T-02": 2}
    assert planned.combine(sites, planned._planned(conn, planned.BASELINE)) == {
        "SYN-T-01": 2, "SYN-T-02": 0}


@live
def test_unknown_scenario_or_site_is_refused(conn):
    with pytest.raises(ValueError, match="unknown scenario"):
        planned._select_site(conn, "no-such-scenario", "SYN-T-01", 1, "pytest")
    with pytest.raises(ValueError, match="unknown site"):
        planned._select_site(conn, "syn-test", "SYN-NOPE", 1, "pytest")
    planned._select_site(conn, planned.BASELINE, "SYN-T-01", 1, "pytest")  # baseline is fine
