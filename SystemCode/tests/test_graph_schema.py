"""The graph schema must stay in step with the frozen contracts. These run without a
database; tests/test_graph_live.py checks a real one when credentials are present."""

import optev.contracts as contracts
from optev.contracts import RuleResult, RuleSource
from optev.graph import schema
from optev.graph.ddl import SEED_SOURCE_CLASSES, apply_schema, constraints, statements

COORD_FIELDS = {"lat", "lon"}  # flattened from the contract's Coordinate


def test_labels_and_keys_are_unique():
    labels = [n.label for n in schema.NODES]
    assert len(labels) == len(set(labels))


def test_every_relationship_connects_declared_labels():
    labels = {n.label for n in schema.NODES}
    for rel in schema.RELATIONSHIPS:
        assert rel.start in labels, rel
        assert rel.end in labels, rel


def test_node_properties_exist_on_their_contract():
    for n in schema.NODES:
        if not n.contract:
            continue
        fields = set(getattr(contracts, n.contract).model_fields)
        assert set(n.properties) - COORD_FIELDS <= fields, n.label
        assert n.key in fields or n.key in schema.DERIVED_KEYS, n.label


def test_source_classes_cover_every_rule_source():
    # If the contract gains a source class, the graph must learn what it means.
    assert set(schema.SOURCE_CLASSES) == set(RuleSource)


def test_planned_capacity_is_a_relationship_not_a_site_property():
    for label in ("CandidateSite", "Station", "Connector"):
        assert "planned" not in " ".join(schema.node(label).properties)
    plans = [r for r in schema.RELATIONSHIPS if r.type == "PLANS"]
    assert [(r.start, r.end) for r in plans] == [("Scenario", "CandidateSite")]


def test_verdict_keeps_unevaluated_distinct_from_failed():
    assert schema.verdict(RuleResult(rule_id="r", passed=True)) == "passed"
    assert schema.verdict(RuleResult(rule_id="r", passed=False)) == "failed"
    assert schema.verdict(RuleResult(rule_id="r", passed=None)) == "unevaluated"


def test_keys_are_deterministic_and_scenario_aware():
    assert schema.decision_key("S1", None) == schema.decision_key("S1", None) == "observed:S1"
    assert schema.decision_key("S1", "base") != schema.decision_key("S1", None)
    assert schema.allocation_key("base", 1_000_000.0) == "base:budget=1e+06"
    assert schema.indicator_key("S1", "a", "b") != schema.indicator_key("S1", "a", "c")


def test_one_idempotent_constraint_per_label():
    assert len(constraints()) == len(schema.NODES)
    assert all("IF NOT EXISTS" in s for s in statements())


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def run(self, query: str, parameters: dict[str, object] | None = None) -> None:
        self.calls.append((query, parameters))


def test_apply_schema_runs_everything_then_seeds_source_classes():
    session = _RecordingSession()
    assert apply_schema(session) == len(statements())
    queries = [q for q, _ in session.calls]
    assert queries[:-1] == statements()
    assert queries[-1] == SEED_SOURCE_CLASSES
    seeded = session.calls[-1][1]
    assert seeded is not None
    assert {row["code"] for row in seeded["rows"]} == {s.value for s in RuleSource}  # type: ignore[attr-defined]
