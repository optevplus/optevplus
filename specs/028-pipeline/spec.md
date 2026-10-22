# 028 · Pipeline and load_all (#35, #25)

**Owner:** Ghanashyam  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/35-pipeline`

## Design section
> `optev/pipeline.py`, run as `uv run python -m optev.pipeline run --scenario base --area TM
> --points 12`. Order: migrate check → `conform` → … → `allocate` → `check` → graph `load_all`.
> — SYSTEM_DESIGN.md §5; `load_all(database_url)` — §4.5

## Approach
- `optev/pipeline.py`: one function per step calling the stage's own module, in the design's
  order; `--from` / `--only`; a report of counts and seconds per step. Writes the plan
  (`write_plan`, §3.3 ids), which no stage owns. The allocator gets `scenario_demand`.
- `optev/graph/read.py`: every pipeline table into one bundle; `load()` now takes any number of
  plans and reports. `load_all` = read + apply schema + load. `python -m optev.graph load` (no
  `--sample`) runs it.
- `optev/sample/seed_db.py`: the sample into an empty migrated database, as collection and the
  static loads would write it, so the whole pipeline runs offline.

## Verification
- 7 tests: every query maps to a bundle field; many plans and none load; the plan is written
  under its design id; step order and restart; and one live run.
- **Ran end to end on a local Postgres 17 + PostGIS seeded with the sample:** 30 sites,
  11 measured (1 lower bound), 19 regression estimates, 3 scenarios, rules 8 accept /
  16 conditional / 4 defer / 2 reject, plan 12 points at 8 sites, SGD 111,000, 0 violations,
  coverage written. The graph bundle from it builds every node and relationship type.

## Checkpoint · 22 Oct 2026
- Not yet run on Neon (this network blocks port 5432) and `load_all` not yet written to Aura,
  to keep the sample graph the tests use. First Neon run: from a network that allows 5432.
