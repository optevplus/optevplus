"""Against a real Neo4j. Skipped unless NEO4J_URI is set, in the environment or .env."""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="no Neo4j credentials")


def test_apply_schema_twice_is_the_same_as_once():
    from optev.graph import apply_schema, driver
    from optev.graph.schema import NODES, SOURCE_CLASSES

    with driver() as d, d.session() as s:
        apply_schema(s)
        apply_schema(s)
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
        sources = s.run("MATCH (c:SourceClass) RETURN count(c) AS n").single()

    assert {f"{n.label.lower()}_key" for n in NODES} <= names
    assert sources is not None and sources["n"] == len(SOURCE_CLASSES)


def test_loading_the_sample_twice_is_the_same_as_once():
    # Leaves the sample loaded on purpose: the app and retrieval build against it until real
    # data lands. `python -m optev.graph clear --sample` removes it.
    from optev.graph import apply_schema, driver
    from optev.graph.load import load
    from optev.graph.schema import SAMPLE_LABEL
    from optev.sample import load as sample

    count = (
        f"MATCH (n:{SAMPLE_LABEL}) OPTIONAL MATCH (n)-[r]->() "
        "RETURN count(DISTINCT n) AS nodes, count(r) AS rels"
    )
    with driver() as d, d.session() as s:
        apply_schema(s)
        sent = load(sample(), s, extra_label=SAMPLE_LABEL)
        first = s.run(count).single()
        load(sample(), s, extra_label=SAMPLE_LABEL)
        second = s.run(count).single()

    assert first is not None and second is not None
    assert (first["nodes"], first["rels"]) == (second["nodes"], second["rels"])
    nodes = sum(n for name, n in sent.items() if "->" not in name)
    assert first["nodes"] == nodes
