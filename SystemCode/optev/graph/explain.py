"""Grounded answers to a planner's question (#27, SYSTEM_DESIGN.md §4.5).

    classify → (out of scope? refuse) → retrieve → (nothing? refuse) → write → check
                                                            ↑ retry once ──┘   ↓
                                                                    (still failing? refuse)

Classification is rules, not the model: the question type and its ids come from fixed
patterns, so the model can never choose what evidence it sees. The model only rewords the
retrieved rows. Its answer is then checked: every number must appear in the evidence, every
[citation] must name a retrieved id, and at least one citation must be present. An answer
that fails twice is refused, with the evidence still returned for the planner to read.
"""

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .llm import LLM
from .retrieve import TEMPLATES, retrieve

Retriever = Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class Answer:
    text: str
    evidence: list[dict[str, Any]]
    refused: bool
    question_type: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    cited: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    """Why the last draft failed the check; empty for a grounded answer."""


# Classification -------------------------------------------------------------------------

SITE = re.compile(r"\b(?:SYN-S-\d+|(?:hdb|ura|mall|hawker|cc|petrol):[A-Za-z0-9_-]+)")
RULE = re.compile(r"\bR\d{2}\b")
AREA = re.compile(r"\b(?:in|for|area)\s+([A-Z]{2,3})\b")
SCENARIO = re.compile(r"\b(low|base|high)\b(?:\s+(?:scenario|growth|case))?", re.I)
POINTS = re.compile(r"\b\d+\s+(?:new\s+)?(?:charging\s+)?points?\b", re.I)


def _has(text: str, *patterns: str) -> bool:
    """Each pattern is matched from a word start, so "assum" finds "assumptions"."""
    return any(re.search(rf"\b{p}", text, re.I) for p in patterns)


def classify(question: str) -> tuple[str, dict[str, str]] | None:
    """The question type and parameters, or None when it is out of scope."""
    sites = list(dict.fromkeys(SITE.findall(question)))
    rules = RULE.findall(question)
    scenario = SCENARIO.search(question)
    scen = {"scenario_id": scenario.group(1).lower()} if scenario else {}

    if len(sites) >= 2:
        return "compare_sites", {"site_a": sites[0], "site_b": sites[1], **scen}
    if rules and not sites:
        return "rule_sources", {"rule_id": rules[0]}
    if sites:
        site = {"site_id": sites[0]}
        if _has(question, "assum"):
            return "assumptions_used", {**site, **scen}
        if _has(question, "demand", "arrival", "estimate", "how busy", "utilis", "lower bound"):
            return "demand_basis", site
        if _has(question, r"not\b", r"\w+n't\b", "reject", "exclud", "fail", "defer",
                "conditional", r"why\s+no\b"):
            return "why_not_site", {**site, **scen}
        return "why_site", {**site, **scen}
    if POINTS.search(question) or _has(question, "infeasib", "impossible", "can't", "cannot"):
        area = AREA.search(question)
        return "infeasible_request", {
            "scenario_id": scen.get("scenario_id", "base"),
            **({"planning_area": area.group(1)} if area else {}),
        }
    if _has(question, "saturat", "busiest", "near capacity", "full", "running out"):
        return "area_saturation", {}
    return None


# The check ------------------------------------------------------------------------------

ID_KEYS = re.compile(
    r"(^|_)id$|^planning_area$|^affected_areas$|^based_on$|^code$|^source_ref$|_ids$")
NUMBER = re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?%?")
CITATION = re.compile(r"\[([^\[\]]+)\]")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+)?")


def _walk(value: Any, key: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        yield key + "#len", len(value)
        for v in value:
            yield from _walk(v, key)
    else:
        yield key, value


def evidence_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {str(v) for k, v in _walk(rows) if v is not None and ID_KEYS.search(k)}


def evidence_numbers(rows: list[dict[str, Any]]) -> list[float]:
    """Every number in the evidence: values, list lengths, and numbers written in text."""
    found: list[float] = []
    for _, v in _walk(rows):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float):
            found.append(float(v))
        elif isinstance(v, str):
            numbers = NUMBER.findall(DATE.sub("", v))
            found += [float(n.rstrip("%").replace(",", "")) for n in numbers]
    return found


def _supported(written: str, known: list[float]) -> bool:
    pct = written.endswith("%")
    digits = written.rstrip("%").replace(",", "")
    value = float(digits)
    tol = 0.5 * 10 ** -(len(digits.split(".")[1]) if "." in digits else 0)
    candidates = [k * 100 for k in known] + known if pct else known + [k * 100 for k in known]
    return any(abs(value - k) <= tol + 1e-9 for k in candidates)


