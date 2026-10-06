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
