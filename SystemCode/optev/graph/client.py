"""Neo4j connection. Kept trivial so day-one verification has something to call."""

import os

from neo4j import Driver, GraphDatabase


def driver() -> Driver:
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    return GraphDatabase.driver(uri, auth=auth)


def ping() -> str:
    """Round-trip the graph. Raises if credentials or connectivity are wrong."""
    with driver() as d, d.session() as s:
        record = s.run("RETURN 'ok' AS status").single()
        if record is None:
            raise RuntimeError("Neo4j returned no row for the ping query")
        return str(record["status"])


def heartbeat() -> None:
    """A write, so Aura Free does not auto-pause. Called weekly by CI."""
    with driver() as d, d.session() as s:
        s.run("MERGE (h:Heartbeat {id: 1}) SET h.last_seen = datetime()")
