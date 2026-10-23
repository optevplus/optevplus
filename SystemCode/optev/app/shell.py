"""What the Map page shows (#30). Pure functions over `AppData`, tested without Streamlit.

No business logic: outcomes come from the rules engine, points from the allocator, demand from
the analysis package. This module only joins them per site and labels every figure with its
layer (app/CLAUDE.md): observed, inferred, recommended or planned.
"""

from dataclasses import dataclass
from typing import Any

import h3

from optev.app.data import AppData
from optev.contracts import Allocation, InfeasibilityReport, Outcome

OUTCOME_COLOURS: dict[str, list[int]] = {  # RGBA for pydeck
    Outcome.ACCEPT.value: [26, 150, 65, 210],
    Outcome.CONDITIONAL.value: [240, 160, 0, 210],
    Outcome.DEFER.value: [140, 140, 140, 180],
    Outcome.REJECT.value: [215, 48, 39, 200],
    "unscreened": [90, 90, 200, 160],
}
ELIGIBLE = (Outcome.ACCEPT.value, Outcome.CONDITIONAL.value)
HEX_RESOLUTION = 8  # ~0.7 km² cells: a few car parks each


@dataclass(frozen=True)
class Request:
    scenario_id: str
    planning_area: str | None = None
    points: int | None = None
    budget: float | None = None


def stored_plan(data: AppData, request: Request) -> Allocation | None:
    """The most recent stored allocation for exactly this request, if there is one."""
    for a in data.allocations:
        if (a.scenario_id, a.planning_area, a.requested_connectors, a.budget) == (
                request.scenario_id, request.planning_area, request.points, request.budget):
            return a
    return None


def plan(data: AppData, request: Request) -> tuple[Allocation | InfeasibilityReport | None, str]:
    """The allocation for the request and where it came from. Calls the allocator (#21) when
    it is installed; otherwise falls back to a stored plan for the same request."""
    if request.points is None and request.budget is None:
        return None, "Give a number of points, a budget, or both."
    try:
        from optev.reasoning.allocate import allocate  # type: ignore[import-not-found]
    except ImportError:
        found = stored_plan(data, request)
        if found:
            return found, "stored plan (allocator not installed)"
        return None, "The allocator (#21) is not installed and no stored plan matches."
    from optev.scenario.project import project

    scenario = next(s for s in data.scenarios if s.scenario_id == request.scenario_id)
    # Plan for the scenario's demand (§4.3): observed rates × its growth, lower bounds kept.
    result = allocate(data.decisions, data.sites, project(data.estimates, scenario), scenario,
                      planning_area=request.planning_area,
                      requested_connectors=request.points, budget=request.budget)
    return result, "allocator (CP-SAT)"


def site_rows(data: AppData, allocation: Allocation | None,
              planning_area: str | None = None) -> list[dict[str, Any]]:
    """One row per site for the map and the ranking, every figure named with its layer."""
    outcome = {d.site_id: d for d in data.decisions}
    points = {i.site_id: i.connectors for i in allocation.items} if allocation else {}
    demand = {e.site_id: e for e in data.estimates}
    use = {i.site_id: i.utilisation for i in data.indicators}
    rows = []
    for s in data.sites:
        if planning_area and s.planning_area != planning_area:
            continue
        d, e = outcome.get(s.site_id), demand.get(s.site_id)
        verdict = d.outcome.value if d else "unscreened"
        new = points.get(s.site_id, 0)
        rows.append({
            "site_id": s.site_id,
            "kind": s.kind.value,
            "planning_area": s.planning_area,
            "lat": s.coord.lat,
            "lon": s.coord.lon,
            "outcome": verdict,
            "failing_rules": ", ".join(d.failing_rules) if d else "",
            "existing_points (observed)": s.existing_connectors,
            "utilisation (observed)": use.get(s.site_id),
            "demand_per_h (inferred)": round(e.arrivals_per_hour, 2) if e else None,
            "lower_bound": bool(e and e.kind.value == "lower_bound"),
            "new_points (recommended)": new,
            "colour": OUTCOME_COLOURS[verdict],
            "radius": 120 + 90 * new,
        })
    return rows


def ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Eligible sites first; within them, most recommended points, then most demand."""
    def key(r: dict[str, Any]) -> tuple[int, int, float, str]:
        return (r["outcome"] not in ELIGIBLE, -r["new_points (recommended)"],
                -(r["demand_per_h (inferred)"] or 0.0), r["site_id"])
    ranked = sorted(rows, key=key)
    return [{"rank": i, **r} for i, r in enumerate(ranked, start=1)]


def demand_hexes(rows: list[dict[str, Any]],
                 resolution: int = HEX_RESOLUTION) -> list[dict[str, Any]]:
    """Inferred demand summed per H3 cell. Sites without an estimate add nothing."""
    cells: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["demand_per_h (inferred)"] is None:
            continue
        cell = h3.latlng_to_cell(r["lat"], r["lon"], resolution)
        c = cells.setdefault(cell, {"hex": cell, "demand_per_h": 0.0, "sites": 0})
        c["demand_per_h"] += r["demand_per_h (inferred)"]
        c["sites"] += 1
    peak = max((c["demand_per_h"] for c in cells.values()), default=0.0) or 1.0
    for c in cells.values():
        c["demand_per_h"] = round(c["demand_per_h"], 2)
        c["shade"] = [0, 92, 175, int(40 + 140 * c["demand_per_h"] / peak)]
    return sorted(cells.values(), key=lambda c: c["hex"])


def funnel(data: AppData, site_ids: set[str] | None = None) -> dict[str, int]:
    """Sites per outcome (all four always present), optionally for some sites only."""
    out = {o.value: 0 for o in Outcome}
    for d in data.decisions:
        if site_ids is None or d.site_id in site_ids:
            out[d.outcome.value] += 1
    return out
