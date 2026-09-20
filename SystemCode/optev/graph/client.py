"""Neo4j connection. Kept trivial so day-one verification has something to call."""

import os

from neo4j import GraphDatabase


def _driver():
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    return GraphDatabase.driver(uri, auth=auth)


def ping() -> str:
    """Round-trip the graph. Raises if credentials or connectivity are wrong."""
    with _driver() as d, d.session() as s:
        return s.run("RETURN 'ok' AS status").single()["status"]


def heartbeat() -> None:
    """A write, so Aura Free does not auto-pause. Called weekly by CI."""
    with _driver() as d, d.session() as s:
        s.run("MERGE (h:Heartbeat {id: 1}) SET h.last_seen = datetime()")
