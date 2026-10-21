"""The experiment harness (#39): a fair yardstick and baselines that obey the same limits."""

import pytest

from optev.contracts import Allocation, AllocationItem
from optev.evaluation import harness as H

REQ, INPUTS, METHODS = H.sample_inputs()


def _plan(**counts: int) -> Allocation:
    return Allocation(scenario_id=REQ.scenario_id, requested_connectors=REQ.points,
                      items=[AllocationItem(site_id=s.replace("_", "-"), connectors=n, cost=0)
                             for s, n in counts.items()])


def test_erlang_b_matches_known_values():
    assert H.erlang_b(0, 2.0) == 1.0
    assert H.erlang_b(1, 1.0) == pytest.approx(0.5)
    assert H.erlang_b(2, 1.0) == pytest.approx(0.2)


def test_rescued_is_zero_for_nothing_and_grows_with_points():
    assert H.rescued(_plan(), INPUTS) == 0.0
    one, two = H.rescued(_plan(SYN_S_04=1), INPUTS), H.rescued(_plan(SYN_S_04=2), INPUTS)
    assert 0 < one < two
    assert two - one <= one  # each extra point at a site helps no more than the last


def test_violations_name_room_eligibility_and_request():
    site = next(s for s in INPUTS.sites if s.site_id == "SYN-S-13")  # rejected in the sample
    assert any("not eligible" in v for v in H.violations(_plan(SYN_S_13=1), REQ, INPUTS))
    assert any("room for" in v for v in H.violations(_plan(SYN_S_04=999), REQ, INPUTS))
    assert any("requested" in v for v in H.violations(_plan(SYN_S_03=13), REQ, INPUTS))
    assert site.site_id == "SYN-S-13"


def test_random_is_reproducible_and_valid():
    a, b = H.random_plan(REQ, INPUTS, 7), H.random_plan(REQ, INPUTS, 7)
    assert a == b and a.total_connectors == REQ.points
    for seed in range(20):
        assert H.violations(H.random_plan(REQ, INPUTS, seed), REQ, INPUTS) == []


def test_population_share_follows_residents_when_given():
    plan = H.population_share(REQ, INPUTS)
    assert plan.total_connectors == REQ.points and H.violations(plan, REQ, INPUTS) == []
    weighted = H.Inputs(INPUTS.decisions, INPUTS.sites, INPUTS.demand, INPUTS.scenario,
                        residents={"TM": 0, "PR": 1})
    areas = {s.site_id: s.planning_area for s in INPUTS.sites}
    assert {areas[i.site_id] for i in H.population_share(REQ, weighted).items} == {"PR"}


def test_the_table_compares_every_method_on_one_request():
    rows = H.compare(REQ, INPUTS, METHODS)
    names = [r.method for r in rows]
    assert names[:2] == ["random (mean of 100)", "population share"]
    assert "sample reference (greedy)" in names
    assert all(r.violations == 0 for r in rows)
    best = max(rows[:2], key=lambda r: r.rescued)
    assert best.vs_best_baseline == pytest.approx(1.0)
    greedy = next(r for r in rows if r.method == "sample reference (greedy)")
    assert greedy.rescued > rows[0].rescued  # beats random on average
    assert "| Method |" in H.markdown(rows)
