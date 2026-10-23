"""Allocator (SYSTEM_DESIGN.md §4.4, #20 and #21, spec 021), on optev.sample. No database."""

import math

import pytest

from optev.assumptions import COST_PER_POINT_SGD
from optev.contracts import (
    Allocation,
    Decision,
    DemandEstimate,
    EstimateKind,
    InfeasibilityReport,
    Outcome,
    PlannedCapacity,
)
from optev.reasoning import allocate as A
from optev.sample import generate, load

S = load()
SITE = {s.site_id: s for s in S.sites}
BASE = next(x for x in S.scenarios if x.scenario_id == "base")
# scenario demand for base: the observed estimates times its growth multiplier (§4.3)
DEMAND = [e.model_copy(update={"arrivals_per_hour": e.arrivals_per_hour * BASE.growth_multiplier})
          for e in S.estimates]
COST = COST_PER_POINT_SGD.value


def _relief(plan: dict[str, int]) -> float:
    """A plan's objective (drivers per hour rescued), scored on base's effective connectors."""
    c = A.effective_connectors(S.sites, BASE)
    profile = A.demand_profile(DEMAND)
    return sum(sum(A.marginal_gains(c[s], profile.get(s, []), n)) for s, n in plan.items())


def _base(**request) -> Allocation | InfeasibilityReport:
    return A.allocate(S.decisions, S.sites, DEMAND, BASE, **request)


# Cost model and constraints (#20) ------------------------------------------------------


def test_erlang_b_matches_the_sample_generator():
    for c, a in [(0, 1.5), (1, 0.4), (4, 2.7), (12, 9.0), (6, 0.0)]:
        assert A.erlang_b(c, a) == pytest.approx(generate.erlang_b(c, a), abs=1e-12)


def test_marginal_gains_never_increase_and_match_erlang_b():
    profile = [(A.WEIGHT["wd"], 3.0)] * 24 + [(A.WEIGHT["we"], 1.0)] * 24
    gains = A.marginal_gains(2, profile, 6)
    assert len(gains) == 6 and all(g >= 0 for g in gains)
    assert all(g1 >= g2 for g1, g2 in zip(gains, gains[1:], strict=False))
    a_wd, a_we = 3.0 * A.MEAN_SESSION_HOURS.value, 1.0 * A.MEAN_SESSION_HOURS.value
    first = (5 / 7 * 3.0 * (A.erlang_b(2, a_wd) - A.erlang_b(3, a_wd))
             + 2 / 7 * 1.0 * (A.erlang_b(2, a_we) - A.erlang_b(3, a_we)))
    assert gains[0] == pytest.approx(first)
    assert A.marginal_gains(3, [], 2) == [0.0, 0.0] and A.marginal_gains(3, profile, 0) == []


def test_the_48_bin_weights_sum_to_one_and_bins_win_over_all():
    bins = [f"{d}-{h:02d}" for d in ("wd", "we") for h in range(24)]
    assert sum(A.WEIGHT[b[:2]] for b in bins) == pytest.approx(1.0)
    est = [DemandEstimate(site_id="X", time_bin=b, arrivals_per_hour=1.0,
                          kind=EstimateKind.POINT) for b in bins]
    est += [DemandEstimate(site_id="X", time_bin="all", arrivals_per_hour=9.0,
                           kind=EstimateKind.POINT),
            DemandEstimate(site_id="Y", time_bin="all", arrivals_per_hour=2.0,
                           kind=EstimateKind.LOWER_BOUND)]
    profile = A.demand_profile(est)
    assert len(profile["X"]) == 48 and {lam for _, lam in profile["X"]} == {1.0}
    assert profile["Y"] == [(1.0, 2.0)]  # only `all`: used with weight 1 (spec 021)


def test_room_is_fifteen_percent_of_lots_less_effective_connectors():
    assert A.room(210, 2) == 29  # floor(0.15 x 210) = 31
    assert A.room(60, 0) == 9  # no floating-point loss at a whole number
    assert A.room(20, 5) == 0  # floored at 0
    assert A.room(None, 0) == 0  # no lot count, no stated room


def test_effective_connectors_add_this_scenarios_planned_points():
    c = A.effective_connectors(S.sites, BASE)
    assert c["SYN-S-04"] == SITE["SYN-S-04"].existing_connectors + 2  # base plans 2 there
    assert c["SYN-S-01"] == SITE["SYN-S-01"].existing_connectors
    observed = A.effective_connectors(S.sites, BASE.model_copy(update={"planned": []}))
    assert observed["SYN-S-04"] == SITE["SYN-S-04"].existing_connectors


