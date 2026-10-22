"""Baselines (#37 spatial spread, SYSTEM_DESIGN.md §6), on optev.sample through the harness."""

import math
from dataclasses import replace

from optev.evaluation import harness as H
from optev.evaluation.baselines import _metres, spatial_spread

REQ, INPUTS, METHODS = H.sample_inputs()
SITES = {s.site_id: s for s in INPUTS.sites}


def _open() -> dict[str, int]:
    c = H.effective(INPUTS)
    return {s.site_id: H.room(s, c[s.site_id]) for s in H.eligible(REQ, INPUTS)
            if H.room(s, c[s.site_id]) > 0}


def test_places_the_requested_points_with_no_violations():
    plan = spatial_spread(REQ, INPUTS)
    assert plan.total_connectors == REQ.points
    assert H.violations(plan, REQ, INPUTS) == []
    assert plan.requested_connectors == REQ.points and plan.scenario_id == REQ.scenario_id


def test_first_point_goes_farthest_from_existing_charging():
    c = H.effective(INPUTS)
    charging = [s.coord for s in INPUTS.sites if c[s.site_id] > 0]
    far = max(_open(), key=lambda sid: (min(_metres(SITES[sid].coord, a) for a in charging),
                                        [-ord(ch) for ch in sid]))
    one = spatial_spread(replace(REQ, points=1), INPUTS)
    assert [i.site_id for i in one.items] == [far]


def test_spreads_one_point_per_site_before_doubling_up():
    plan = spatial_spread(REQ, INPUTS)
    assert len(_open()) >= REQ.points  # the sample has enough open sites
    assert all(i.connectors == 1 for i in plan.items)


def test_new_sites_come_before_sites_that_already_charge():
    c = H.effective(INPUTS)
    fresh = [sid for sid in _open() if c[sid] == 0]
    plan = spatial_spread(replace(REQ, points=len(fresh)), INPUTS)
    assert {i.site_id for i in plan.items} == set(fresh)


def test_ignores_demand():
    doubled = replace(INPUTS, demand=[e.model_copy(update={"arrivals_per_hour":
                                                          e.arrivals_per_hour * 3 + 1})
                                      for e in INPUTS.demand])
    assert spatial_spread(REQ, doubled) == spatial_spread(REQ, INPUTS)


def test_stops_when_room_runs_out_and_respects_the_area():
    total_room = sum(_open().values())
    big = spatial_spread(replace(REQ, points=total_room + 50), INPUTS)
    assert big.total_connectors == total_room
    assert H.violations(big, replace(REQ, points=total_room + 50), INPUTS) == []
    in_pr = spatial_spread(replace(REQ, planning_area="PR"), INPUTS)
    assert {SITES[i.site_id].planning_area for i in in_pr.items} == {"PR"}


def test_metres_is_a_great_circle_distance():
    a, b = INPUTS.sites[0].coord, INPUTS.sites[-1].coord
    assert _metres(a, a) == 0
    assert 3000 < _metres(a, b) < 3300 and math.isclose(_metres(a, b), _metres(b, a))


def test_is_in_the_comparison_table():
    rows = {r.method: r for r in H.compare(REQ, INPUTS, METHODS)}
    spread = rows["spatial spread (#37)"]
    assert spread.points == REQ.points and spread.violations == 0
