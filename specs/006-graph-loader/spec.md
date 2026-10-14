# 006 · Graph loader (#25)

**Owner:** Ghanashyam  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/25-graph-loader`

## Design section

> **Loader (#25).** Reads Postgres after each pipeline run; MERGE in batches of 500 using the
> key helpers in `schema.py`; order: areas, car parks, stations, connectors, sites,
> `station_site`, indicators, `all` demand estimates, datasets, documents, assumptions, rules,
> scenarios, decisions with `EVALUATED`, allocations, infeasibility. Never loads raw readings
> or per-bin estimates. — SYSTEM_DESIGN.md §4.5

## Problem
The graph has a schema (#24) but nothing in it. Postgres is not provisioned yet (#2), so a
loader that can only read Postgres cannot be built or tested this week, and the retrieval
(#26) and explanation (#27) work behind it would wait too.

## Contracts touched
Reads every contract in `optev.sample.Sample`; produces none. Needs design 1.1 in the
schema: `Allocation.planning_area` and optional `budget`, so `allocation_key` and
`infeasibility_key` change (on #47, not here).

## Approach
1. **Bring #47 up to design 1.1:** merge `main`; `allocation_key(scenario, area, points,
   budget)`; `planning_area` on Allocation and Infeasibility; `on_fail` on Rule.
2. **Split read from write (design change, §4.5):**
   - `load(data: Sample, session) -> dict[str, int]` MERGEs a bundle of contract objects.
   - `load_all(database_url)` reads Postgres into the same bundle, then calls `load`.
   - Until Postgres exists, `python -m optev.graph load --sample` loads `optev.sample`.
3. `rows(data) -> list[Batch]`: pure function turning contracts into parameter rows, in the
   design's order, one batch per node label or relationship. All logic lives here, testable
   without Neo4j.
4. One fixed Cypher per batch (`UNWIND $rows AS r MERGE ... SET ...`), sent 500 rows at a time.
5. Rules link by what `source_ref` points to: `doc-` CITES a Document, `ds-` READS a
   Dataset, `asm-` ASSUMES an Assumption; every rule gets FROM_SOURCE its class.
6. Missing values are sent as null, which removes the property (`SET n += ...`), so they are
   absent and never 0 (invariant 2), and a value that disappears on re-load is removed too.
   Planned selections become `(:Scenario)-[:PLANS]->(:CandidateSite)`, never a site property
   (invariant 1).
7. References (areas, datasets, documents, assumptions) load first, so every relationship that
   cites them finds its target. A relationship is only emitted when both ends are in the bundle.

## Verification
- `uv run pytest`: `rows()` covers every node and relationship type in `schema.py`, uses
  exactly the schema properties, keeps missing values absent, and puts no planned capacity on
  a site.
- Live test (skips without `NEO4J_URI`): load the sample twice; counts are identical the
  second time (MERGE is idempotent); `python -m optev.graph load --sample` prints them.

## Open questions
1. OK to load the sample into the shared Aura now? Every id starts with `SYN-`, and
   `python -m optev.graph clear --sample` removes it before real data goes in.
2. Scenarios link to growth assumptions only once #28 declares them; until then, no
   `ASSUMES` from Scenario.

## Checkpoint · 14 Oct 2026
- **Works:** `optev/graph/load.py` (`rows`, `load`, `clear_sample`); CLI `load --sample` and
  `clear --sample`. 11 unit tests; live test loads the sample into Aura twice with identical
  counts. The sample is loaded in Aura now: 227 nodes labelled `:Sample`.
- **Decided:** design 1.2 adds `load(data, session)` beside `load_all`, the `ds-`/`doc-`/`asm-`
  reference ids, and references-first load order (the 1.1 order loaded datasets after the
  indicators that point at them). On #47: allocation keys follow design 1.1, `on_fail` on Rule.
- **Not built:** `load_all` (the Postgres reader) waits for #2 and migration 002 on Neon.
  `Scenario-ASSUMES->Assumption` waits for growth assumptions from #28.
- **Next:** #26 retrieval templates, written against the loaded sample.
