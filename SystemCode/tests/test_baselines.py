"""Baselines (#36 busiest first, #37 spatial spread, SYSTEM_DESIGN.md §6), on optev.sample
through the harness."""

import math
from dataclasses import replace

from optev.evaluation import harness as H
from optev.evaluation.baselines import _metres, busiest_first, spatial_spread, utilisation

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


# Busiest first (#36, spec 025) ---------------------------------------------------------

UTIL = utilisation(INPUTS.indicators)


def _plan_of(plan) -> dict[str, int]:
    return {i.site_id: i.connectors for i in plan.items}


def test_busiest_first_places_the_requested_points_with_no_violations():
    plan = busiest_first(REQ, INPUTS)
    assert plan.total_connectors == REQ.points and H.violations(plan, REQ, INPUTS) == []
    assert plan.requested_connectors == REQ.points and plan.scenario_id == REQ.scenario_id


def test_busiest_first_fills_the_busiest_site_to_its_room_before_the_next():
    measured = sorted((sid for sid in _open() if UTIL.get(sid) is not None),
                      key=lambda sid: (-UTIL[sid], sid))  # type: ignore[operator]
    first, second = measured[:2]
    room = _open()[first]
    assert _plan_of(busiest_first(REQ, INPUTS)) == {first: REQ.points}  # 12 <= room 27
    assert _plan_of(busiest_first(replace(REQ, points=room + 3), INPUTS)) == {
        first: room, second: 3}


def test_unmeasured_sites_come_after_every_measured_one_never_as_zero():
    space = _open()
    measured = sum(r for sid, r in space.items() if UTIL.get(sid) is not None)
    plan = _plan_of(busiest_first(replace(REQ, points=measured + 1), INPUTS))
    unmeasured = sorted(sid for sid in space if UTIL.get(sid) is None)
    assert {sid for sid in plan if UTIL.get(sid) is None} == {unmeasured[0]}
    assert plan[unmeasured[0]] == 1
    assert all(plan.get(sid) == r for sid, r in space.items() if UTIL.get(sid) is not None)


def test_utilisation_takes_the_latest_window_and_keeps_none():
    old = INPUTS.indicators[0]
    new = old.model_copy(update={"window_end": "2099-01-01T00:00:00+08:00",
                                 "utilisation": None if old.utilisation is None else 0.01})
    assert utilisation([old, new])[old.site_id] == new.utilisation
    assert utilisation([new, old])[old.site_id] == new.utilisation
    assert None in UTIL.values() and 0 not in UTIL.values()


def test_busiest_first_ignores_demand_and_respects_the_area():
    tripled = replace(INPUTS, demand=[e.model_copy(update={"arrivals_per_hour":
                                                          e.arrivals_per_hour * 3 + 1})
                                      for e in INPUTS.demand])
    assert busiest_first(REQ, tripled) == busiest_first(REQ, INPUTS)
    in_pr = busiest_first(replace(REQ, planning_area="PR"), INPUTS)
    assert {SITES[i.site_id].planning_area for i in in_pr.items} == {"PR"}
    total = sum(_open().values())
    assert busiest_first(replace(REQ, points=total + 50), INPUTS).total_connectors == total


def test_busiest_first_is_in_the_comparison_table():
    row = {r.method: r for r in H.compare(REQ, INPUTS, METHODS)}["busiest first (#36)"]
    assert row.points == REQ.points and row.violations == 0