def test_eligible_sites_are_accept_or_conditional_and_a_scenario_decision_wins():
    outcome = {d.site_id: d.outcome for d in S.decisions}
    pool = {s.site_id for s in A.eligible_sites(S.decisions, S.sites, "base", None)}
    assert pool == {s for s, o in outcome.items() if o in A.ELIGIBLE}
    rejected = next(s for s, o in outcome.items() if o is Outcome.REJECT)
    override = Decision(site_id=rejected, outcome=Outcome.ACCEPT, scenario_id="base")
    pool = {s.site_id for s in A.eligible_sites([*S.decisions, override], S.sites, "base", None)}
    assert rejected in pool
    in_pr = A.eligible_sites(S.decisions, S.sites, "base", "PR")
    assert in_pr and all(s.planning_area == "PR" for s in in_pr)


def test_points_come_from_the_request_or_the_budget():
    assert A.points_for(12, None) == 12 and A.points_for(12, 1e6) == 12
    assert A.points_for(None, 300_000) == 32 == A.budget_cap(300_000)  # floor(300000 / 9250)
    assert A.points_for(None, 3 * COST) == 3  # no float loss at an exact multiple
    assert A.budget_cap(None) is None
    with pytest.raises(ValueError):
        A.points_for(None, None)


# Allocation (#21) -----------------------------------------------------------------------


def _plan(result: Allocation | InfeasibilityReport) -> dict[str, int]:
    assert isinstance(result, Allocation)
    return {i.site_id: i.connectors for i in result.items}


def test_twelve_points_island_wide_meet_every_constraint_and_beat_the_greedy_reference():
    result = _base(requested_connectors=12)
    plan = _plan(result)
    assert isinstance(result, Allocation)
    assert result.total_connectors == 12 and not result.checked and result.budget is None
    assert (result.scenario_id, result.planning_area, result.requested_connectors) == (
        "base", None, 12)
    c = A.effective_connectors(S.sites, BASE)
    eligible = {s.site_id for s in A.eligible_sites(S.decisions, S.sites, "base", None)}
    for item in result.items:
        assert item.site_id in eligible
        assert item.connectors <= A.room(SITE[item.site_id].total_lots, c[item.site_id])
        assert item.cost == COST * item.connectors
    reference = {i.site_id: i.connectors for i in S.allocation.items}
    assert _relief(plan) >= _relief(reference) - 1e-9
    assert sum(i.marginal_relief or 0 for i in result.items) == pytest.approx(_relief(plan),
                                                                              abs=1e-3)


def test_planned_capacity_takes_room_and_lowers_the_gain():
    crowded = BASE.model_copy(update={"planned": [PlannedCapacity(site_id="SYN-S-04",
                                                                  connectors=29)]})
    result = A.allocate(S.decisions, S.sites, DEMAND, crowded, requested_connectors=12)
    assert "SYN-S-04" not in _plan(result)  # floor(0.15 x 210) = 31 = 2 existing + 29 planned


def test_budget_only_places_as_many_points_as_it_pays_for():
    result = _base(budget=300_000)
    assert isinstance(result, Allocation)
    assert result.total_connectors == 32 and result.total_cost <= 300_000
    assert result.requested_connectors is None and result.budget == 300_000


def test_too_many_points_for_the_budget_report_the_most_feasible():
    result = _base(planning_area="PR", requested_connectors=40, budget=300_000)
    assert isinstance(result, InfeasibilityReport)
    assert (result.planning_area, result.requested_connectors, result.max_feasible) == (
        "PR", 40, 32)
    assert result == S.infeasibility  # the sample's report, binding constraints included


def test_an_area_request_stays_in_the_area():
    plan = _plan(_base(planning_area="TM", requested_connectors=5))
    assert sum(plan.values()) == 5 and all(SITE[s].planning_area == "TM" for s in plan)


def test_no_minimum_per_area_so_an_area_without_demand_gets_nothing():
    no_pr = [e for e in DEMAND if SITE[e.site_id].planning_area != "PR"]
    plan = _plan(A.allocate(S.decisions, S.sites, no_pr, BASE, requested_connectors=12))
    assert sum(plan.values()) == 12
    assert not any(SITE[s].planning_area == "PR" for s in plan)  # 0 is a valid answer (1.8)


def test_an_area_with_no_room_does_not_block_the_others():
    full = [s.model_copy(update={"total_lots": 6}) if s.planning_area == "PR" else s
            for s in S.sites]  # floor(0.15 x 6) = 0: no PR site has room
    plan = _plan(A.allocate(S.decisions, full, DEMAND, BASE, requested_connectors=12))
    assert sum(plan.values()) == 12 and all(SITE[s].planning_area == "TM" for s in plan)


