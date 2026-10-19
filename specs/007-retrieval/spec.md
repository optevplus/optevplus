# 007 · Retrieval templates (#26)

**Owner:** Ghanashyam  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/26-retrieval`

## Design section

> **Retrieval (#26).** Fixed, parameterised Cypher per question type: `why_site`,
> `why_not_site`, `demand_basis`, `compare_sites`, `rule_sources`, `infeasible_request`. Never
> generated Cypher. An empty result is returned as "no evidence", never filled in.
> — SYSTEM_DESIGN.md §4.5, with `retrieve(question_type: str, **params: str) -> list[dict[str, object]]`

## Problem
The graph holds the evidence (#25), but nothing can ask it a planner's question. The
explanation layer (#27) needs, for each kind of question, one fixed query that returns
everything needed to answer it and nothing invented.

## Contracts touched
None. Reads the graph as loaded by `optev/graph/load.py`; returns plain rows.

## Approach
1. `optev/graph/retrieve.py`: a `TEMPLATES` table, one entry per question type with its
   parameters, its fixed Cypher and one line on what it answers. `retrieve()` checks the type
   and parameters, runs the query with parameters (never string-built), returns rows.
   `run(session, question_type, **params)` does the work, so tests can pass a session.
2. What each returns (every row names the node it came from, so answers can cite it):

   | Type | Params | Evidence returned |
   |---|---|---|
   | `why_site` | `site_id`, `scenario_id` | Outcome; every rule with verdict, detail, source class and the document, dataset or assumption behind it; demand estimate; points allocated |
   | `why_not_site` | `site_id`, `scenario_id` | Outcome; only failed and unevaluated rules, with `on_fail` and evidence; if the site was accepted, says so |
   | `demand_basis` | `site_id` | Estimate, point or lower bound; utilisation, saturation and coverage it came from; assumptions; source dataset |
   | `compare_sites` | `site_a`, `site_b`, `scenario_id` | The same facts for both, side by side |
   | `rule_sources` | `rule_id` | Condition, source class, cited evidence, how many sites it failed |
   | `infeasible_request` | `scenario_id`, `planning_area` | Requested, max feasible, binding constraints, affected areas |

   `scenario_id` defaults to `observed`; `planning_area` to `all`.
3. Read-only by construction: a test fails if any template contains CREATE, MERGE, SET or
   DELETE, or uses a label or relationship not declared in `schema.py`.

## Verification
- Unit: every template's parameters are exactly the ones its Cypher uses; read-only; only
  schema labels and relationships; an unknown type or missing parameter raises.
- Live (skips without `NEO4J_URI`), on the loaded sample: `why_not_site SYN-S-13` returns R03
  failed with the LTA factsheet; `demand_basis` on the saturated site returns a lower bound
  citing `asm-reliable-up-to`; an unknown site returns `[]`.
- `python -m optev.graph ask why_not_site site_id=SYN-S-13` prints the rows.

## Open questions
1. ~~Add `area_saturation` and `assumptions_used`?~~ Done, design 1.5: the issue asks for both.
2. Precision@k needs an answer key: for each of the 20 evaluation questions, the evidence
   nodes a correct answer must cite. Written in #27 with the questions.
3. `why_site` lists allocations by the scenario they sit `UNDER`. An allocation for the
   `observed` baseline has no Scenario node to sit under, so it would not show. The allocator
   (#21) should always allocate under a named scenario; confirm with Shrey.

## Checkpoint · 18 Oct 2026
- **Works:** `optev/graph/retrieve.py` with eight templates; `retrieve()` (design signature),
  `run(session, ...)` for tests, `bind()` for validation; CLI `ask`. All eight answer on the
  sample in Aura (Neo4j 5.27); unknown ids return `[]` and the CLI prints "no evidence".
- **Decided:** decisions are matched by `ABOUT` + `scenario_id` (with `observed` for none), so
  no template spells out a key format. One row per question for site questions, with lists
  inside (rules, demand, allocations), instead of one row per rule. COLLECT subqueries
  (Neo4j 5.6+). Driver warnings off in `retrieve()`: a relationship type with no rows yet
  (AFFECTS on the sample) only warns.
- **Tests:** 6 unit (read-only, schema names only, parameters match, named in the design,
  bad calls raise, values never enter the query text) and 3 live.
- **Next:** #27 explanation layer on top of `retrieve()`; its 20 questions double as the
  Precision@k answer key.
