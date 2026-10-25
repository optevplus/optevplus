"""What the Rules page shows (#31). Pure functions over `AppData`, tested without Streamlit.

The page explains each decision from the screen alone (WBS 6.4a): every rule result, the source
class and document behind it, and whether waiving one failed rule would change the outcome. The
outcome itself always comes from the rules engine (`rules.outcome`), never recomputed here.
"""

from typing import Any

from optev.app.data import AppData
from optev.contracts import Decision, Outcome, Rule
from optev.reasoning.rules import outcome

SOURCE_CLASS = {
    "gov_dataset": "Government dataset",
    "gov_policy": "Government policy",
    "math_constraint": "Arithmetic limit",
    "project_assumption": "Our declared assumption",
}
VERDICT = {True: "passed", False: "failed", None: "unevaluated (missing data)"}
# what a planner acts on first: sites ruled out, then those needing a check, then data gaps
OUTCOME_ORDER = [Outcome.REJECT, Outcome.CONDITIONAL, Outcome.DEFER, Outcome.ACCEPT]


def _source(data: AppData, rule: Rule) -> dict[str, Any]:
    ref = data.references.get(rule.source_ref or "", {})
    return {
        "source type": SOURCE_CLASS.get(rule.source.value, rule.source.value),
        "source": ref.get("title") or ref.get("name") or rule.source_ref,
        "link": ref.get("url"),
    }


def register_rows(data: AppData) -> list[dict[str, Any]]:
    """The register as the planner sees it: what each rule checks and where it comes from."""
    return [{
        "rule": r.rule_id,
        "condition": r.condition,
        "if it fails": data.on_fail[r.rule_id].value,
        "reads": ", ".join(r.required_facts),
        **_source(data, r),
    } for r in data.rules]


def decision_table(data: AppData, outcome_filter: str | None = None,
                   planning_area: str | None = None) -> list[dict[str, Any]]:
    """One row per screened site: outcome, failed rules, rules that could not be evaluated.
    Car parks come first, then by outcome (reject, conditional, defer, accept), then by place
    name, so the table opens on the decisions a planner acts on."""
    sites = {s.site_id: s for s in data.sites}

    def order(d: Decision) -> tuple[bool, int, str, str]:
        site = sites.get(d.site_id)
        car_park = site is not None and site.kind.value.endswith("car_park")
        name = data.site_names.get(d.site_id) or d.site_id
        return (not car_park, OUTCOME_ORDER.index(d.outcome), name.lower(), d.site_id)

    rows = []
    for d in sorted(data.decisions, key=order):
        site = sites.get(d.site_id)
        if outcome_filter and d.outcome.value != outcome_filter:
            continue
        if planning_area and (site is None or site.planning_area != planning_area):
            continue
        rows.append({
            "site_id": d.site_id,
            "kind": site.kind.value if site else None,
            "planning_area": site.planning_area if site else None,
            "outcome": d.outcome.value,
            "failed": ", ".join(d.failing_rules),
            "unevaluated": ", ".join(d.unevaluated_rules),
        })
    return rows


def rule_results(data: AppData, decision: Decision) -> list[dict[str, Any]]:
    """Every rule the engine evaluated for one site, in register order, with its source."""
    by_id = {r.rule_id: r for r in data.rules}
    rows = []
    for res in decision.results:
        rule = by_id.get(res.rule_id)
        rows.append({
            "rule": res.rule_id,
            "result": VERDICT[res.passed],
            "detail": res.detail,
            "condition": rule.condition if rule else None,
            "if it fails": data.on_fail[res.rule_id].value if res.rule_id in data.on_fail
            else None,
            **(_source(data, rule) if rule else {}),
        })
    return rows


def waivers(data: AppData, decision: Decision) -> dict[str, Outcome]:
    """For each failed rule: the outcome if that rule alone were waived (treated as passed).
    Shows whether a single exception would change the result (WBS 3.2)."""
    out = {}
    for rule_id in decision.failing_rules:
        waived = [r.model_copy(update={"passed": True}) if r.rule_id == rule_id else r
                  for r in decision.results]
        out[rule_id] = outcome(waived, data.on_fail)
    return out
