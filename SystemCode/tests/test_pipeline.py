"""The end-to-end pipeline (#35) and the Postgres → graph reader (load_all). Unit tests use
canned rows and fake connections; the live run needs a database (see test bottom)."""

import os
from typing import Any

import pytest

from optev import pipeline as P
from optev.contracts import Allocation, AllocationItem, InfeasibilityReport
from optev.graph import load as L
from optev.graph.read import SQL, bundle
from optev.graph.schema import allocation_key, infeasibility_key
from optev.sample import load as sample

S = sample()


def _rows_from_sample() -> dict[str, list[dict[str, Any]]]:
    """The sample, shaped as the Postgres rows graph.read expects."""
    def flat(m: Any) -> dict[str, Any]:
        d = m.model_dump(mode="json")
        if "coord" in d:
            d.update(d.pop("coord"))
        return d

    return {
        "areas": [flat(a) for a in S.planning_areas],
        "car_parks": [flat(c) for c in S.car_parks],
        "stations": [flat(s) for s in S.stations],
        "connectors": [flat(c) for c in S.connectors],
        "sites": [flat(s) for s in S.sites],
        "near": [dict(n) for n in S.near],
        "indicators": [flat(i) for i in S.indicators],
        "estimates": [flat(e) for e in S.estimates],
        "rules": [{**flat(r), "on_fail": S.rule_on_fail[r.rule_id].value} for r in S.rules],
        "decisions": [{"site_id": d.site_id, "scenario_id": d.scenario_id or "observed",
                       "outcome": d.outcome.value} for d in S.decisions],
        "results": [{"site_id": d.site_id, "scenario_id": d.scenario_id or "observed",
                     **r.model_dump(mode="json")} for d in S.decisions for r in d.results],
        "scenarios": [{k: v for k, v in flat(s).items() if k != "planned"} for s in S.scenarios],
        "planned": [{"scenario_id": s.scenario_id, **p.model_dump(mode="json")}
                    for s in S.scenarios for p in s.planned],
        "allocations": [{"allocation_id": "a1", **{k: v for k, v in flat(S.allocation).items()
                                                  if k != "items"}}],
        "items": [{"allocation_id": "a1", **i.model_dump(mode="json")}
                  for i in S.allocation.items],
        "reports": [flat(S.infeasibility)],
    }


def test_every_query_has_a_matching_bundle_field():
    rows = _rows_from_sample()
    assert set(SQL) == set(rows)
    data = bundle(lambda name: rows[name])
    assert len(data.sites) == len(S.sites) and len(data.decisions) == len(S.decisions)
    assert data.allocations[0].items == S.allocation.items
    assert data.infeasibilities[0] == S.infeasibility
    assert {s.scenario_id: s.planned for s in data.scenarios} == {
        s.scenario_id: s.planned for s in S.scenarios}


def test_the_graph_loader_takes_the_postgres_bundle_with_many_plans():
    rows = _rows_from_sample()
    data = bundle(lambda name: rows[name])
    second = data.allocations[0].model_copy(update={"planning_area": "TM"})
    data.allocations.append(second)
    batches = {b.name: b for b in L.rows(data)}  # type: ignore[arg-type]
    keys = {r["key"] for r in batches["Allocation"].rows}
    assert len(keys) == 2
    assert batches["Decision"].rows and batches["Infeasibility"].rows


def test_no_plan_at_all_loads_nothing_for_allocations():
    rows = {**_rows_from_sample(), "allocations": [], "items": [], "reports": []}
    batches = {b.name for b in L.rows(bundle(lambda name: rows[name]))}  # type: ignore[arg-type]
    assert "Allocation" not in batches and "Infeasibility" not in batches


class _Cur:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self) -> "_Cur":
        return self

    def __exit__(self, *a: Any) -> None:
        pass

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, rows: Any) -> None:
        self.calls.append((sql, list(rows)))


class _Conn:
    def __init__(self) -> None:
        self.cur = _Cur()

    def cursor(self) -> _Cur:
        return self.cur


def test_a_plan_is_written_under_its_design_id_and_replaces_the_last():
    plan = Allocation(scenario_id="base", planning_area="TM", requested_connectors=2,
                      items=[AllocationItem(site_id="S1", connectors=2, cost=18500.0)])
    conn = _Conn()
    aid = P.write_plan(conn, plan)  # type: ignore[arg-type]
    assert aid == allocation_key("base", "TM", 2, None)
    sqls = [c[0] for c in conn.cur.calls]
    assert sqls[0].startswith("DELETE FROM allocation") and "INSERT INTO allocation_item" in sqls[2]


def test_an_impossible_request_is_written_as_a_report():
    report = InfeasibilityReport(scenario_id="base", planning_area="PR", requested_connectors=40,
                                 max_feasible=32, binding_constraints=["budget"])
    conn = _Conn()
    assert P.write_plan(conn, report) == infeasibility_key("base", "PR", 40)  # type: ignore[arg-type]
    assert "INSERT INTO infeasibility" in conn.cur.calls[1][0]


def test_steps_follow_the_design_order_and_restart_part_way():
    names = [n for n, _ in P.STEPS]
    assert names == ["migrations", "conform", "indicators", "demand", "patterns", "unserved",
                     "scenarios", "rules", "allocate", "coverage", "graph"]
    ran: list[str] = []
    def recorder(name: str) -> Any:
        def step(run: Any) -> dict[str, Any]:
            ran.append(name)
            return {}
        return step

    fake = [(n, recorder(n)) for n in names]
    import optev.pipeline as mod

    original = mod.STEPS
    mod.STEPS = fake  # type: ignore[assignment]
    try:
        P.run("postgresql://unused", P.Request(), start_at="rules")
        assert ran == ["rules", "allocate", "coverage", "graph"]
        ran.clear()
        P.run("postgresql://unused", P.Request(), only=["demand"])
        assert ran == ["indicators", "demand"]  # demand needs this run's measurements
    finally:
        mod.STEPS = original
    with pytest.raises(ValueError, match="unknown step"):
        P.run("postgresql://unused", P.Request(), start_at="nope")


@pytest.mark.skipif(not os.environ.get("OPTEV_PIPELINE_DB"),
                    reason="set OPTEV_PIPELINE_DB to a scratch database to run end to end")
def test_the_whole_pipeline_runs_on_a_database():
    state = P.run(os.environ["OPTEV_PIPELINE_DB"], P.Request("base", None, 12, None),
                  only=["migrations", "allocate"])
    assert state.plan is not None