def check(text: str, rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(problems, citations). An answer passes when problems is empty."""
    ids = evidence_ids(rows)
    cited = [c.strip() for group in CITATION.findall(text) for c in group.split(",")]
    problems = [f"cites {c!r}, which is not in the evidence" for c in cited if c not in ids]
    if not cited:
        problems.append("cites nothing; every fact needs an [id] from the evidence")
    prose = CITATION.sub(" ", text)
    for known_id in sorted(ids, key=len, reverse=True):  # ids like SYN-S-13 hold digits
        prose = prose.replace(known_id, " ")
    known = evidence_numbers(rows)
    for n in NUMBER.findall(DATE.sub(" ", prose)):
        if not _supported(n, known):
            problems.append(f"the number {n} is not in the evidence")
    return problems, cited


# The flow -------------------------------------------------------------------------------

SYSTEM = """You explain decisions of OptEV+, a planner for Singapore's public EV charging points.
Answer ONLY from the EVIDENCE (JSON rows retrieved from the knowledge graph).
- Cite every fact with the id it comes from in square brackets, e.g. [R03] or
  [doc-lta-ev-factsheet-2021] or [SYN-S-13@all]. Use only ids that appear in the evidence.
- Copy numbers exactly as they appear in the evidence. A share like 0.9479 may be written as
  94.79%. Do not compute new numbers.
- verdict "unevaluated" means the rule could not be checked, not that it failed.
- kind "lower_bound" means demand is at least this value.
- If the evidence does not answer the question, say "The evidence does not say."
Write 2 to 5 plain sentences for a government planner."""

REFUSE_SCOPE = (
    "I can only answer questions about the sites, rules, demand, plans and assumptions in "
    "the OptEV+ knowledge graph. Try: why was SYN-S-13 rejected?"
)


class State(TypedDict, total=False):
    question: str
    question_type: str | None
    params: dict[str, str]
    evidence: list[dict[str, Any]]
    draft: str
    problems: list[str]
    cited: list[str]
    attempts: int
    answer: Answer


def build(llm: LLM, retriever: Retriever = retrieve) -> Any:
    """The LangGraph flow. Separate from explain() so tests can pass a fake model."""

    def classify_node(s: State) -> State:
        found = classify(s["question"])
        return {"question_type": found[0] if found else None,
                "params": found[1] if found else {}}

    def retrieve_node(s: State) -> State:
        assert s["question_type"] is not None
        return {"evidence": retriever(s["question_type"], **s["params"]), "attempts": 0}

    def write_node(s: State) -> State:
        user = f"QUESTION: {s['question']}\n\nEVIDENCE:\n{json.dumps(s['evidence'], default=str)}"
        if s.get("problems"):
            user += "\n\nYour previous answer failed these checks; fix them:\n- " + "\n- ".join(
                s["problems"])
        draft = llm(SYSTEM, user)
        problems, cited = check(draft, s["evidence"])
        return {"draft": draft, "problems": problems, "cited": cited,
                "attempts": s.get("attempts", 0) + 1}

    def refuse_scope(s: State) -> State:
        return {"answer": Answer(REFUSE_SCOPE, [], True)}

    def refuse_empty(s: State) -> State:
        what = ", ".join(f"{k}={v}" for k, v in s["params"].items()) or "this question"
        return {"answer": Answer(
            f"No evidence in the knowledge graph for {what}. Nothing is recorded, so I "
            "won't guess.", [], True, s["question_type"], s["params"])}

    def refuse_unsupported(s: State) -> State:
        return {"answer": Answer(
            "I couldn't write an answer the evidence fully supports, so here is the evidence "
            "itself instead.", s["evidence"], True, s["question_type"], s["params"],
            s.get("cited", []), s.get("problems", []))}

    def done(s: State) -> State:
        return {"answer": Answer(s["draft"], s["evidence"], False, s["question_type"],
                                 s["params"], s["cited"], [])}

    g: Any = StateGraph(State)  # LangGraph's overloads reject plain State -> State nodes
    g.add_node("classify", classify_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("write", write_node)
    g.add_node("refuse_scope", refuse_scope)
    g.add_node("refuse_empty", refuse_empty)
    g.add_node("refuse_unsupported", refuse_unsupported)
    g.add_node("done", done)
    g.set_entry_point("classify")
    g.add_conditional_edges("classify", lambda s: "retrieve" if s["question_type"]
                            else "refuse_scope")
    g.add_conditional_edges("retrieve", lambda s: "write" if s["evidence"] else "refuse_empty")
    g.add_conditional_edges("write", lambda s: "done" if not s["problems"] else (
        "write" if s["attempts"] < 2 else "refuse_unsupported"))
    for end in ("refuse_scope", "refuse_empty", "refuse_unsupported", "done"):
        g.add_edge(end, END)
    return g.compile()


def explain(question: str, llm: LLM | None = None,
            retriever: Retriever = retrieve) -> Answer:
    """Design §4.5 entry point. Uses the model from SystemCode/.env unless one is given."""
    if llm is None:
        from .llm import from_env

        llm = from_env()
    result = build(llm, retriever).invoke({"question": question})
    answer: Answer = result["answer"]
    return answer


__all__ = ["TEMPLATES", "Answer", "build", "check", "classify", "explain"]
