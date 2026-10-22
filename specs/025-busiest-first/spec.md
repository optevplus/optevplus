# 025 · Baseline: busiest first

**Owner:** Shrey  ·  **Status:** draft, awaiting Shrey's OK  ·  **Branch:** `shrey/36-busiest-first` (from `gurneetkb/37-spatial-spread`, #80, which creates `evaluation/baselines.py`)
**Issue:** #36 (7.1a · Baseline: rank by observed utilisation)

## Design section
SYSTEM_DESIGN.md §6 (1.13 on `main`):

> **Baselines**, each producing an `Allocation` for the same request (area, points) and rules,
> scored by the same objective: busiest first (#36), spatial spread (#37), extend sites that
> already have chargers (#38), population share and random averaged over 100 seeds (in the
> harness, #39). **End-to-end number:** unmet demand covered per new point against the best baseline.

`evaluation/CLAUDE.md`: compare fairly by walking each baseline's ranking under the same
request and rules, so only the selection logic differs. §2.3 rule 2: `utilisation` is `None`,
never `0`, without supply.

## Problem
There is no "busiest first" baseline, so the optimiser cannot be compared with the obvious
planner's rule: put chargers where the existing ones are busiest. Issue #36: done when it
produces an allocation directly comparable with the system's.

## Contracts touched
Reads `SiteIndicators.utilisation` (unchanged contract); returns `Allocation`.

## Approach
1. **Harness input** (`evaluation/harness.py`, #39): `Inputs` gains
   `indicators: list[SiteIndicators] = field(default_factory=list)`, defaulted so no caller
   breaks; `sample_inputs` passes `s.indicators`. Today `Inputs` carries no utilisation at all.
2. **`busiest_first(request, inputs) -> Allocation`** in `evaluation/baselines.py`, a harness
   `Method` next to `spatial_spread`:
   - rank eligible sites with room (`harness.eligible`, `harness.room`) by observed
     `utilisation`, highest first, ties by `site_id`; latest indicator window per site;
   - walk the ranking and fill each site up to its room before moving to the next;
   - sites with `utilisation` None (no supply or unobserved) are **not ranked as 0**: they go
     after every measured site, in `site_id` order;
   - never reads demand.
3. Registered in `harness.sample_inputs` as "busiest first (#36)".

## Verification
`tests/test_baselines.py`, on the sample through the harness:
- places the requested points with 0 violations; same request copied onto the plan;
- the first site filled is the eligible site with room and the highest utilisation;
- a `None`-utilisation site is used only after every measured site is full;
- ignores demand (tripled demand gives the same plan);
- respects the area and stops when room runs out;
- the harness table lists "busiest first (#36)".
ruff, mypy, `NEO4J_URI= uv run pytest` pass; `uv run python -m optev.evaluation.harness` prints the row.

## Open questions
1. **Fill to room vs one point per site.** "Busiest first" read literally fills the busiest
   site first. Spreading one per site round-robin is a different rule (closer to #38). I'd fill.
2. **Touching the harness** (Ghanashyam's #39) to add `indicators` to `Inputs`. It's additive
   with a default; the alternative is passing utilisation through `residents`-style ad hoc
   dicts, which is worse. I'd ping him on the PR.
3. **Stacked on #80** (Gurneet, unreviewed). If #80 changes, this rebases.
