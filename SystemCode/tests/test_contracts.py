"""Day-one tests. These exist so CI is real before there is anything to break."""

import pytest
from pydantic import ValidationError

from optev.contracts import (
    Allocation,
    AllocationItem,
    Coordinate,
    Decision,
    Outcome,
    RuleResult,
    SiteIndicators,
    SupplyState,
)


def test_coordinate_rejects_points_outside_singapore():
    Coordinate(lat=1.3521, lon=103.8198)
    with pytest.raises(ValidationError):
        Coordinate(lat=51.5, lon=-0.12)


@pytest.mark.parametrize("state", [SupplyState.NO_SUPPLY, SupplyState.UNOBSERVED])
def test_utilisation_must_be_none_without_supply(state):
    """Zero would sort these sites to the bottom of a ranking as if nobody wanted to
    charge there. That is the failure the project exists to avoid."""
    with pytest.raises(ValidationError):
        SiteIndicators(site_id="s1", window_start="a", window_end="b",
                       supply_state=state, utilisation=0.0)
    ok = SiteIndicators(site_id="s1", window_start="a", window_end="b", supply_state=state)
    assert ok.utilisation is None


def test_decision_separates_failures_from_unevaluated_rules():
    d = Decision(site_id="s1", outcome=Outcome.DEFER, results=[
        RuleResult(rule_id="R1", passed=True),
        RuleResult(rule_id="R2", passed=False),
        RuleResult(rule_id="R3", passed=None, detail="total_lots missing"),
    ])
    assert d.failing_rules == ["R2"]
    assert d.unevaluated_rules == ["R3"]


def test_allocation_totals():
    a = Allocation(scenario_id="sc1", budget=100_000, items=[
        AllocationItem(site_id="s1", connectors=2, cost=20_000),
        AllocationItem(site_id="s2", connectors=4, cost=38_000),
    ])
    assert a.total_connectors == 6
    assert a.total_cost == 58_000
    assert a.checked is False


def test_allocation_needs_points_or_budget():
    assert Allocation(scenario_id="sc1", requested_connectors=12).budget is None
    with pytest.raises(ValidationError):
        Allocation(scenario_id="sc1")


def test_contracts_round_trip_through_json():
    a = Allocation(scenario_id="sc1", budget=1.0,
                   items=[AllocationItem(site_id="s1", connectors=1, cost=1.0)])
    assert Allocation.model_validate_json(a.model_dump_json()) == a
