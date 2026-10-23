"""The whole system, end to end on Postgres (#35, SYSTEM_DESIGN.md §5).

    uv run python -m optev.pipeline run --scenario base --area TM --points 12 [--budget N]

Order: migrations present → conform → indicators + occupancy by bin → demand (queueing) →
patterns → demand at sites with no chargers (regression) → scenarios → rules → allocate →
check → write the plan → coverage report → graph. Each step reads only what earlier steps
wrote and is safe to re-run; `--from STEP` restarts part-way. Every step's own module does the
work; this file only calls them in order and writes the plan, which no stage owns.
"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from optev.contracts import (
    Allocation,
    DemandEstimate,
    EstimateKind,
    InfeasibilityReport,
    Scenario,
    SiteIndicators,
    SupplyState,
)
from optev.graph.schema import allocation_key, infeasibility_key

log = logging.getLogger("optev.pipeline")
_ENV = Path(__file__).resolve().parents[1] / ".env"
BASELINE = "observed"
SQL_SITES = """SELECT site_id, kind, planning_area, car_park_id, total_lots,
    existing_connectors, provenance, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM candidate_site"""
REQUIRED_TABLES = ("candidate_site", "site_indicators", "demand_estimate", "scenario",
                   "scenario_demand", "decision", "allocation", "stg_collect_slot")


@dataclass
class Request:
    scenario_id: str = "base"
    planning_area: str | None = None
    points: int | None = 12
    budget: float | None = None


@dataclass
class Run:
    """What the steps share and report, in order."""

    url: str
    request: Request
    window: tuple[datetime, datetime] | None = None
    occupancy: dict[str, dict[str, float]] = field(default_factory=dict)
    supply: dict[str, SupplyState] = field(default_factory=dict)
    measured: list[SiteIndicators] = field(default_factory=list)
    plan: Allocation | InfeasibilityReport | None = None
    report: dict[str, dict[str, Any]] = field(default_factory=dict)


def _connect(url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(url, connect_timeout=20)


# Steps ------------------------------------------------------------------------------------

def check_migrations(run: Run) -> dict[str, Any]:
    with _connect(run.url) as conn:
        missing = [t for t in REQUIRED_TABLES
                   if conn.execute("SELECT to_regclass(%s)", (t,)).fetchone() == (None,)]
    if missing:
        raise RuntimeError(f"tables missing: {', '.join(missing)}; run `optev-db migrate`")
    return {"tables": len(REQUIRED_TABLES)}


def conform(run: Run) -> dict[str, Any]:
    from optev.ingest.conform import conform as do

    return dict(do())


def indicators(run: Run) -> dict[str, Any]:
    from optev.analysis.indicators import occupancy_by_bin, site_indicators
    from optev.ingest.coverage import collected_window

    with _connect(run.url) as conn:
        run.window = collected_window(conn)
    measured = site_indicators(*run.window)  # also upserts site_indicators
    run.measured = measured
    run.supply = {i.site_id: i.supply_state for i in measured}
    run.occupancy = occupancy_by_bin(*run.window)
    states: dict[str, int] = {}
    for s in run.supply.values():
        states[s.value] = states.get(s.value, 0) + 1
    return {"sites": len(measured), **states}


def demand(run: Run) -> dict[str, Any]:
    from optev.analysis.demand import infer_demand, write_estimates

    estimates = infer_demand(run.measured, run.occupancy)
    with _connect(run.url) as conn:
        n = write_estimates(conn, estimates)
        conn.commit()
    lower = sum(e.kind is EstimateKind.LOWER_BOUND and e.time_bin == "all" for e in estimates)
    return {"rows": n, "sites": len({e.site_id for e in estimates}), "lower_bounds": lower}


def patterns(run: Run) -> dict[str, Any]:
    from optev.analysis.patterns import find_patterns, label_patterns, write_patterns

    found = find_patterns(run.occupancy)
    labels = label_patterns(run.occupancy, found)
    with _connect(run.url) as conn:
        n = write_patterns(conn, found, labels)
        conn.commit()
    return {"sites": n, "clusters": len(labels)}


def unserved(run: Run) -> dict[str, Any]:
    from psycopg.rows import dict_row

    from optev.analysis.unserved import estimate_unserved, unserved_context, write_unserved
    from optev.contracts import CandidateSite
    from optev.graph.read import SQL, models

    assert run.window is not None
    keep = {SupplyState.SUPPLY_ACTIVE, SupplyState.NO_SUPPLY}  # design 1.13
    with _connect(run.url) as conn:
        cur = conn.cursor(row_factory=dict_row)
        sites = [s for s in models(CandidateSite, cur.execute(SQL["sites"]))
                 if run.supply.get(s.site_id) in keep]
        observed = [e for e in models(DemandEstimate, cur.execute(
                        "SELECT site_id, time_bin, arrivals_per_hour, kind, note "
                        "FROM demand_estimate WHERE method = 'queueing'"))
                    if run.supply.get(e.site_id) is SupplyState.SUPPLY_ACTIVE]
    estimates = estimate_unserved(sites, observed, unserved_context(*run.window))
    with _connect(run.url) as conn:
        n = write_unserved(conn, estimates)
        conn.commit()
    return {"rows": n, "sites": len({e.site_id for e in estimates})}


def scenarios(run: Run) -> dict[str, Any]:
    from optev.scenario.project import run as project_all

    with _connect(run.url) as conn:
        written = project_all(conn)
        conn.commit()
    return dict(written)


def rules(run: Run) -> dict[str, Any]:
    from optev.reasoning.rules import screen_all

    return {k.value: v for k, v in screen_all(run.url).items()}


def allocate(run: Run) -> dict[str, Any]:
    from optev.reasoning.allocate import allocate as solve
    from optev.reasoning.checker import check

    req = run.request
    inputs, projected = read_planning_inputs(run.url, req.scenario_id)
    result = solve(inputs["decisions"], inputs["sites"], projected, inputs["scenario"],
                   planning_area=req.planning_area, requested_connectors=req.points,
                   budget=req.budget)
    if isinstance(result, Allocation):
        result = check(result, inputs["decisions"], inputs["sites"])
    run.plan = result
    with _connect(run.url) as conn:
        write_plan(conn, result)
        conn.commit()
    if isinstance(result, Allocation):
        return {"points": result.total_connectors, "sites": len(result.items),
                "cost_sgd": result.total_cost, "checked": result.checked,
                "violations": len(result.violations)}
    return {"infeasible": True, "requested": result.requested_connectors,
            "max_feasible": result.max_feasible, "binding": result.binding_constraints}


def coverage(run: Run) -> dict[str, Any]:
    from optev.ingest.coverage import collected_window, measure, write

    with _connect(run.url) as conn:
        start, end = run.window or collected_window(conn)
        metrics, skipped = measure(conn, start, end)
        write(conn, metrics)
        conn.commit()
    return {**{k: round(v, 4) for k, (v, _) in metrics.items()}, "not_measured": len(skipped)}


def graph(run: Run) -> dict[str, Any]:
    from optev.graph.load import load_all

    counts = load_all(run.url)
    return {"nodes": sum(n for k, n in counts.items() if "->" not in k),
            "relationships": sum(n for k, n in counts.items() if "->" in k)}


STEPS: list[tuple[str, Callable[[Run], dict[str, Any]]]] = [
    ("migrations", check_migrations), ("conform", conform), ("indicators", indicators),
    ("demand", demand), ("patterns", patterns), ("unserved", unserved),
    ("scenarios", scenarios), ("rules", rules), ("allocate", allocate),
    ("coverage", coverage), ("graph", graph),
]
NEEDS_WINDOW = {"demand", "patterns", "unserved"}  # use what `indicators` measured


# The plan, which no stage owns ------------------------------------------------------------

PLANNING_SQL = {
    "sites": SQL_SITES,
    "decisions": "SELECT site_id, scenario_id, outcome FROM decision",
    "results": "SELECT site_id, scenario_id, rule_id, passed, detail FROM rule_result",
    "scenarios": """SELECT scenario_id, seed, growth_multiplier, horizon_months,
        baseline_window, provenance FROM scenario""",
    "planned": "SELECT scenario_id, site_id, connectors, selected_by FROM planned_capacity",
    "observed_demand": """SELECT site_id, time_bin, arrivals_per_hour, kind, note
        FROM demand_estimate""",
    "scenario_demand": """SELECT site_id, time_bin, arrivals_per_hour, kind FROM scenario_demand
        WHERE scenario_id = %s""",
}


def planning_inputs(q: Callable[..., list[dict[str, Any]]], scenario_id: str
                    ) -> tuple[dict[str, Any], list[DemandEstimate]]:
    """Only what the allocator needs, from `q(name, *params) -> rows`: sites, one decision per
    site (the scenario's own, else the observed one), the scenario with its planned picks, and
    its demand (`scenario_demand`, or `demand_estimate` for `observed`)."""
    from optev.contracts import CandidateSite, Decision, PlannedCapacity, RuleResult
    from optev.graph.read import models

    results: dict[tuple[str, str], list[RuleResult]] = {}
    for r in q("results"):
        results.setdefault((r["site_id"], r["scenario_id"]), []).append(
            RuleResult(rule_id=r["rule_id"], passed=r["passed"], detail=r["detail"]))
    chosen: dict[str, dict[str, Any]] = {}
    for d in q("decisions"):
        if d["scenario_id"] == scenario_id or (
                d["scenario_id"] == BASELINE and d["site_id"] not in chosen):
            chosen[d["site_id"]] = d
    decisions = [Decision(site_id=d["site_id"], outcome=d["outcome"],
                          scenario_id=None if d["scenario_id"] == BASELINE else d["scenario_id"],
                          results=results.get((d["site_id"], d["scenario_id"]), []))
                 for d in chosen.values()]
    if scenario_id == BASELINE:
        scenario = Scenario(scenario_id=BASELINE, growth_multiplier=1.0)
        demand = models(DemandEstimate, q("observed_demand"))
    else:
        found = [r for r in q("scenarios") if r["scenario_id"] == scenario_id]
        if not found:
            raise RuntimeError(f"scenario {scenario_id!r} not in Postgres; run the scenarios "
                               "step first")
        planned = [PlannedCapacity(site_id=p["site_id"], connectors=p["connectors"],
                                   selected_by=p["selected_by"])
                   for p in q("planned") if p["scenario_id"] == scenario_id]
        scenario = Scenario(**found[0], planned=planned)
        demand = models(DemandEstimate, q("scenario_demand", scenario_id))
    sites = models(CandidateSite, q("sites"))
    return {"decisions": decisions, "sites": sites, "scenario": scenario}, demand


def read_planning_inputs(url: str, scenario_id: str
                         ) -> tuple[dict[str, Any], list[DemandEstimate]]:
    from psycopg.rows import dict_row

    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        return planning_inputs(
            lambda name, *params: list(cur.execute(PLANNING_SQL[name], params or None)),
            scenario_id)


def write_plan(conn: psycopg.Connection[Any], plan: Allocation | InfeasibilityReport) -> str:
    """Upsert the plan (or the report) under its §3.3 id; a re-run of the same request
    replaces it. Returns the id."""
    with conn.cursor() as cur:
        if isinstance(plan, InfeasibilityReport):
            rid = infeasibility_key(plan.scenario_id, plan.planning_area,
                                    plan.requested_connectors)
            cur.execute("DELETE FROM infeasibility WHERE report_id = %s", (rid,))
            cur.execute(
                "INSERT INTO infeasibility (report_id, scenario_id, planning_area, "
                "requested_connectors, max_feasible, binding_constraints, affected_areas) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (rid, plan.scenario_id, plan.planning_area, plan.requested_connectors,
                 plan.max_feasible, plan.binding_constraints, plan.affected_areas))
            return rid
        aid = allocation_key(plan.scenario_id, plan.planning_area, plan.requested_connectors,
                             plan.budget)
        cur.execute("DELETE FROM allocation WHERE allocation_id = %s", (aid,))  # items cascade
        cur.execute(
            "INSERT INTO allocation (allocation_id, scenario_id, planning_area, "
            "requested_connectors, budget, checked, violations) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (aid, plan.scenario_id, plan.planning_area, plan.requested_connectors,
             plan.budget, plan.checked, plan.violations))
        cur.executemany(
            "INSERT INTO allocation_item (allocation_id, site_id, connectors, cost, "
            "marginal_relief) VALUES (%s, %s, %s, %s, %s)",
            [(aid, i.site_id, i.connectors, i.cost, i.marginal_relief) for i in plan.items])
        return aid


# Running ----------------------------------------------------------------------------------

def run(url: str, request: Request, start_at: str = "migrations",
        only: list[str] | None = None) -> Run:
    """Run the steps in order from `start_at` (or exactly `only`). Stops at the first error."""
    names = [n for n, _ in STEPS]
    if start_at not in names:
        raise ValueError(f"unknown step {start_at!r}; one of {names}")
    unknown = [n for n in only or [] if n not in names]
    if unknown:
        raise ValueError(f"unknown step(s) {unknown}; one of {names}")
    if only and start_at != names[0]:
        raise ValueError("use --from or --only, not both")
    chosen = only or names[names.index(start_at):]
    if set(chosen) & NEEDS_WINDOW and "indicators" not in chosen:
        chosen = ["indicators", *chosen]  # they need this run's measurements
    state = Run(url, request)
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # the steps' own modules read it
    try:
        for name, step in STEPS:
            if name not in chosen:
                continue
            t0 = time.perf_counter()
            log.info("step %s …", name)
            state.report[name] = {**step(state), "seconds": round(time.perf_counter() - t0, 1)}
            log.info("step %s done: %s", name, state.report[name])
    finally:  # never leak the URL into later tests or the app process
        if before is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = before
    return state


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(prog="python -m optev.pipeline")
    parser.add_argument("command", choices=["run", "steps"])
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--area", default=None, help="planning-area code; omit = island-wide")
    parser.add_argument("--points", type=int, default=None)
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--from", dest="start_at", default="migrations")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)
    if args.command == "steps":
        print(" → ".join(n for n, _ in STEPS))
        return 0
    if args.points is None and args.budget is None:
        args.points = 12
    load_dotenv(_ENV)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.",
              file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    state = run(url, Request(args.scenario, args.area, args.points, args.budget),
                args.start_at, args.only)
    for name, result in state.report.items():
        print(f"{name:11s} {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
