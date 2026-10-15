"""Turn the declared schema into Cypher and apply it. Every statement is idempotent, so
applying twice is the same as applying once."""

from typing import Protocol

from .schema import NODES, SOURCE_CLASSES


class _Session(Protocol):
    def run(self, query: str, parameters: dict[str, object] | None = None) -> object: ...


INDEXES: tuple[str, ...] = (
    "CREATE INDEX decision_outcome IF NOT EXISTS FOR (d:Decision) ON (d.outcome)",
    "CREATE INDEX rule_source IF NOT EXISTS FOR (r:Rule) ON (r.source)",
    "CREATE INDEX site_kind IF NOT EXISTS FOR (s:CandidateSite) ON (s.kind)",
)

SEED_SOURCE_CLASSES = (
    "UNWIND $rows AS row MERGE (c:SourceClass {code: row.code}) SET c.meaning = row.meaning"
)


def constraints() -> list[str]:
    """One uniqueness constraint per label, on its key. This is what makes MERGE safe."""
    return [
        f"CREATE CONSTRAINT {n.label.lower()}_key IF NOT EXISTS "
        f"FOR (n:{n.label}) REQUIRE n.{n.key} IS UNIQUE"
        for n in NODES
    ]


def statements() -> list[str]:
    return [*constraints(), *INDEXES]


def seed_rows() -> list[dict[str, str]]:
    return [{"code": src.value, "meaning": text} for src, text in SOURCE_CLASSES.items()]


def apply_schema(session: _Session) -> int:
    """Create constraints and indexes, then seed the fixed SourceClass nodes."""
    for stmt in statements():
        session.run(stmt)
    session.run(SEED_SOURCE_CLASSES, {"rows": seed_rows()})
    return len(statements())
