"""The shared sample data must be valid, self-consistent, and reproducible, because every
workstream builds against it until real data lands."""

from collections import defaultdict

from optev.contracts import Outcome, SupplyState
from optev.sample import DATA, connector_readings, load, truth
from optev.sample.generate import RELIABLE_UP_TO, write

S = load()


def test_everything_is_labelled_synthetic():
    ids = (
        [c.car_park_id for c in S.car_parks]
        + [s.station_id for s in S.stations]
        + [c.connector_id for c in S.connectors]
        + [s.site_id for s in S.sites]
    )
    assert ids and all(i.startswith("SYN-") for i in ids)


def test_references_resolve():
    areas = {a.code for a in S.planning_areas}
    car_parks = {c.car_park_id for c in S.car_parks}
    stations = {s.station_id for s in S.stations}
    sites = {s.site_id for s in S.sites}
    rules = {r.rule_id for r in S.rules}
    assert {s.planning_area for s in S.sites} <= areas
    assert {s.car_park_id for s in S.sites if s.car_park_id} <= car_parks
    assert {c.station_id for c in S.connectors} <= stations
    assert {n["station_id"] for n in S.near} == stations
    for group in (S.indicators, S.estimates, S.decisions):
        assert {x.site_id for x in group} == sites
    assert {r.rule_id for d in S.decisions for r in d.results} == rules
    assert {i.site_id for i in S.allocation.items} <= sites


def test_installed_capacity_counts_only_connectors_seen_active():
    active = defaultdict(int)
    for c in S.connectors:
        active[c.station_id] += c.ever_active
    by_site = {n["site_id"]: active[n["station_id"]] for n in S.near}
    assert any(not c.ever_active for c in S.connectors), "sample should include a planned unit"
    for site in S.sites:
        assert site.existing_connectors == by_site.get(site.site_id, 0)


def test_no_supply_means_utilisation_is_absent_not_zero():
    for ind in S.indicators:
        site = next(s for s in S.sites if s.site_id == ind.site_id)
        assert (ind.supply_state is SupplyState.NO_SUPPLY) == (site.existing_connectors == 0)
        if ind.supply_state is SupplyState.NO_SUPPLY:
            assert ind.utilisation is None


def test_indicators_match_the_readings():
    station_of_site = {n["site_id"]: n["station_id"] for n in S.near}
    snaps: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in connector_readings():
        snaps[r.connector_id.rsplit("-", 1)[0]][r.collected_ts.isoformat()].append(r.status.value)
    for ind in S.indicators:
        if ind.site_id not in station_of_site:
            continue
        ratios, saturated = [], 0
        for statuses in snaps[station_of_site[ind.site_id]].values():
            occ, avail = statuses.count("occupied"), statuses.count("available")
            if occ + avail:
                ratios.append(occ / (occ + avail))
                saturated += avail == 0 and occ > 0
        assert ind.utilisation is not None
        assert abs(sum(ratios) / len(ratios) - ind.utilisation) < 1e-4
        assert ind.saturated_fraction is not None
        assert abs(saturated / len(ratios) - ind.saturated_fraction) < 1e-4


def test_lower_bound_exactly_where_occupancy_is_unreliable_and_it_holds():
    util = {i.site_id: i.utilisation for i in S.indicators}
    answer = truth()["sites"]
    kinds = [e.kind.value for e in S.estimates]
    assert "lower_bound" in kinds and "point" in kinds
    for e in S.estimates:
        u = util[e.site_id]
        assert (e.kind.value == "lower_bound") == (u is not None and u >= RELIABLE_UP_TO)
        if e.kind.value == "lower_bound":
            assert e.arrivals_per_hour <= answer[e.site_id]["true_arrivals_per_hour"]


def test_decisions_follow_the_outcome_policy():
    assert {d.outcome for d in S.decisions} == set(Outcome)  # all four appear
    for d in S.decisions:
        failed = {S.rule_on_fail[r] for r in d.failing_rules}
        if Outcome.REJECT in failed:
            expected = Outcome.REJECT
        elif d.unevaluated_rules:
            expected = Outcome.DEFER
        else:
            expected = Outcome.CONDITIONAL if failed else Outcome.ACCEPT
        assert d.outcome is expected, d.site_id


def test_reference_allocation_respects_every_constraint():
    a, site = S.allocation, {s.site_id: s for s in S.sites}
    allowed = {d.site_id for d in S.decisions if d.outcome in (Outcome.ACCEPT, Outcome.CONDITIONAL)}
    assert a.checked and not a.violations
    assert a.total_cost <= a.budget
    assert a.total_connectors == a.requested_connectors
    per_area: dict[str | None, int] = defaultdict(int)
    for item in a.items:
        s = site[item.site_id]
        assert item.site_id in allowed
        assert s.total_lots is not None
        assert s.existing_connectors + item.connectors <= int(0.1 * s.total_lots)
        per_area[s.planning_area] += item.connectors
    assert all(per_area[area.code] >= 2 for area in S.planning_areas)


def test_regenerates_byte_for_byte(tmp_path):
    write(tmp_path)
    for name in ("entities.json", "truth.json", "connector_readings.csv", "car_park_readings.csv"):
        assert (tmp_path / name).read_bytes() == (DATA / name).read_bytes(), name
