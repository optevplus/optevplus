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

## Checkpoint · 23 Oct 2026 (model connected)
- **Model:** OpenAI `gpt-4o-mini` through `openai_compatible` (GitHub Models was retired on
  30 Jul 2026, so it cannot be used).
- **Real-data answer key:** `evaluation/explain_questions_real.toml`, 20 questions about real
  sites from the first Neon run (rejected by R03/R04, conditional by R02/R06, deferred, the two
  sites with 3 points, demand of a busy and a no-charger site, comparisons, rule sources,
  assumptions, 3 refusals). `python -m optev.evaluation.explain_eval --llm --real`.
- **Results, real key (two runs, identical):** classification 1.000, evidence recall 1.000,
  accuracy 0.950, answered 17 of 17, citation rate 1.000, unsupported claims 0,
  Precision@k ≈ 0.2 (answers cite the site and decision before the rule and document).
- **Fixed on the way:** the system prompt showed real ids as citation examples and the model
  copied them into unrelated answers (the check caught it and refused); the prompt now
  describes the format without ids. The checker reads `rule_id: "R03"` as `R03`. The scorer
  accepts the same fact in other words ("at least" = lower bound, a share as a percentage).
- **Sample key:** 0.75, because the real load shares rule, scenario and plan ids with the sample
  graph and replaced parts of it. Report the real key.
