"""Stage 5 evaluation (SYSTEM_DESIGN.md §6): the 20 questions in explain_questions.toml.

Without a model it scores what needs no model: classification and retrieval. With one it also
scores the answers. Run: `uv run python -m optev.evaluation.explain_eval [--llm]`.

- classification   share of questions mapped to the right type and parameters
- evidence recall  share of answerable questions whose evidence holds every must_cite id
- evidence size    mean number of distinct ids retrieved per answerable question (focus)
- precision@k      (model) for each answer, the share of its first k citations that are
                   expected ids, k = number of expected ids
- accuracy         share answered correctly: every must_mention present, or refused when it
                   should be and not otherwise
- citation rate    share of given answers that cite only retrieved ids, at least one
- unsupported      claims that failed the number or citation check in a given answer
"""

import sys
import tomllib
from pathlib import Path
from typing import Any

from optev.graph.explain import Answer, check, classify, evidence_ids, explain
from optev.graph.llm import LLM
from optev.graph.retrieve import retrieve

QUESTIONS = Path(__file__).with_name("explain_questions.toml")


def questions() -> list[dict[str, Any]]:
    return list(tomllib.loads(QUESTIONS.read_text(encoding="utf-8"))["q"])


def score(llm: LLM | None = None, retriever: Any = retrieve) -> dict[str, float]:
    qs = questions()
    right_class, recall, sizes, p_at_k, answered = 0, [], [], [], 0
    accurate, cited_ok, unsupported = 0, 0, 0
    for q in qs:
        found = classify(q["question"])
        expected = (q["type"], q["params"]) if "type" in q else None
        right_class += found == expected
        if q["must_cite"]:
            rows = retriever(q["type"], **q["params"])
            ids = evidence_ids(rows)
            recall.append(set(q["must_cite"]) <= ids)
            sizes.append(len(ids))
        if llm is None:
            continue
        a: Answer = explain(q["question"], llm=llm, retriever=retriever)
        if q.get("refuse"):
            accurate += a.refused
            continue
        if not a.refused:
            answered += 1
            problems, cited = check(a.text, a.evidence)
            cited_ok += not problems
            want = set(q["must_cite"])
            if want:
                top = list(dict.fromkeys(cited))[: len(want)]
                p_at_k.append(len(want & set(top)) / len(want))
            unsupported += len(problems)
            accurate += all(m.lower() in a.text.lower() for m in q["must_mention"])
    n = len(qs)
    out = {
        "questions": n,
        "classification": right_class / n,
        "evidence_recall": sum(recall) / len(recall),
        "evidence_size": sum(sizes) / len(sizes),
    }
    if llm is not None:
        out |= {"accuracy": accurate / n, "answered": answered,
                "citation_rate": cited_ok / answered if answered else 0.0,
                "precision_at_k": sum(p_at_k) / len(p_at_k) if p_at_k else 0.0,
                "unsupported_claims": unsupported}
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    model = None
    if "--llm" in sys.argv:
        from optev.graph.llm import from_env

        model = from_env()
    for name, value in score(model).items():
        print(f"{name:20s} {value:.3f}" if isinstance(value, float) else f"{name:20s} {value}")
