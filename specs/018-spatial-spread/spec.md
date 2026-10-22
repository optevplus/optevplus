# 018 · baseline: spatial spread

**Owner:** Gurneet  ·  **Status:** ready for review  ·  **Branch:** `gurneetkb/37-spatial-spread`
**Issue:** #37  ·  **WBS:** 7.1b Baseline: spatial spread only

## Design section
SYSTEM_DESIGN.md §6:

> **Baselines**, each producing an `Allocation` for the same request (area, points) and rules,
> scored by the same objective: busiest first (#36), spatial spread (#37), extend sites that
> already have chargers (#38) …

WBS 7.1b: "Implement one simple selection rule, then push it through the same budget and the
same eligibility rules as ours, so the only thing that differs is the selection logic."

## Approach
`optev/evaluation/baselines.py`: `spatial_spread(request, inputs) -> Allocation`, a harness
`Method`. It uses the harness's own `eligible` and `room`, so only the selection differs.

**Rule (greedy max–min distance):** each point goes to the eligible site with room that is
farthest from every site already charging (existing connectors, planned picks, or a point this
baseline has placed), ties by site id. A site that gets a point starts charging, so points spread
one per site before any site gets a second. It never looks at demand.

Distances are great-circle metres: the evaluation must not import ingest's projection (§2.3
rule 4), and ranking by spread needs no more precision. `baselines.py` is where #36 and #38 can
add theirs. Registered in `harness.sample_inputs` as "spatial spread (#37)".

## Verification
`tests/test_baselines.py` (8 tests, sample): requested points with 0 violations; the first point
goes to the open site farthest from existing charging; one point per site before doubling;
new sites before sites that already charge; demand doesn't change the plan; stops when room runs
out; respects the area; appears in the comparison table.

**Sample table (12 points, base, island-wide):**

| Method | Drivers rescued / h | vs best baseline |
|---|---|---|
| random (mean of 100) | 3.398 ± 0.133 | 1.00× |
| population share | 3.037 | 0.89× |
| sample reference (greedy) | 3.738 | 1.10× |
| **spatial spread (#37)** | **3.632** | **1.07×** |

## Open question
`compare` takes "best baseline" from random and population share only. Spatial spread beats
both on the sample (1.07×), so once #36–#38 are in, the end-to-end number (§6, "against the best
baseline") should count them too. That's a harness change for #39's owner.

## Checkpoint · 22 Oct 2026
- Built and tested on the sample; ruff, mypy, pytest pass.
