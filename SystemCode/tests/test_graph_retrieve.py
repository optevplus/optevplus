"""Retrieval must be fixed, read-only Cypher over the declared schema. These run without a
database; the live tests at the bottom ask the sample loaded in Aura."""

import os
import re
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

from optev.graph import schema as S
from optev.graph.retrieve import CONSTANTS, TEMPLATES, bind, run

DESIGN = (Path(__file__).resolve().parents[2] / "SYSTEM_DESIGN.md").read_text(encoding="utf-8")
WRITES = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|LOAD\s+CSV|CALL\s+db\.|CALL\s+apoc)\b", re.I
)


def test_every_template_is_read_only():
    for name, t in TEMPLATES.items():
        assert not WRITES.search(t.cypher), name


def test_templates_use_only_declared_labels_and_relationships():
    labels = {n.label for n in S.NODES}
    types = {r.type for r in S.RELATIONSHIPS}
    for name, t in TEMPLATES.items():
        used_labels = set(re.findall(r"\(\w*:(\w+)", t.cypher))
        used_types = {x for group in re.findall(r"\[\w*:([\w|]+)", t.cypher)
                      for x in group.split("|")}
        assert used_labels <= labels, (name, used_labels - labels)
        assert used_types <= types, (name, used_types - types)


def test_parameters_match_what_each_query_uses():
    for name, t in TEMPLATES.items():
        used = set(re.findall(r"\$(\w+)", t.cypher))
        declared = {p for p, _ in t.params}
        assert used <= declared | set(CONSTANTS), (name, used - declared - set(CONSTANTS))
        assert declared <= used, (name, declared - used)


def test_every_question_type_is_named_in_the_design():
    section = DESIGN[DESIGN.index("### 4.5"):DESIGN.index("### 4.6")]
    for name in TEMPLATES:
        assert f"`{name}`" in section, name


def test_bind_fills_defaults_and_rejects_bad_calls():
    _, bound = bind("why_site", {"site_id": "S1"})
    assert bound["scenario_id"] == S.BASELINE and bound["baseline"] == S.BASELINE
    with pytest.raises(ValueError, match="unknown question type"):
        bind("why_maybe", {})
    with pytest.raises(ValueError, match="needs site_id"):
        bind("why_site", {})
    with pytest.raises(ValueError, match="not"):
        bind("rule_sources", {"rule_id": "R01", "site_id": "S1"})


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def data(self) -> list[dict[str, Any]]:
        return self.rows


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows, self.calls = rows, []

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((query, parameters))
        return _Result(self.rows)


def test_run_sends_the_fixed_query_with_parameters_only():
    session = _Session([])
    assert run(session, "why_not_site", site_id="X'; MATCH (n) DETACH DELETE n //") == []
    query, params = session.calls[0]
    assert query == TEMPLATES["why_not_site"].cypher  # the value never enters the text
    assert params["site_id"].startswith("X'")


# Live: the sample loaded by `python -m optev.graph load --sample` ------------------------

load_dotenv()
live = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="no Neo4j credentials")


@live
def test_a_rejected_site_names_the_failed_rule_and_its_document():
    from optev.graph.retrieve import retrieve

    [row] = retrieve("why_not_site", site_id="SYN-S-13")
    assert row["outcome"] == "reject"
    [rule] = row["rules"]
    assert (rule["rule_id"], rule["verdict"]) == ("R03", "failed")
    assert rule["evidence_id"] == "doc-lta-ev-factsheet-2021" and rule["url"]


@live
def test_a_lower_bound_cites_the_reliability_limit():
    from optev.graph.retrieve import retrieve

    [row] = retrieve("demand_basis", site_id="SYN-S-04")
    [est] = row["demand"]
    assert est["kind"] == "lower_bound"
    assert S.RELIABILITY_ASSUMPTION in {a["assumption_id"] for a in est["assumptions"]}
    assert est["based_on"] == [i["indicator_id"] for i in row["indicators"]]


@live
def test_every_question_answers_on_the_sample_and_unknowns_give_no_evidence():
    from optev.graph.retrieve import retrieve

    asks = {
        "why_site": {"site_id": "SYN-S-04"},
        "why_not_site": {"site_id": "SYN-S-13"},
        "demand_basis": {"site_id": "SYN-S-04"},
        "compare_sites": {"site_a": "SYN-S-13", "site_b": "SYN-S-04"},
        "rule_sources": {"rule_id": "R03"},
        "infeasible_request": {"scenario_id": "base", "planning_area": "PR"},
        "area_saturation": {},
        "assumptions_used": {"site_id": "SYN-S-04"},
    }
    assert set(asks) == set(TEMPLATES)
    for name, params in asks.items():
        assert retrieve(name, **params), name
    assert [r["site_id"] for r in retrieve("compare_sites", **asks["compare_sites"])] == [
        "SYN-S-13", "SYN-S-04"]
    assert retrieve("why_site", site_id="NO-SUCH-SITE") == []
    assert retrieve("rule_sources", rule_id="R99") == []
