"""The Evidence page (#34): sections carry their layer and invent nothing; the page itself runs
against the sample in Aura (live tests, skipped without NEO4J_URI)."""

import os
from pathlib import Path

import pytest

from optev.app.evidence import LAYER_HELP, QUESTIONS, sections
from optev.graph.retrieve import TEMPLATES

PAGE = Path(__file__).resolve().parents[1] / "optev/app/pages/5_Evidence.py"
ROW = {
    "site_id": "SYN-S-04", "kind": "hdb_car_park", "planning_area": "TM", "total_lots": 210,
    "existing_connectors": 2, "outcome": "accept",
    "rules": [{"rule_id": "R03", "verdict": "passed", "on_fail": "reject", "url": "https://x",
               "source_class": "math_constraint", "evidence": "LTA factsheet"}],
    "demand": [{"estimate_id": "SYN-S-04@all", "arrivals_per_hour": 4.7207,
                "kind": "lower_bound", "based_on": ["i1"],
                "assumptions": [{"assumption_id": "asm-reliable-up-to", "value": 0.93,
                                 "unit": "share of time"}]}],
    "allocated": [{"allocation_id": "base:all:points=12:budget=-", "connectors": 7}],
    "planned": [{"scenario_id": "base", "connectors": 2}],
}


def test_every_question_on_the_page_is_a_retrieval_question():
    assert set(QUESTIONS) == set(TEMPLATES)
    for name, (_, params) in QUESTIONS.items():
        accepted = {p for p, _ in TEMPLATES[name].params}
        required = {p for p, default in TEMPLATES[name].params if default is None}
        assert required <= set(params) <= accepted, name  # optional ones keep their defaults


def test_every_section_is_labelled_with_a_known_layer():
    secs = sections("why_site", [ROW])
    assert [s.layer for s in secs] == ["observed", "rule", "inferred", "recommended", "planned"]
    assert all(s.layer in LAYER_HELP for s in secs)


def test_a_lower_bound_is_shown_as_at_least_and_numbers_pass_through_unchanged():
    [demand] = [s for s in sections("demand_basis", [ROW]) if s.layer == "inferred"]
    assert demand.rows[0]["kind"] == "at least (lower bound)"
    assert demand.rows[0]["arrivals per hour"] == 4.7207
    assert "asm-reliable-up-to = 0.93" in demand.rows[0]["assumes"]


def test_no_rows_gives_no_sections():
    assert sections("why_site", []) == []


live = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="no Neo4j credentials")


@live
def test_the_page_shows_a_rejection_with_its_rule():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    at.radio[0].set_value("Pick a Question").run()
    at.selectbox[0].set_value("why_not_site").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("Rules not passed" in h.value for h in at.subheader)
    assert "Room for Another Point" in at.dataframe[1].value["Rule"].tolist()


@live
def test_the_page_visibly_refuses_a_site_with_no_path(monkeypatch):
    from streamlit.testing.v1 import AppTest

    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setenv(name, "")
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    at.text_input[0].set_value("Why was SYN-S-99 rejected?").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("No evidence" in e.value for e in at.error)


def test_examples_name_sites_that_exist_in_the_data_shown():
    from optev.app.evidence import examples
    from optev.sample import load

    sample_ids = {s.site_id for s in load().sites}
    shown, defaults = examples(real=False)
    assert all(any(i in q for i in sample_ids) for q in shown[:3])
    assert defaults["site_id"] in sample_ids
    real_shown, real_defaults = examples(real=True)
    assert not any("SYN-" in q for q in real_shown) and "SYN-" not in real_defaults["site_id"]


def test_missing_graph_settings_are_named_and_empty_counts_as_missing():
    from optev.app.evidence import missing_graph_settings

    full = {"NEO4J_URI": "neo4j+s://x", "NEO4J_USER": "u", "NEO4J_PASSWORD": "p"}
    assert missing_graph_settings(full) == []
    assert missing_graph_settings({**full, "NEO4J_PASSWORD": ""}) == ["NEO4J_PASSWORD"]
    assert missing_graph_settings({}) == ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]


def test_the_page_explains_a_missing_graph_instead_of_crashing(monkeypatch):
    # As on a deployment whose secrets hold only DATABASE_URL: no traceback, a clear message.
    from streamlit.testing.v1 import AppTest

    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.setenv(name, "")  # set but empty, so load_dotenv cannot refill it
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("not configured" in w.value and "NEO4J_URI" in w.value for w in at.warning)
    assert not at.button  # nothing to ask until the graph is there


def test_the_page_explains_an_unreachable_graph_instead_of_crashing(monkeypatch):
    from neo4j.exceptions import ServiceUnavailable
    from streamlit.testing.v1 import AppTest

    import optev.graph.retrieve as R

    def down(*args, **kwargs):
        raise ServiceUnavailable("Aura is paused")

    monkeypatch.setenv("NEO4J_URI", "neo4j+s://paused.example")
    monkeypatch.setenv("NEO4J_USER", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setattr(R, "retrieve", down)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    at.radio[0].set_value("Pick a Question").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("Could not reach the knowledge graph" in e.value for e in at.error)
