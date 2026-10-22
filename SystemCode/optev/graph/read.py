"""Read Postgres into the bundle the graph loader takes (design §4.5, `load_all`).

`load()` was built on `optev.sample.Sample`; this fills the same fields from the pipeline's
tables, with every allocation and infeasibility report instead of the sample's one each.
Postgres stays the source of truth: the graph is rebuilt from it after each pipeline run.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from optev.contracts import (
    Allocation,
    AllocationItem,
    CandidateSite,
    CarPark,
    Connector,
    Decision,
    DemandEstimate,
    InfeasibilityReport,
    Outcome,
    PlannedCapacity,
    PlanningArea,
    Rule,
    RuleResult,
    Scenario,
    SiteIndicators,
    Station,
)

BASELINE = "observed"

SQL = {
    "areas": "SELECT code, name, region FROM planning_area",
    "car_parks": """SELECT car_park_id, name, ST_Y(geom) AS lat, ST_X(geom) AS lon,
        planning_area, total_lots, car_park_type, has_live_feed FROM car_park""",
    "stations": """SELECT station_id, operator, address, provenance, planning_area,
        ST_Y(geom) AS lat, ST_X(geom) AS lon FROM station""",
    "connectors": """SELECT connector_id, station_id, plug_type, power_kw::float AS power_kw,
        ever_active FROM connector""",
    "sites": """SELECT site_id, kind, planning_area, car_park_id, total_lots,
        existing_connectors, provenance, ST_Y(geom) AS lat, ST_X(geom) AS lon
        FROM candidate_site""",
    "near": "SELECT station_id, site_id, distance_m, threshold_m FROM station_site",
    "indicators": """SELECT DISTINCT ON (site_id) site_id, window_start, window_end,
        supply_state, active_connectors, utilisation, saturated_fraction, dwell_opportunity,
        observation_coverage FROM site_indicators ORDER BY site_id, window_end DESC""",
    "estimates": """SELECT site_id, time_bin, arrivals_per_hour, kind, note
        FROM demand_estimate WHERE time_bin = 'all'""",
    "rules": """SELECT rule_id, condition, source, source_ref, required_facts,
        explanation_template, on_fail FROM rule""",
    "decisions": "SELECT site_id, scenario_id, outcome FROM decision",
    "results": """SELECT site_id, scenario_id, rule_id, passed, detail FROM rule_result
        ORDER BY rule_id""",
    "scenarios": """SELECT scenario_id, seed, growth_multiplier, horizon_months,
        baseline_window, provenance FROM scenario""",
    "planned": "SELECT scenario_id, site_id, connectors, selected_by FROM planned_capacity",
    "allocations": """SELECT allocation_id, scenario_id, planning_area, requested_connectors,
        budget, checked, violations FROM allocation""",
    "items": """SELECT allocation_id, site_id, connectors, cost, marginal_relief
        FROM allocation_item""",
    "reports": """SELECT scenario_id, planning_area, requested_connectors, max_feasible,
        binding_constraints, affected_areas FROM infeasibility""",
}


@dataclass
class GraphBundle:
    """The fields `load()` reads, filled from Postgres."""

    planning_areas: list[PlanningArea]
    car_parks: list[CarPark]
    stations: list[Station]
    connectors: list[Connector]
    sites: list[CandidateSite]
    near: list[dict[str, Any]]
    indicators: list[SiteIndicators]
    estimates: list[DemandEstimate]
    rules: list[Rule]
    rule_on_fail: dict[str, Outcome]
    decisions: list[Decision]
    scenarios: list[Scenario]
    allocations: list[Allocation] = field(default_factory=list)
    infeasibilities: list[InfeasibilityReport] = field(default_factory=list)
    references: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def models[M: BaseModel](model: type[M], rows: Iterable[Mapping[str, Any]]) -> list[M]:
    """Contracts from rows: lat/lon nested as `coord`, timestamps as ISO text."""
    out = []
    for row in rows:
        data = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        if "lat" in row:
            data["coord"] = {"lat": row["lat"], "lon": row["lon"]}
        for k, v in list(data.items()):
            if isinstance(v, datetime):
                data[k] = v.isoformat()
        out.append(model.model_validate(data))
    return out


def bundle(q: Any) -> GraphBundle:
    """Build the bundle from `q(name) -> list[dict]`, one call per entry in SQL. Takes a query
    function rather than a connection, so tests can pass canned rows."""
    from optev.sample import load as sample

    results: dict[tuple[str, str], list[RuleResult]] = {}
    for r in q("results"):
        results.setdefault((r["site_id"], r["scenario_id"]), []).append(
            RuleResult(rule_id=r["rule_id"], passed=r["passed"], detail=r["detail"]))
    decisions = [Decision(site_id=d["site_id"], outcome=d["outcome"],
                          scenario_id=None if d["scenario_id"] == BASELINE else d["scenario_id"],
                          results=results.get((d["site_id"], d["scenario_id"]), []))
                 for d in q("decisions")]
    rule_rows = q("rules")
    on_fail = {r["rule_id"]: Outcome(r["on_fail"]) for r in rule_rows}
    rules = models(Rule, [{k: v for k, v in r.items() if k != "on_fail"} for r in rule_rows])
    planned: dict[str, list[PlannedCapacity]] = {}
    for p in q("planned"):
        planned.setdefault(p["scenario_id"], []).append(PlannedCapacity(
            site_id=p["site_id"], connectors=p["connectors"], selected_by=p["selected_by"]))
    scenarios = [Scenario(**row, planned=planned.get(row["scenario_id"], []))
                 for row in q("scenarios")]
    items: dict[str, list[AllocationItem]] = {}
    for it in q("items"):
        items.setdefault(it["allocation_id"], []).append(AllocationItem(
            **{k: v for k, v in it.items() if k != "allocation_id"}))
    allocations = [Allocation(**{k: v for k, v in h.items() if k != "allocation_id"},
                              items=items.get(h["allocation_id"], []))
                   for h in q("allocations")]
    return GraphBundle(
        planning_areas=models(PlanningArea, q("areas")),
        car_parks=models(CarPark, q("car_parks")),
        stations=models(Station, q("stations")),
        connectors=models(Connector, q("connectors")),
        sites=models(CandidateSite, q("sites")),
        near=[dict(n) for n in q("near")],
        indicators=models(SiteIndicators, q("indicators")),
        estimates=models(DemandEstimate, q("estimates")),
        rules=rules, rule_on_fail=on_fail, decisions=decisions, scenarios=scenarios,
        allocations=allocations, infeasibilities=models(InfeasibilityReport, q("reports")),
        # No reference table: titles and links of the cited sources live with the sample.
        references=sample().references,
    )


def read_bundle(database_url: str) -> GraphBundle:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
        return bundle(lambda name: list(cur.execute(SQL[name])))
