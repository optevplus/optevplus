"""Independent checker (SYSTEM_DESIGN.md §4.4, #22, spec 016), on optev.sample. Every planted
fault in a good plan must be caught, each by its own code."""

import ast
from pathlib import Path

import pytest

from optev.contracts import Allocation, AllocationItem, Outcome
from optev.reasoning import checker as K
from optev.sample import load

S = load()
SITE = {s.site_id: s for s in S.sites}
GOOD = S.allocation.model_copy(update={"checked": False})  # 12 points island-wide, base
COST = 9_250.0


def _codes(allocation: Allocation) -> list[str]:
    return [v.split(":")[0] for v in K.violations(allocation, S.decisions, S.sites)]


def _with(items: list[AllocationItem], **request) -> Allocation:
    return GOOD.model_copy(update={"items": items, **request})


def _item(site_id: str, n: int) -> AllocationItem:
    return AllocationItem(site_id=site_id, connectors=n, cost=COST * n)


def test_the_reference_plan_passes_and_the_input_is_unchanged():
    result = K.check(GOOD, S.decisions, S.sites)
    assert result.checked and result.violations == []
    assert not GOOD.checked and result.items == GOOD.items


def test_a_failing_plan_is_still_marked_checked_with_its_violations():
    result = K.check(_with(GOOD.items[1:]), S.decisions, S.sites)
    assert result.checked and result.violations


def _swap(old: str, new: str, n: int | None = None) -> list[AllocationItem]:
    return [_item(new, n or i.connectors) if i.site_id == old else i for i in GOOD.items]


def test_a_rejected_or_deferred_site_is_caught():
    for outcome in (Outcome.REJECT, Outcome.DEFER):
        bad = next(d.site_id for d in S.decisions if d.outcome is outcome
                   and SITE[d.site_id].planning_area == SITE[GOOD.items[0].site_id].planning_area)
        assert "not_eligible" in _codes(_with(_swap(GOOD.items[0].site_id, bad)))


def test_a_scenario_decision_overrides_the_baseline():
    rejected = next(d.site_id for d in S.decisions if d.outcome is Outcome.REJECT)
    accepted = [d.model_copy(update={"outcome": Outcome.ACCEPT, "scenario_id": "base"})
                for d in S.decisions if d.site_id == rejected]
    plan = _with(_swap(GOOD.items[0].site_id, rejected, 1))
    assert "not_eligible" not in [v.split(":")[0] for v in
                                  K.violations(plan, [*S.decisions, *accepted], S.sites)]


def test_an_unknown_and_a_duplicated_site_are_caught():
    assert _codes(_with(_swap(GOOD.items[0].site_id, "SYN-S-99"))) == ["unknown_site"]
    assert "duplicate_site" in _codes(_with([*GOOD.items, GOOD.items[0]]))


def test_a_site_outside_the_requested_area_is_caught():
    tm = [i for i in GOOD.items if SITE[i.site_id].planning_area == "TM"]
    pr = next(i for i in GOOD.items if SITE[i.site_id].planning_area == "PR")
    n = sum(i.connectors for i in tm) + pr.connectors
    assert _codes(_with([*tm, pr], planning_area="TM", requested_connectors=n)) == [
        "outside_area"]


def test_the_wrong_number_of_points_is_caught():
    assert _codes(_with(GOOD.items, requested_connectors=11)) == ["points"]


def test_budget_only_plans_must_place_what_the_budget_pays_for():
    items = [_item(i.site_id, i.connectors) for i in GOOD.items]
    assert _codes(_with(items, requested_connectors=None, budget=12 * COST)) == []
    assert _codes(_with(items, requested_connectors=None, budget=13 * COST)) == ["points"]


def test_going_over_budget_is_caught():
    assert _codes(_with(GOOD.items, budget=12 * COST - 0.01)) == ["budget"]


def test_more_points_than_room_is_caught():
    site = GOOD.items[0].site_id
    space = K._space(SITE[site])
    over = _with(_swap(site, site, space + 1),
                 requested_connectors=GOOD.total_connectors - GOOD.items[0].connectors + space + 1)
    assert _codes(over) == ["room"]


def test_an_area_below_its_minimum_is_caught():
    pr = [i for i in GOOD.items if SITE[i.site_id].planning_area == "PR"]
    others = [i for i in GOOD.items if i not in pr]
    one = [_item(pr[0].site_id, 1)]
    plan = _with([*others, *one], requested_connectors=sum(i.connectors for i in others) + 1)
    assert _codes(plan) == ["coverage"]


def test_a_wrong_cost_is_caught():
    items = [i.model_copy(update={"cost": i.cost + 1}) if k == 0 else i
             for k, i in enumerate(GOOD.items)]
    assert _codes(_with(items)) == ["cost"]


def test_violations_name_what_broke():
    plan = _with(GOOD.items, requested_connectors=11)
    assert K.violations(plan, S.decisions, S.sites) == ["points: 12 placed, 11 requested"]


@pytest.mark.parametrize("module", ["optev.reasoning.allocate", "allocate"])
def test_the_checker_never_imports_the_allocator(module):
    tree = ast.parse(Path(K.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert module not in imported
    assert all(m in {"math", "collections", "collections.abc", "optev.assumptions",
                     "optev.contracts"} for m in imported if m)
