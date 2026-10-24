"""The only module in the app that reads data (SYSTEM_DESIGN.md §4.6): Postgres when
DATABASE_URL is set, otherwise `optev.sample`, so every page works before the database is ready.

Pages get one `AppData` bundle of contracts and never query anything themselves. Decisions on
the sample come from the rules engine run over the sample, so the screen always reflects the
current register; in Postgres they are the `decision` / `rule_result` rows the pipeline wrote.
"""

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import BaseModel, ValidationError

from optev.assumptions import SNAPSHOT_MINUTES
from optev.contracts import (
    Allocation,
    AllocationItem,
    CandidateSite,
    CarPark,
    Decision,
    DemandEstimate,
    Outcome,
    PlannedCapacity,
    PlanningArea,
    Rule,
    RuleResult,
    Scenario,
    SiteIndicators,
)
from optev.reasoning.rules import load_register, screen

log = logging.getLogger(__name__)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
OBSERVED = "observed"  # §3.2: baseline decisions belong to no scenario


@dataclass
class AppData:
    source: str  # "sample" or "postgres": shown on every page
    planning_areas: list[PlanningArea]
    sites: list[CandidateSite]
    car_parks: list[CarPark]
    indicators: list[SiteIndicators]
    estimates: list[DemandEstimate]  # the `all` bin: one arrivals rate per site
    decisions: list[Decision]  # baseline (observed) decisions
    rules: list[Rule]
    on_fail: dict[str, Outcome]
    scenarios: list[Scenario]
    allocations: list[Allocation] = field(default_factory=list)
    references: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Datasets, documents and assumptions by id (`ds-`, `doc-`, `asm-`), for rule sources."""
    profiles: list[DemandEstimate] = field(default_factory=list)
    """The hourly bins (`wd-`, `we-`) behind `estimates`, for the Demand page."""
    patterns: dict[str, int] = field(default_factory=dict)  # site_id -> cluster
    pattern_labels: dict[int, str] = field(default_factory=dict)  # cluster -> label

    def site(self, site_id: str) -> CandidateSite | None:
        return next((s for s in self.sites if s.site_id == site_id), None)


def _references(raw: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    out = {}
    for refs in raw.values():
        for ref in refs:
            key = ref.get("dataset_id") or ref.get("doc_id") or ref.get("assumption_id")
            if key:
                out[key] = ref
    return out


def _sample_bins(s: Any) -> tuple[list[DemandEstimate], dict[str, int], dict[int, str]]:
    """Hourly demand and patterns for the sample, which stores only `all` rows: the analysis
    package run over the sample's readings, over the readings' own window."""
    from optev.analysis.demand import infer_demand
    from optev.analysis.indicators import (
        compute_indicators,
        compute_occupancy_by_bin,
        snapshot_slot,
    )
    from optev.analysis.patterns import find_patterns, label_patterns
    from optev.sample import connector_readings

    readings = connector_readings()
    seen = [r.collected_ts for r in readings]
    start = snapshot_slot(min(seen))
    end = snapshot_slot(max(seen)) + timedelta(minutes=SNAPSHOT_MINUTES)
    args = (s.sites, s.near, s.connectors, readings, start, end)
    occupancy = compute_occupancy_by_bin(*args)
    bins = [e for e in infer_demand(compute_indicators(*args), occupancy) if e.time_bin != "all"]
    patterns = find_patterns(occupancy)
    return bins, patterns, label_patterns(occupancy, patterns)


def from_sample() -> AppData:
    from optev.sample import load

    s = load()
    rules, on_fail = load_register()
    decisions, _ = screen(s.sites, s.car_parks, s.indicators, {}, rules, on_fail)
    profiles, patterns, labels = _sample_bins(s)
    return AppData("sample", s.planning_areas, s.sites, s.car_parks, s.indicators,
                   [e for e in s.estimates if e.time_bin == "all"], decisions, rules, on_fail,
                   s.scenarios, [s.allocation], _references(s.references),
                   profiles, patterns, labels)


# Postgres ---------------------------------------------------------------------------------

SQL = {
    "areas": "SELECT code, name, region FROM planning_area ORDER BY code",
    "sites": """SELECT site_id, kind, planning_area, car_park_id, total_lots, existing_connectors,
        provenance, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM candidate_site""",
    "car_parks": """SELECT car_park_id, name, ST_Y(geom) AS lat, ST_X(geom) AS lon,
        planning_area, total_lots, car_park_type, has_live_feed FROM car_park""",
    "indicators": """SELECT DISTINCT ON (site_id) site_id, window_start, window_end,
        supply_state, active_connectors, utilisation, saturated_fraction, dwell_opportunity,
        observation_coverage FROM site_indicators ORDER BY site_id, window_end DESC""",
    "estimates": """SELECT site_id, time_bin, arrivals_per_hour, kind, note
        FROM demand_estimate WHERE time_bin = 'all'""",
    "profiles": """SELECT site_id, time_bin, arrivals_per_hour, kind, note
        FROM demand_estimate WHERE time_bin <> 'all' ORDER BY site_id, time_bin""",
    "patterns": "SELECT site_id, cluster, label FROM site_pattern ORDER BY site_id",
    "decisions": "SELECT site_id, outcome FROM decision WHERE scenario_id = %s",
    "results": """SELECT site_id, rule_id, passed, detail FROM rule_result
        WHERE scenario_id = %s ORDER BY site_id, rule_id""",
    "scenarios": """SELECT scenario_id, seed, growth_multiplier, horizon_months,
        baseline_window, provenance FROM scenario ORDER BY scenario_id""",
    "planned": """SELECT scenario_id, site_id, connectors, selected_by FROM planned_capacity
        ORDER BY selected_at""",
    "allocations": """SELECT allocation_id, scenario_id, planning_area, requested_connectors,
        budget, checked, violations FROM allocation ORDER BY created_at DESC LIMIT 20""",
    "items": """SELECT allocation_id, site_id, connectors, cost, marginal_relief
        FROM allocation_item WHERE allocation_id = ANY(%s)""",
}


def _models[M: BaseModel](model: type[M], rows: Iterable[Mapping[str, Any]]) -> list[M]:
    """Contracts from rows: coordinates nested, timestamps as ISO text. Bad rows are logged."""
    out = []
    for row in rows:
        data = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        if "lat" in row:
            data["coord"] = {"lat": row["lat"], "lon": row["lon"]}
        for k, v in list(data.items()):
            if isinstance(v, datetime):
                data[k] = v.isoformat()
        try:
            out.append(model.model_validate(data))
        except ValidationError as e:
            log.warning("skipped %s row: %s", model.__name__, e.errors()[0]["msg"])
    return out


def from_postgres(url: str) -> AppData:
    import psycopg
    from psycopg.rows import dict_row

    from optev.sample import load as load_sample

    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        def q(name: str, *params: Any) -> list[dict[str, Any]]:
            return list(cur.execute(SQL[name], params or None))

        results: dict[str, list[RuleResult]] = {}
        for r in q("results", OBSERVED):
            results.setdefault(r["site_id"], []).append(RuleResult.model_validate(
                {k: r[k] for k in ("rule_id", "passed", "detail")}))
        decisions = [Decision(site_id=d["site_id"], outcome=d["outcome"],
                              results=results.get(d["site_id"], []))
                     for d in q("decisions", OBSERVED)]
        planned: dict[str, list[PlannedCapacity]] = {}
        for p in q("planned"):
            planned.setdefault(p.pop("scenario_id"), []).append(PlannedCapacity(**p))
        scenarios = [Scenario(**row, planned=planned.get(row["scenario_id"], []))
                     for row in q("scenarios")]
        heads = q("allocations")
        items: dict[str, list[AllocationItem]] = {}
        for it in q("items", [h["allocation_id"] for h in heads]):
            items.setdefault(it.pop("allocation_id"), []).append(AllocationItem(**it))
        allocations = [Allocation(**{k: v for k, v in h.items() if k != "allocation_id"},
                                  items=items.get(h["allocation_id"], [])) for h in heads]
        rules, on_fail = load_register()
        patterns = q("patterns")
        return AppData(
            "postgres", _models(PlanningArea, q("areas")), _models(CandidateSite, q("sites")),
            _models(CarPark, q("car_parks")), _models(SiteIndicators, q("indicators")),
            _models(DemandEstimate, q("estimates")), decisions, rules, on_fail, scenarios,
            allocations,
            # no reference table yet; source metadata (titles, links) lives with the sample
            _references(load_sample().references),
            _models(DemandEstimate, q("profiles")),
            {p["site_id"]: p["cluster"] for p in patterns},
            {p["cluster"]: p["label"] for p in patterns if p["label"]})


@st.cache_resource(ttl=300, show_spinner="Loading sites, decisions and demand…")
def shared() -> AppData:
    """`load()` once for every page and visitor. `st.cache_data` gave each page view its own
    unpickled copy (about 300 MB of demand rows on the real data), which ran the 1 GB
    Community Cloud container out of memory (#5). Pages only read it; `shared.clear()` after a
    planner selection makes the next run reload."""
    return load()


def load() -> AppData:
    """Postgres when DATABASE_URL is set (environment or SystemCode/.env), else the sample."""
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)  # never overrides a variable already set
    url = os.environ.get("DATABASE_URL")
    return from_postgres(url) if url else from_sample()
