# 010 · Explanation layer (#27)

**Owner:** Ghanashyam  ·  **Status:** built, in review (model key pending)  ·  **Branch:** `ghanashyam/27-explanation`

## Design section

> **Explanation (#27).** LangGraph flow: classify the question → refuse if out of scope →
> retrieve → the LLM answers **only** from the retrieved evidence → every number in the answer
> must appear in the evidence → retry once, otherwise refuse. — SYSTEM_DESIGN.md §4.5

Issue #27: done when a site with no recorded path visibly produces a refusal.

## Problem
Retrieval (#26) returns evidence rows; a planner needs a sentence, and the proposal promises
that sentence never claims more than the graph holds.

## Approach
- `graph/llm.py`: `LLM = (system, user) -> text`; `from_env()` builds DeepSeek, Gemini,
  Anthropic or any OpenAI-compatible endpoint from `.env`; temperature 0.
- `graph/explain.py`: LangGraph `StateGraph` classify → retrieve → write → check, with three
  refusal exits (out of scope, no evidence, failed twice). `classify()` is fixed patterns, so
  the model never picks its evidence. `check()` verifies numbers and `[citations]`.
- `evaluation/explain_questions.toml`: 20 questions with type, params, ids a correct answer
  rests on, facts it must state, and 3 that must be refused. `explain_eval.py` scores them.

## Verification
- `uv run pytest tests/test_explain.py`: 9 unit tests with a fake model and fake retriever,
  2 live (scores on Aura; the no-path refusal).
- `uv run python -m optev.evaluation.explain_eval` (no model): classification 1.000, evidence
  recall 1.000, mean evidence size 7.9 ids.
- `uv run python -m optev.graph explain "Why was SYN-S-99 rejected?"` → refusal.

## Checkpoint · 19 Oct 2026
- **Works:** the full flow on Aura with fake models: a grounded answer passes; a draft that
  invents "120 car lots" fails twice and is refused with the evidence kept; an unknown site and
  an off-topic question are refused without calling the model.
- **Decided:** classification by patterns, not the model (deterministic, testable, cannot
  widen what is retrieved). Precision@k is measured on the answer's citations: the order of
  ids inside a retrieved row carries no meaning, so ranking them would measure nothing.
- **Waiting on:** a model key. Then run `explain_eval --llm` for accuracy, citation rate,
  unsupported claims and Precision@k, and record them for the report (#43).
