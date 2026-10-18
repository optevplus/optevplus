"""The loader's logic lives in rows(), so it is tested here without a database.
tests/test_graph_live.py loads the sample into a real Neo4j when credentials are present."""

from dataclasses import replace
from typing import Any

import pytest

from optev.contracts import SupplyState
from optev.graph import load as L
from optev.graph import schema as S
from optev.sample import load as sample

DATA = sample()
# The sample's decisions are all baseline and its impossible request affects no area, so add
# one scenario decision and one affected area to reach every relationship.
FULL = replace(
    DATA,
    decisions=[*DATA.decisions, DATA.decisions[0].model_copy(update={"scenario_id": "base"})],
    infeasibility=DATA.infeasibility.model_copy(update={"affected_areas": ["PR"]}),
)
BATCHES = {b.name: b for b in L.rows(FULL)}

NOT_LOADED = {
    "SourceClass",  # seeded by apply_schema
    "Scenario-ASSUMES->Assumption",  # waits for growth assumptions from #28
}


def _keys(label: str) -> set[str]:
    return {r["key"] for r in BATCHES[label].rows}


def test_every_declared_node_and_relationship_is_loaded():
    declared = {n.label for n in S.NODES} | {
        f"{r.start}-{r.type}->{r.end}" for r in S.RELATIONSHIPS
    }
    assert set(BATCHES) == declared - NOT_LOADED


def test_nodes_carry_exactly_the_schema_properties():
    for n in S.NODES:
        for row in BATCHES.get(n.label, L.Batch(n.label, "")).rows:
            assert row["key"], n.label
            assert set(row["props"]) == set(n.properties), n.label


def test_relationships_only_join_nodes_that_are_loaded():
    seeded = {s.value for s in S.SOURCE_CLASSES}
    for name, batch in BATCHES.items():
        if "->" not in name:
            continue
        start, rest = name.split("-", 1)
        end = rest.split("->")[1]
        ends = seeded if end == "SourceClass" else _keys(end)
        for row in batch.rows:
            assert row["a"] in _keys(start), (name, row)
            assert row["b"] in ends, (name, row)


def test_missing_values_stay_absent_never_zero():
    no_supply = {
        i.site_id for i in DATA.indicators if i.supply_state is SupplyState.NO_SUPPLY
    }
    assert no_supply
    for row in BATCHES["Indicator"].rows:
        if row["key"].split("@")[0] in no_supply:
            assert row["props"]["utilisation"] is None


def test_planned_capacity_is_only_a_scenario_relationship():
    for row in BATCHES["CandidateSite"].rows:
        assert not any("planned" in p for p in row["props"])
    plans = BATCHES["Scenario-PLANS->CandidateSite"].rows
    assert plans and all(r["a"] in _keys("Scenario") and r["props"]["connectors"] for r in plans)


def test_only_daily_estimates_are_loaded():
    assert _keys("DemandEstimate") and all(k.endswith("@all") for k in _keys("DemandEstimate"))


def test_lower_bounds_cite_the_reliability_limit():
    lower = {
        S.estimate_key(e.site_id, e.time_bin)
        for e in DATA.estimates
        if e.kind.value == "lower_bound"
    }
    cites = {
        r["a"]
        for r in BATCHES["DemandEstimate-ASSUMES->Assumption"].rows
        if r["b"] == S.RELIABILITY_ASSUMPTION
    }
    assert lower and cites == lower


def test_every_rule_result_becomes_a_three_valued_verdict():
    verdicts = [r["props"]["verdict"] for r in BATCHES["Decision-EVALUATED->Rule"].rows]
    assert len(verdicts) == sum(len(d.results) for d in FULL.decisions)
    assert set(verdicts) == {"passed", "failed", "unevaluated"}


def test_rules_link_to_what_their_source_ref_names():
    linked = {
        r["a"]: r["b"]
        for name in ("Rule-READS->Dataset", "Rule-CITES->Document", "Rule-ASSUMES->Assumption")
        for r in BATCHES[name].rows
    }
    assert linked == {r.rule_id: r.source_ref for r in DATA.rules if r.source_ref}
    on_fail = {r["key"]: r["props"]["on_fail"] for r in BATCHES["Rule"].rows}
    assert on_fail == {k: v.value for k, v in DATA.rule_on_fail.items()}


def test_references_load_before_anything_points_at_them():
    order = list(BATCHES)
    for ref in ("PlanningArea", "Dataset", "Document", "Assumption"):
        assert order.index(ref) < order.index("CarPark")
    design = ["CarPark", "Station", "Connector", "CandidateSite", "Station-NEAR->CandidateSite",
              "Indicator", "DemandEstimate", "Rule", "Scenario", "Decision", "Allocation",
              "Infeasibility"]
    assert [order.index(x) for x in design] == sorted(order.index(x) for x in design)


class _Result:
    def consume(self) -> None:
        pass


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((query, parameters))
        return _Result()


def test_load_sends_every_row_in_batches(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(L, "BATCH_SIZE", 7)
    session = _Session()
    counts = L.load(DATA, session, extra_label=S.SAMPLE_LABEL)
    sent: dict[str, int] = {}
    for query, params in session.calls:
        assert params is not None and 0 < len(params["rows"]) <= 7
        assert "MERGE" in query
        sent[query] = sent.get(query, 0) + len(params["rows"])
    assert sum(sent.values()) == sum(counts.values())
    assert counts["Decision-EVALUATED->Rule"] == 150
    assert all(f"SET n:{S.SAMPLE_LABEL}" in q for q, _ in session.calls if "MERGE (n:" in q)
