"""The independent checker. SYSTEM_DESIGN.md §4.4 (#22), spec 016.

Whatever proposes a plan must not be what approves it, so this module re-tests every
allocation constraint from the design text alone. It never imports `allocate.py`; the
arithmetic both need (room, the budget floor, which decision applies) is written again here
on purpose.
"""

import math
from collections import Counter
from collections.abc import Iterable, Sequence

from optev.assumptions import COST_PER_POINT_SGD, MAX_SHARE_OF_LOTS
from optev.contracts import Allocation, CandidateSite, Decision, Outcome

APPROVED = frozenset({Outcome.ACCEPT, Outcome.CONDITIONAL})
NO_SCENARIO = frozenset({None, "observed"})


def _decision_for(decisions: Iterable[Decision], scenario_id: str) -> dict[str, Decision]:
    """The scenario's own decision per site, else the baseline one."""
    chosen: dict[str, Decision] = {}
    for d in decisions:
        if d.scenario_id in NO_SCENARIO:
            chosen.setdefault(d.site_id, d)
    for d in decisions:
        if d.scenario_id == scenario_id:
            chosen[d.site_id] = d
    return chosen


def _space(site: CandidateSite) -> int:
    """`floor(MAX_SHARE_OF_LOTS × total_lots) − existing_connectors`, at least 0. Planned
    capacity is not visible here (spec 016, Q1)."""
    if site.total_lots is None:
        return 0
    limit = math.floor(round(site.total_lots * MAX_SHARE_OF_LOTS.value, 9))
    return max(limit - site.existing_connectors, 0)


def _points_expected(allocation: Allocation) -> int | None:
    if allocation.requested_connectors is not None:
        return allocation.requested_connectors
    if allocation.budget is not None:
        return math.floor(allocation.budget / COST_PER_POINT_SGD.value + 1e-9)
    return None


def violations(allocation: Allocation, decisions: Sequence[Decision],
               sites: Sequence[CandidateSite]) -> list[str]:
    """Every broken constraint, one `"<code>: <detail>"` string per instance (spec 016)."""
    found: list[str] = []
    by_id = {s.site_id: s for s in sites}
    decision = _decision_for(decisions, allocation.scenario_id)
    area = allocation.planning_area
    unit = COST_PER_POINT_SGD.value

    seen = Counter(item.site_id for item in allocation.items)
    found += [f"duplicate_site: {s} appears {n} times" for s, n in sorted(seen.items()) if n > 1]
    for item in allocation.items:
        site = by_id.get(item.site_id)
        if site is None:
            found.append(f"unknown_site: {item.site_id}")
            continue
        d = decision.get(item.site_id)
        if d is None or d.outcome not in APPROVED:
            found.append(f"not_eligible: {item.site_id} is {d.outcome.value if d else 'undecided'}")
        if area is not None and site.planning_area != area:
            found.append(f"outside_area: {item.site_id} is in {site.planning_area}, not {area}")
        if item.connectors > _space(site):
            found.append(f"room: {item.site_id} has {item.connectors}, room {_space(site)}")
        if round(item.cost, 2) != round(unit * item.connectors, 2):
            found.append(f"cost: {item.site_id} costs {item.cost:.2f}, "
                         f"expected {unit * item.connectors:.2f}")

    total = sum(item.connectors for item in allocation.items)
    expected = _points_expected(allocation)
    if expected is not None and total != expected:
        found.append(f"points: {total} placed, {expected} requested")
    if allocation.budget is not None and unit * total > allocation.budget + 1e-6:
        found.append(f"budget: {unit * total:.2f} over {allocation.budget:.2f}")

    return found


def check(allocation: Allocation, decisions: list[Decision],
          sites: list[CandidateSite]) -> Allocation:
    """Re-test the plan. Returns a copy with `violations` filled and `checked = True`: checked
    means re-tested, and an empty `violations` means it passed (spec 016, Q2)."""
    return allocation.model_copy(
        update={"violations": violations(allocation, decisions, sites), "checked": True})
