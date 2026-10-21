"""What the Evidence page shows (#34). Pure functions, so they are tested without Streamlit.

Every section carries its layer, because the planner must never mistake a recommendation or
a projection for something that was measured (invariant 1, app/CLAUDE.md):

    observed     measured from a government feed (indicators)
    inferred     computed from observed data under a declared assumption (demand estimates)
    rule         a decision rule and the source it cites
    declared     a value we chose and state openly (assumptions)
    recommended  the optimiser's plan for a scenario
    planned      a planner's own selection
"""

from dataclasses import dataclass, field
from typing import Any

# The questions a planner can pick without typing, with the parameters each needs.
QUESTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "why_site": ("Why was this site chosen?", ("site_id",)),
    "why_not_site": ("Why was this site rejected, deferred or conditional?", ("site_id",)),
    "demand_basis": ("Where does this site's demand number come from?", ("site_id",)),
    "assumptions_used": ("Which assumptions sit behind this site?", ("site_id",)),
    "compare_sites": ("Compare two sites", ("site_a", "site_b")),
    "rule_sources": ("Where does a rule come from?", ("rule_id",)),
    "infeasible_request": ("Why can't a request be met?", ("scenario_id", "planning_area")),
    "area_saturation": ("Which areas are near saturation?", ()),
}

EXAMPLES = (
    "Why was SYN-S-13 rejected?",
    "Where does the demand estimate for SYN-S-04 come from?",
    "Compare SYN-S-04 and SYN-S-13.",
    "Why was SYN-S-99 rejected?",
)

LAYER_HELP = {
    "observed": "Measured from a government feed.",
    "inferred": "Computed from observed data under a declared assumption.",
    "rule": "A decision rule and the source it cites.",
    "declared": "A value we chose and state openly.",
    "recommended": "The optimiser's plan for a scenario. Not built.",
    "planned": "A planner's own selection. Not built.",
}


@dataclass
class Section:
    title: str
    layer: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


def _rule_rows(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "rule": r.get("rule_id"), "result": r.get("verdict"), "detail": r.get("detail"),
        "if it fails": r.get("on_fail"), "source type": r.get("source_class"),
        "source": r.get("evidence") or r.get("evidence_id"), "link": r.get("url"),
        "condition": r.get("condition"),
    } for r in rules]


def _demand_rows(demand: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "estimate": d.get("estimate_id"), "arrivals per hour": d.get("arrivals_per_hour"),
        "kind": "at least (lower bound)" if d.get("kind") == "lower_bound" else d.get("kind"),
        "based on": ", ".join(d.get("based_on") or []) or "no chargers here: comparable sites",
        "assumes": ", ".join(f"{a['assumption_id']} = {a['value']} {a['unit']}"
                             for a in d.get("assumptions") or []),
    } for d in demand]


def sections(question_type: str | None, rows: list[dict[str, Any]]) -> list[Section]:
    """Turn retrieved rows into labelled sections. Nothing is computed, only arranged."""
    out: list[Section] = []
    for row in rows:
        site = row.get("site_id")
        if site and question_type not in ("assumptions_used",):
            facts: dict[str, Any] = {k: row.get(k) for k in
                     ("site_id", "kind", "planning_area", "total_lots", "existing_connectors",
                      "outcome") if k in row}
            out.append(Section(f"Site {site}", "observed", [facts],
                               "Outcome comes from the rules below."))
        checked = "Rules not passed" if question_type == "why_not_site" else "Rules checked"
        for key, title in (("rules", checked), ("rules_not_passed", "Rules not passed")):
            if row.get(key) is not None:
                note = "" if row[key] else "No rule failed or went unchecked."
                out.append(Section(f"{title} · {site}" if site else title, "rule",
                                   _rule_rows(row[key]), note))
        if row.get("indicators"):
            out.append(Section("Measured indicators", "observed", row["indicators"]))
        if row.get("demand"):
            out.append(Section("Demand estimate", "inferred", _demand_rows(row["demand"]),
                               "A lower bound means demand is at least this: chargers were "
                               "full too often to see the true figure."))
        if row.get("allocated"):
            out.append(Section("In the optimiser's plan", "recommended", row["allocated"]))
        if row.get("planned"):
            out.append(Section("Picked by a planner", "planned", row["planned"]))
        if row.get("assumptions"):
            out.append(Section("Assumptions used", "declared", row["assumptions"]))
    if question_type == "rule_sources":
        out = [Section("Rule and its source", "rule", rows)]
    elif question_type == "infeasible_request":
        out = [Section("Unmet request", "recommended", rows,
                       "Binding = removing that limit alone would make the request possible.")]
    elif question_type == "area_saturation":
        out = [Section("Planning areas by saturation", "observed",
                       [{k: v for k, v in r.items() if k != "indicator_ids"} for r in rows],
                       "Share of half-hours when every charger at a site was in use.")]
    return out
