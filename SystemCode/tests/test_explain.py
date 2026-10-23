"""The explanation layer answers only from retrieved evidence, or refuses (#27). Unit tests
use a fake model and a fake retriever; the live ones ask the sample loaded in Aura."""

import os
from typing import Any

import httpx
import pytest
from dotenv import dotenv_values

from optev.evaluation.explain_eval import questions, score
from optev.graph import llm as L
from optev.graph.explain import check, classify, explain

ROWS: list[dict[str, Any]] = [{
    "site_id": "SYN-S-13", "planning_area": "TM", "total_lots": 24, "existing_connectors": 3,
    "decision_id": "observed:SYN-S-13", "outcome": "reject",
    "rules": [{"rule_id": "R03", "verdict": "failed", "detail": "room 0", "on_fail": "reject",
               "condition": "Existing plus one new point stays within 15% of car lots",
               "evidence_id": "doc-lta-ev-factsheet-2021", "utilisation": 0.9479}],
}]
GOOD = ("SYN-S-13 was rejected [observed:SYN-S-13]: rule R03 failed [R03], since 3 points on "
        "24 lots leave room 0 within 15% [doc-lta-ev-factsheet-2021].")


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies, self.calls = list(replies), 0

    def __call__(self, system: str, user: str) -> str:
        self.calls += 1
        return self.replies[min(self.calls, len(self.replies)) - 1]


def fake_retriever(rows: list[dict[str, Any]]):
    def retriever(question_type: str, **params: str) -> list[dict[str, Any]]:
        return rows
    return retriever


def test_every_evaluation_question_is_classified_as_its_answer_key_says():
    for q in questions():
        expected = (q["type"], q["params"]) if "type" in q else None
        assert classify(q["question"]) == expected, q["question"]


def test_check_accepts_numbers_and_ids_from_the_evidence():
    problems, cited = check(GOOD, ROWS)
    assert problems == []
    assert cited == ["observed:SYN-S-13", "R03", "doc-lta-ev-factsheet-2021"]
    assert check("Utilisation was 94.79% [SYN-S-13].", ROWS)[0] == []  # a share as a percent
    assert check("Utilisation was 95% [SYN-S-13].", ROWS)[0] == []  # rounded as written


def test_check_rejects_invented_numbers_unknown_ids_and_missing_citations():
    assert check("It has 120 lots [SYN-S-13].", ROWS)[0] == [
        "the number 120 is not in the evidence"]
    assert "not in the evidence" in check("Rejected [R99].", ROWS)[0][0]
    assert check("It was rejected.", ROWS)[0] == [
        "cites nothing; every fact needs an [id] from the evidence"]


def test_a_grounded_answer_is_returned_after_one_draft():
    model = FakeLLM(GOOD)
    a = explain("Why was SYN-S-13 rejected?", llm=model, retriever=fake_retriever(ROWS))
    assert not a.refused and a.text == GOOD and model.calls == 1
    assert a.question_type == "why_not_site" and a.evidence == ROWS


def test_a_bad_draft_is_retried_once_then_fixed():
    model = FakeLLM("It has 120 lots [SYN-S-13].", GOOD)
    a = explain("Why was SYN-S-13 rejected?", llm=model, retriever=fake_retriever(ROWS))
    assert not a.refused and model.calls == 2


def test_an_answer_that_fails_twice_is_refused_with_the_evidence_kept():
    model = FakeLLM("It has 120 lots [SYN-S-13].")
    a = explain("Why was SYN-S-13 rejected?", llm=model, retriever=fake_retriever(ROWS))
    assert a.refused and model.calls == 2
    assert a.evidence == ROWS and a.problems == ["the number 120 is not in the evidence"]


def test_no_evidence_is_refused_without_asking_the_model():
    model = FakeLLM(GOOD)
    a = explain("Why was SYN-S-99 rejected?", llm=model, retriever=fake_retriever([]))
    assert a.refused and model.calls == 0 and "No evidence" in a.text


def test_out_of_scope_is_refused_without_retrieving_or_asking():
    model = FakeLLM(GOOD)

    def never(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise AssertionError("retrieved for an out-of-scope question")

    a = explain("Write me a poem about charging stations.", llm=model, retriever=never)
    assert a.refused and a.question_type is None and model.calls == 0


def test_the_model_comes_from_settings_and_says_what_is_missing(monkeypatch):
    monkeypatch.setattr(L, "_ENV", L._ENV.with_name("no-such.env"))
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(L.LLMNotConfigured, match="LLM_PROVIDER, LLM_API_KEY, LLM_MODEL"):
        L.from_env()
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    sent: dict[str, Any] = {}

    def fake_post(url: str, **kw: Any) -> httpx.Response:
        sent.update(url=url, **kw)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(L.httpx, "post", fake_post)
    assert L.from_env()("sys", "user") == "hi"
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    assert sent["json"]["model"] == "m" and sent["json"]["temperature"] == 0
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(L.LLMNotConfigured, match="unknown"):
        L.from_env()


# Live ---------------------------------------------------------------------------------

# Only NEO4J_* from .env: loading the whole file would also set DATABASE_URL and switch on
# the Neon live tests, which run only when asked (`uv run --env-file .env pytest`).
for _key, _value in dotenv_values().items():
    if _key.startswith("NEO4J_") and _value:
        os.environ.setdefault(_key, _value)
live = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="no Neo4j credentials")


@live
def test_classification_and_retrieval_score_full_marks_on_the_sample():
    result = score()
    assert result["classification"] == 1.0
    assert result["evidence_recall"] == 1.0


@live
def test_a_site_with_no_recorded_path_is_visibly_refused():
    # The #27 done-check: no graph path, no answer, and the model is never asked.
    model = FakeLLM(GOOD)
    a = explain("Why was SYN-S-99 rejected?", llm=model)
    assert a.refused and model.calls == 0 and a.evidence == []


def test_a_citation_with_a_field_name_or_quotes_is_the_same_id():
    rows = [{"site_id": "hdb:A76", "decision_id": "observed:hdb:A76",
             "rules": [{"rule_id": "R03"}]}]
    problems, cited = check('Rejected [rule_id: "R03"] at [\'hdb:A76\'] [observed:hdb:A76].', rows)
    assert problems == [] and cited == ["R03", "hdb:A76", "observed:hdb:A76"]
    assert "not in the evidence" in check("Rejected [rule_id: R99].", rows)[0][0]


def test_the_scorer_accepts_the_same_fact_in_other_words():
    from optev.evaluation.explain_eval import REAL, mentions, questions

    assert mentions("demand is at least 4.7 an hour", "lower bound")
    assert mentions("busy 86.87% of the time", "0.8687")
    assert mentions("a project assumption", "project_assumption")
    assert not mentions("it was accepted", "reject")
    for q in questions(REAL):  # the real answer key classifies as written
        expected = (q["type"], q["params"]) if "type" in q else None
        assert classify(q["question"]) == expected, q["question"]