def test_more_points_than_all_the_room_is_infeasible():
    pool = A.eligible_sites(S.decisions, S.sites, "base", "PR")
    c = A.effective_connectors(pool, BASE)
    total = sum(A.room(s.total_lots, c[s.site_id]) for s in pool)
    result = _base(planning_area="PR", requested_connectors=total + 1)
    assert isinstance(result, InfeasibilityReport) and result.max_feasible == total


def test_neither_points_nor_budget_is_an_error():
    with pytest.raises(ValueError):
        _base()


def test_the_same_request_gives_the_same_plan():
    first, second = _base(requested_connectors=12), _base(requested_connectors=12)
    assert first == second
    assert math.isclose(sum(i.cost for i in first.items), 12 * COST)  # type: ignore[union-attr]


# Unmet requirement (#23) ---------------------------------------------------------------


def _pr_room() -> int:
    pool = A.eligible_sites(S.decisions, S.sites, "base", "PR")
    c = A.effective_connectors(pool, BASE)
    return sum(A.room(s.total_lots, c[s.site_id]) for s in pool)


def test_over_the_budget_only_names_the_budget():
    result = _base(planning_area="PR", requested_connectors=40, budget=300_000)
    assert isinstance(result, InfeasibilityReport)
    assert result.binding_constraints == ["budget"] and result.affected_areas == []


def test_over_the_room_only_names_the_room():
    total = _pr_room()
    result = _base(planning_area="PR", requested_connectors=total + 1)
    assert isinstance(result, InfeasibilityReport)
    assert result.binding_constraints == ["room"] and result.max_feasible == total


def test_over_both_names_neither_since_neither_alone_is_enough():
    total = _pr_room()
    result = _base(planning_area="PR", requested_connectors=total + 1, budget=COST * (total - 1))
    assert isinstance(result, InfeasibilityReport)
    assert result.binding_constraints == [] and result.max_feasible == total - 1


def test_budget_only_with_too_little_room_requests_what_the_budget_pays_for():
    total = _pr_room()
    budget = COST * (total + 5) + 1000
    result = _base(planning_area="PR", budget=budget)
    assert isinstance(result, InfeasibilityReport)
    assert result.requested_connectors == math.floor(budget / COST) == total + 5
    assert result.binding_constraints == ["room"] and result.max_feasible == total


def test_binding_names_only_groups_that_alone_fall_short():
    rooms = {"a": 3, "b": 2}
    assert A.binding(5, rooms, None) == []
    assert A.binding(6, rooms, None) == ["room"]
    assert A.binding(5, rooms, 4) == ["budget"]
    assert A.binding(6, rooms, 4) == []
    assert A.binding(4, {}, 10) == ["room"]  # no eligible site: the room is zero


# Pruning (scale fix for the real data) ---------------------------------------------------

def _objective(gains, plan):
    return sum(sum(gains[s][:n]) for s, n in plan.items())


def test_pruning_never_changes_the_optimum():
    import random

    from optev.reasoning.allocate import prune, solve

    rng = random.Random(7)
    for _ in range(25):
        gains = {f"s{i}": sorted((rng.random() for _ in range(rng.randint(0, 6))), reverse=True)
                 for i in range(12)}
        total = sum(len(g) for g in gains.values())
        for points in (1, 3, 7, total):
            full, pruned = solve(gains, points, None), solve(prune(gains, points), points, None)
            assert (full is None) == (pruned is None)
            if full:
                assert abs(_objective(gains, full) - _objective(gains, pruned)) < 1e-3


def test_pruning_keeps_each_sites_list_a_prefix_and_enough_points():
    from optev.reasoning.allocate import prune

    gains = {"a": [5.0, 3.0, 1.0], "b": [4.0, 2.0], "c": [0.5]}
    kept = prune(gains, 3)
    assert kept == {"a": [5.0, 3.0], "b": [4.0]}
    assert sum(len(g) for g in kept.values()) >= 3
    assert prune(gains, 10) == gains  # fewer candidates than points: nothing to drop


def test_island_wide_scale_solves_quickly_after_pruning():
    import random
    import time

    from optev.reasoning.allocate import prune, solve

    rng = random.Random(1)
    gains = {f"s{i}": sorted((rng.random() for _ in range(30)), reverse=True)
             for i in range(3000)}  # the real data's size: ~3,000 sites, 30 points each
    t0 = time.perf_counter()
    plan = solve(prune(gains, 100), 100, None)
    assert plan is not None and sum(plan.values()) == 100
    assert time.perf_counter() - t0 < 10
    best = sorted((g for gs in gains.values() for g in gs), reverse=True)[:100]
    assert abs(_objective(gains, plan) - sum(best)) < 1e-2  # the top 100 gains overall
