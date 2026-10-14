"""Rule register and engine (SYSTEM_DESIGN.md §4.4, #17-#18).

The register (`register.toml`) says what each rule is, where it comes from and what a
failure means; the checks below say how each is tested, reading every threshold from
`optev.assumptions`. Every rule is evaluated, never only up to the first failure, and a
missing fact gives `passed = None`, so a data gap defers and never rejects.
"""

import math
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from optev.assumptions import IDLE_BELOW, MAX_SHARE_OF_LOTS
from optev.contracts import (
    CandidateSite,
    CarPark,
    Decision,
    Outcome,
    Rule,
    RuleResult,
    SiteIndicators,
    SiteKind,
    SupplyState,
)

REGISTER = Path(__file__).parent / "register.toml"

# The facts rules may read (§4.4). A missing value is absent, never 0.
FACTS = ("kind", "planning_area", "total_lots", "existing_connectors", "car_park_type",
         "supply_state", "utilisation", "land_use", "amenities_nearby", "nearest_point_m")

Facts = dict[str, object]
# A check returns whether the rule passed and the values its explanation needs.
Check = Callable[[Facts], tuple[bool, dict[str, Any]]]
_CAR_PARKS = {SiteKind.HDB_CAR_PARK.value, SiteKind.PUBLIC_CAR_PARK.value}


def _r01(f: Facts) -> tuple[bool, dict[str, Any]]:
    return True, {}  # passes whenever the fact exists; absence is caught as missing


def _r02(f: Facts) -> tuple[bool, dict[str, Any]]:
    return "BASEMENT" not in str(f["car_park_type"]).upper(), {}


def _r03(f: Facts) -> tuple[bool, dict[str, Any]]:
    share = MAX_SHARE_OF_LOTS.value
    lots, existing = cast(int, f["total_lots"]), cast(int, f["existing_connectors"])
    room = max(0, math.floor(round(share * lots, 9)) - existing)
    return room >= 1, {"room": room, "share": share}


def _r04(f: Facts) -> tuple[bool, dict[str, Any]]:
    # supply_state is already measured against IDLE_BELOW by analysis (§4.2).
    return f["supply_state"] != SupplyState.SUPPLY_IDLE.value, {"idle_below": IDLE_BELOW.value}


def _r05(f: Facts) -> tuple[bool, dict[str, Any]]:
    return True, {}


CHECKS: dict[str, Check] = {"R01": _r01, "R02": _r02, "R03": _r03, "R04": _r04, "R05": _r05}
# Rules that only concern some site kinds pass for every other kind, without their facts.
APPLIES_TO: dict[str, set[str]] = {"R02": _CAR_PARKS}


def load_register(path: Path = REGISTER) -> tuple[list[Rule], dict[str, Outcome]]:
    """The rules and, per rule, the outcome a failure gives. Rejects a malformed register."""
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("rules", [])
    rules: list[Rule] = []
    on_fail: dict[str, Outcome] = {}
    for entry in entries:
        item = dict(entry)
        outcome = Outcome(item.pop("on_fail", ""))
        rule = Rule.model_validate(item)
        problems = [
            "duplicate id" if rule.rule_id in on_fail else "",
            "on_fail must be reject or conditional"
            if outcome not in (Outcome.REJECT, Outcome.CONDITIONAL) else "",
            "no check implemented" if rule.rule_id not in CHECKS else "",
            "no source_ref" if not rule.source_ref else "",
            ", ".join(f"unknown fact {k}" for k in rule.required_facts if k not in FACTS),
        ]
        if any(problems):
            raise ValueError(f"{rule.rule_id}: {'; '.join(p for p in problems if p)}")
        rules.append(rule)
        on_fail[rule.rule_id] = outcome
    if not rules:
        raise ValueError(f"no rules in {path}")
    return rules, on_fail


def site_facts(site: CandidateSite, car_park: CarPark | None,
               indicators: SiteIndicators, context: dict[str, object]) -> Facts:
    """The facts for one site. Anything unknown is left out, never set to 0."""
    if indicators.site_id != site.site_id:
        raise ValueError(f"indicators for {indicators.site_id} given for {site.site_id}")
    return facts_without_indicators(site, car_park, context) | {
        k: v for k, v in (("supply_state", indicators.supply_state.value),
                          ("utilisation", indicators.utilisation)) if v is not None}


def facts_without_indicators(site: CandidateSite, car_park: CarPark | None,
                             context: dict[str, object]) -> Facts:
    """Facts for a site analysis has not measured yet; its supply rules will defer."""
    lots = site.total_lots if site.total_lots is not None else (
        car_park.total_lots if car_park else None)
    values: dict[str, object | None] = {
        "kind": site.kind.value,
        "planning_area": site.planning_area or (car_park.planning_area if car_park else None),
        "total_lots": lots,
        "existing_connectors": site.existing_connectors,
        "car_park_type": car_park.car_park_type if car_park else None,
        **{k: context.get(k) for k in ("land_use", "amenities_nearby", "nearest_point_m")},
    }
    return {k: v for k, v in values.items() if v is not None}


def _explain(rule: Rule, facts: Facts, values: dict[str, Any]) -> str:
    try:
        return rule.explanation_template.format(**facts, **values)
    except (KeyError, ValueError, TypeError, IndexError):
        return rule.condition


def evaluate_rule(rule: Rule, facts: Facts) -> RuleResult:
    """One rule on one site's facts."""
    kinds = APPLIES_TO.get(rule.rule_id)
    if kinds is not None and facts.get("kind") not in kinds:
        return RuleResult(rule_id=rule.rule_id, passed=True,
                          detail=f"Does not apply to a {facts.get('kind', 'site')}.")
    missing = [k for k in rule.required_facts if facts.get(k) is None]
    if missing:
        return RuleResult(rule_id=rule.rule_id, passed=None,
                          detail=f"Not evaluated: missing {', '.join(missing)}.")
    passed, values = CHECKS[rule.rule_id](facts)
    return RuleResult(rule_id=rule.rule_id, passed=passed, detail=_explain(rule, facts, values))


def decide(results: list[RuleResult], on_fail: dict[str, Outcome]) -> Outcome:
    """§4.4 outcome policy: reject, then defer, then conditional, then accept."""
    failed = {on_fail[r.rule_id] for r in results if r.passed is False}
    if Outcome.REJECT in failed:
        return Outcome.REJECT
    if any(r.passed is None for r in results):
        return Outcome.DEFER
    return Outcome.CONDITIONAL if failed else Outcome.ACCEPT


def evaluate(site_id: str, facts: dict[str, object], rules: list[Rule],
             on_fail: dict[str, Outcome], scenario_id: str | None = None) -> Decision:
    """Every rule on one site, with the reason for each, and the resulting outcome."""
    unknown = [r.rule_id for r in rules if r.rule_id not in on_fail]
    if unknown:
        raise ValueError(f"no on_fail for {unknown}")
    results = [evaluate_rule(rule, facts) for rule in rules]
    return Decision(site_id=site_id, outcome=decide(results, on_fail), results=results,
                    scenario_id=scenario_id)
