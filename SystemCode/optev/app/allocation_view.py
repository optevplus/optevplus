"""What the Allocation page shows (#32). Pure functions, tested without Streamlit.

No business logic: the plan comes from the allocator (#21), its verdict from the independent
checker (#22), room from the allocator's own rule. This module only arranges them and labels
every figure with its layer (app/CLAUDE.md): observed, recommended or declared.
"""

from dataclasses import dataclass
from typing import Any

from optev.app.data import AppData
from optev.assumptions import COST_PER_POINT_SGD, MAX_SHARE_OF_LOTS, MEAN_SESSION_HOURS
from optev.contracts import Allocation, InfeasibilityReport

# What each binding constraint means for a planner (design §4.4, #23).
BINDING = {
    "budget": "The budget pays for fewer points than requested at the cited cost per point.",
    "room": "Eligible sites have room for fewer points: each site may hold charging points on "
            "at most 15% of its car lots, existing ones included.",
    "requested": "The requested number of points cannot be placed exactly.",
}


@dataclass(frozen=True)
class Summary:
    requested: int | None
    placed: int
    sites: int
    cost_sgd: float
    budget_sgd: float | None
    rescued_per_h: float
    checked: bool
    violations: list[str]

    @property
    def verdict(self) -> str:
        if not self.checked:
            return "not checked"
        return "passed" if not self.violations else f"{len(self.violations)} violations"


def summary(plan: Allocation) -> Summary:
    return Summary(
        requested=plan.requested_connectors, placed=plan.total_connectors, sites=len(plan.items),
        cost_sgd=plan.total_cost, budget_sgd=plan.budget,
        rescued_per_h=round(sum(i.marginal_relief or 0.0 for i in plan.items), 3),
        checked=plan.checked, violations=list(plan.violations))


def plan_rows(data: AppData, plan: Allocation) -> list[dict[str, Any]]:
    """One row per site in the plan, most points first. Conditional sites carry the rules they
    must still satisfy, so the planner sees the caveat next to the recommendation."""
    from optev.reasoning.allocate import room  # the allocator's own rule, not re-derived here

    site = {s.site_id: s for s in data.sites}
    decision = {d.site_id: d for d in data.decisions}
    demand = {e.site_id: e for e in data.estimates if e.time_bin == "all"}
    rows = []
    for item in sorted(plan.items, key=lambda i: (-i.connectors, i.site_id)):
        s, d, e = site.get(item.site_id), decision.get(item.site_id), demand.get(item.site_id)
        rows.append({
            "site": item.site_id,
            "area": s.planning_area if s else None,
            "kind": s.kind.value if s else None,
            "outcome": d.outcome.value if d else "unscreened",
            "to confirm first": ", ".join(d.failing_rules) if d and d.failing_rules else "",
            "existing points (observed)": s.existing_connectors if s else None,
            "new points (recommended)": item.connectors,
            "room left after": (room(s.total_lots, s.existing_connectors) - item.connectors)
            if s else None,
            "demand / h (observed)": round(e.arrivals_per_hour, 3) if e else None,
            "demand kind": ("at least" if e.kind.value == "lower_bound" else "point")
            if e else None,
            "drivers rescued / h (recommended)": item.marginal_relief,
            "cost SGD (estimate)": item.cost,
        })
    return rows


def infeasible(report: InfeasibilityReport) -> dict[str, Any]:
    """Why a request cannot be met, in planner terms."""
    reasons = [BINDING.get(c, c) for c in report.binding_constraints]
    if not reasons:
        reasons = ["Both the budget and the room fall short: neither alone would be enough."]
    return {"requested": report.requested_connectors, "max_feasible": report.max_feasible,
            "short_by": report.requested_connectors - report.max_feasible,
            "binding": report.binding_constraints, "reasons": reasons,
            "areas": report.affected_areas}


def assumption_rows() -> list[dict[str, Any]]:
    """The declared values behind every number on the page, with their sources."""
    return [
        {"value": "Cost per charging point", "amount": f"SGD {COST_PER_POINT_SGD.value:,.0f}",
         "source": COST_PER_POINT_SGD.source},
        {"value": "Most points per site", "amount": f"{MAX_SHARE_OF_LOTS.value:.0%} of car lots",
         "source": MAX_SHARE_OF_LOTS.source},
        {"value": "Mean charging session", "amount": f"{MEAN_SESSION_HOURS.value:g} h",
         "source": MEAN_SESSION_HOURS.source},
    ]
