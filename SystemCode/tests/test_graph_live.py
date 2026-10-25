"""Against a real Neo4j. Skipped unless NEO4J_URI is set, in the environment or .env."""

import os
from dataclasses import replace

import pytest

# These tests write the sample into the graph. The sample's plan has the same id as the real
# 12-point plan (base:all:points=12:budget=-), so running them against the deployed Aura
# replaces the real plan's links until the graph is reloaded. Run them only when asked.
pytestmark = [
    pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="no Neo4j credentials"),
    pytest.mark.skipif(os.getenv("OPTEV_GRAPH_TESTS_MAY_WRITE") != "1",
                       reason="writes to the graph; set OPTEV_GRAPH_TESTS_MAY_WRITE=1 to run"),
]


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


def test_a_reload_drops_links_the_new_data_no_longer_has():
    from optev.graph import apply_schema, driver
    from optev.graph.load import load
    from optev.graph.schema import SAMPLE_LABEL
    from optev.sample import load as sample

    data = sample()
    fewer = data.allocation.model_copy(update={"items": data.allocation.items[:2],
                                               "requested_connectors": None})
    count = ("MATCH (:Allocation)-[x:ALLOCATES]->(:CandidateSite {site_id: $site}) "
             "RETURN count(x) AS n")
    dropped = data.allocation.items[-1].site_id
    with driver() as d, d.session() as s:
        apply_schema(s)
        try:
            load(data, s, extra_label=SAMPLE_LABEL)
            # Same allocation node (same request), fewer items: the dropped site's link goes.
            trimmed = replace(data, allocation=fewer.model_copy(
                update={"requested_connectors": data.allocation.requested_connectors}))
            load(trimmed, s, extra_label=SAMPLE_LABEL)
            after = s.run(count, site=dropped).single()
        finally:
            load(data, s, extra_label=SAMPLE_LABEL)  # leave the full sample in place
    assert after is not None and after["n"] == 0
