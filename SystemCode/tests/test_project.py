"""Scenarios and projected demand (SYSTEM_DESIGN.md §4.3, #28, spec 026), on optev.sample.
The live test runs only when DATABASE_URL is in the environment and rolls back what it writes."""

import math
import os

import pytest

from optev.assumptions import GROWTH, HORIZON_MONTHS
from optev.contracts import Allocation, EstimateKind, Provenance
from optev.reasoning import allocate as A
from optev.sample import load
from optev.scenario import project as P

S = load()


def test_three_scenarios_from_the_declared_growth():
    scenarios = P.make_scenarios()
    assert [s.scenario_id for s in scenarios] == ["low", "base", "high"]
    assert [s.growth_multiplier for s in scenarios] == [g.value for g in GROWTH.values()]
    assert all(s.horizon_months == HORIZON_MONTHS.value for s in scenarios)
    assert all(s.provenance is Provenance.SIMULATED and s.planned == [] for s in scenarios)
    assert all(s.baseline_window == P.BASELINE_WINDOW for s in scenarios)


def test_they_match_the_samples_scenarios_except_its_window_and_picks():
    ours = {s.scenario_id: s.growth_multiplier for s in P.make_scenarios()}
    assert ours == {s.scenario_id: s.growth_multiplier for s in S.scenarios}


def test_project_scales_every_rate_and_keeps_site_bin_and_kind():
    base = next(s for s in P.make_scenarios() if s.scenario_id == "base")
    out = P.project(S.estimates, base)
    assert len(out) == len(S.estimates)
    for before, after in zip(S.estimates, out, strict=True):
        assert (after.site_id, after.time_bin, after.kind) == (
            before.site_id, before.time_bin, before.kind)
        assert math.isclose(after.arrivals_per_hour, before.arrivals_per_hour * 1.8)
        assert after.note == "simulated: x1.8 (base)"


def test_a_lower_bound_stays_a_lower_bound():
    bounds = [e for e in S.estimates if e.kind is EstimateKind.LOWER_BOUND]
    assert bounds, "the sample has saturated sites"
    for s in P.make_scenarios():
        assert all(e.kind is EstimateKind.LOWER_BOUND for e in P.project(bounds, s))


def test_project_never_changes_the_observed_estimates():
    before = [e.model_copy() for e in S.estimates]
    P.project(S.estimates, P.make_scenarios()[-1])
    assert S.estimates == before


def test_projected_base_demand_is_what_the_allocator_works_from():
    """Issue #28 done-when: a scenario produces demand the allocator can work from. The
    allocator tests scale the estimates by hand; `project` must give the same plan."""
    base = next(s for s in S.scenarios if s.scenario_id == "base")
    by_hand = [e.model_copy(update={"arrivals_per_hour": e.arrivals_per_hour * 1.8})
               for e in S.estimates]
    ours = A.allocate(S.decisions, S.sites, P.project(S.estimates, base), base,
                      requested_connectors=12)
    assert isinstance(ours, Allocation) and ours.total_connectors == 12
    assert ours == A.allocate(S.decisions, S.sites, by_hand, base, requested_connectors=12)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def cursor(self) -> "FakeConnection":
        return self

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        for row in rows:
            assert sql.count("%s") == len(row), sql
        self.calls.append((sql, rows))


def test_write_replaces_each_scenarios_demand_and_counts_rows():
    scenarios = P.make_scenarios()
    demand = {s.scenario_id: P.project(S.estimates, s) for s in scenarios}
    conn = FakeConnection()
    written = P.write_scenarios(conn, scenarios, demand)  # type: ignore[arg-type]
    assert written == {"scenario": 3, "scenario_demand": 3 * len(S.estimates)}
    sqls = [sql for sql, _ in conn.calls]
    assert sqls == [P._UPSERT_SCENARIO] + [P._CLEAR_DEMAND, P._INSERT_DEMAND] * 3
    assert "demand_estimate" not in "".join(sqls)  # the observed table is never written


def test_main_needs_a_database(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(P, "_ENV", tmp_path / ".env")  # no .env there
    assert P.main() == 1
    assert "DATABASE_URL" in capsys.readouterr().out


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not in environment")
def test_live_write_scenarios_and_roll_back():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            site = conn.execute("SELECT site_id FROM candidate_site LIMIT 1").fetchone()
            if site is None:
                pytest.skip("no candidate sites in the database")
            est = S.estimates[0].model_copy(update={"site_id": site[0]})
            scenario = P.make_scenarios()[0].model_copy(update={"scenario_id": "SYN-test"})
            written = P.write_scenarios(conn, [scenario],
                                        {"SYN-test": P.project([est], scenario)})
            assert written == {"scenario": 1, "scenario_demand": 1}
            row = conn.execute("SELECT arrivals_per_hour, kind FROM scenario_demand "
                               "WHERE scenario_id = 'SYN-test'").fetchone()
            assert row is not None
            assert math.isclose(row[0], est.arrivals_per_hour * scenario.growth_multiplier)
            assert row[1] == est.kind.value
        finally:
            conn.rollback()
