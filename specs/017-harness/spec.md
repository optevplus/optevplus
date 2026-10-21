# 017 · Experiment harness (#39)

**Owner:** Ghanashyam (shared ticket)  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/39-harness`

## Design section
> **Baselines**, each producing an `Allocation` for the same request (area, points) and rules,
> scored by the same objective: busiest first (#36), spatial spread (#37), extend sites that
> already have chargers (#38), population share and random averaged over 100 seeds (in the
> harness, #39). **End-to-end number:** unmet demand covered per new point against the best
> baseline. — SYSTEM_DESIGN.md §6

Issue #39: done when one command produces the comparison table the report needs.

## Approach
- `optev/evaluation/harness.py`. A method is any `(Request, Inputs) -> Allocation`.
- **The yardstick is independent:** the §4.4 objective (drivers per hour rescued, Erlang B,
  weekday/weekend weights, `all`-only sites at weight 1), room and eligibility are written here
  from the design, not imported from `reasoning/`, so it cannot share a bug with the optimiser.
  Effective connectors include the scenario's planned picks.
- Baselines here: random (100 seeds, mean ± sd) and population share (largest remainder by
  residents per planning area; car lots stand in when residents are not given).
- Table columns: points, drivers rescued per hour, per point, ratio to the best baseline,
  constraint violations, runtime.
- `python -m optev.evaluation.harness` runs it on the sample, adding the optimiser
  automatically once `optev.reasoning.allocate` is on main.

## Verification
6 tests: Erlang B values; rescued is 0 for no plan and grows with diminishing returns;
violations name room, eligibility and over-request; random is reproducible and valid;
population share follows residents (a test caught 0 residents being treated as missing);
the table compares every method on one request.

## Checkpoint · 20 Oct 2026
- Sample, base scenario, 12 points island-wide, demand projected ×1.8:
  random 3.398 ± 0.133, population share 3.037, greedy reference 3.738 drivers/h.
  With Shrey's #68 merged locally (not committed): optimiser 3.743, 1.10× the best baseline,
  0 violations, 19 ms.
- **Next:** at integration (#35), run on real data with residents from `stg_residents`, add
  the #36–#38 baselines as methods, and copy the table into the report (#42, #43).
