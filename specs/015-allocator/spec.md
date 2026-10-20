# 015 · allocator

**Owner:** Shrey  ·  **Status:** approved 20 Oct 2026 (proposals as written); built, open questions raised on the PR  ·  **Branch:** `shrey/20-allocator`
**Issues:** #20 (4.1 cost model and constraint formulation), #21 (4.2 allocator)
**Unblocks:** #22 checker, #23 unmet-requirement reporting, #36 baseline, #35 integration

## Design section
SYSTEM_DESIGN.md §4.4 (version 1.5 on `main`), "Allocation (#20–#21, Shrey)":

> ```python
> # optev/reasoning/allocate.py
> def allocate(decisions: list[Decision], sites: list[CandidateSite],
>              demand: list[DemandEstimate], scenario: Scenario, *,
>              planning_area: str | None = None, requested_connectors: int | None = None,
>              budget: float | None = None) -> Allocation | InfeasibilityReport
> ```
>
> - **Request:** `requested_connectors` (the planner's points), `budget`, or both; neither raises
>   `ValueError`. `planning_area` None means island-wide. The request is copied onto the
>   `Allocation` or `InfeasibilityReport`.
> - **Eligible sites:** outcome accept or conditional, inside `planning_area` if given. Room per site =
>   `floor(MAX_SHARE_OF_LOTS × total_lots) − effective_connectors`, floored at 0.
> - **Objective:** maximise average drivers per hour rescued,
>   `Σ_site Σ_bin w_bin × λ_bin × (B(c, a_bin) − B(c + x, a_bin))`, with `w = 5/7 ÷ 24` for
>   weekday bins and `2/7 ÷ 24` for weekend bins, `λ` from `scenario_demand` (or
>   `demand_estimate` for `observed`), `c` = effective connectors.
> - **CP-SAT formulation:** binary `y[site, k]` for the k-th new point, `x = Σ_k y`, ordered
>   `y[k] ≥ y[k+1]`; objective coefficients are the marginal gains, scaled ×1000 to integers.
>   Constraints: `Σ x = requested_connectors` if given; `Σ COST_PER_POINT_SGD × x ≤ budget` if
>   given (with only a budget, place as many points as it pays for); `x ≤ room`; every planning
>   area in scope with an eligible site gets at least `MIN_POINTS_PER_AREA`. Each item's `cost` is
>   `COST_PER_POINT_SGD × connectors`, shown as an estimate even without a budget. Time limit
>   30 s; record solver status and optimality gap.

Also used: §4.2 step 2 (`B` is Erlang B; arrivals per hour = `a ÷ MEAN_SESSION_HOURS`, so
`a_bin = λ_bin × MEAN_SESSION_HOURS`), §4.3 (`effective_connectors` = existing + planned for
that scenario only), §4.4 "Unmet requirement (#23)" (with only a budget,
`requested_connectors = floor(budget / COST_PER_POINT_SGD)`), §3.4 time bins, §3.5 values
`MAX_SHARE_OF_LOTS`, `COST_PER_POINT_SGD`, `MIN_POINTS_PER_AREA`, `MEAN_SESSION_HOURS`,
§2.3 rules 4 and 5 (packages talk through contracts; every declared number from
`optev.assumptions`).

## Problem
Nothing turns decisions and demand into a plan. `optev/reasoning/` has no allocator, so the
checker (#22), the unmet-requirement report (#23), the baselines (#36–#39), the app's
allocation view (#32) and the end-to-end run (#35) have nothing to work with. The sample's
`allocation` is a greedy reference, not the optimiser the design specifies.

## Contracts touched
Reads `Decision`, `CandidateSite`, `DemandEstimate`, `Scenario` (with its `planned` list of
`PlannedCapacity`). Produces `Allocation` with `AllocationItem`s, or `InfeasibilityReport`.
**No contract changes.** Uses `ortools` (already a dependency).

## Approach
`optev/reasoning/allocate.py`, pure: no database, no imports from other workstreams.

1. **Validate the request.** Neither points nor budget → `ValueError`. Budget only →
   points = `floor(budget / COST_PER_POINT_SGD)` (#23's rule), placed exactly.
2. **Decision per site.** The decision whose `scenario_id` equals `scenario.scenario_id` if
   there is one, otherwise the baseline decision (`scenario_id` None or `observed`).
   Eligible = accept or conditional, and in `planning_area` when given.
3. **Effective connectors (#20).** `c = site.existing_connectors + Σ scenario.planned
   connectors for that site`, read from the `Scenario` contract, so `scenario/` is not imported.
4. **Room (#20).** `floor(MAX_SHARE_OF_LOTS × total_lots) − c`, floored at 0. A site with no
   `total_lots` has room 0 (no capacity limit can be stated).
5. **Demand per bin.** For each site, the 48 `wd-HH` / `we-HH` rates with weights
   `5/7 ÷ 24` and `2/7 ÷ 24` (these sum to 1). `a_bin = λ_bin × MEAN_SESSION_HOURS`. A site with
   no estimate has λ = 0: it gains nothing, so it gets points only if a constraint forces it.
6. **Marginal gains (#20).** `g[s, k] = Σ_bin w × λ × (B(c+k−1, a) − B(c+k, a))` for
   k = 1…room. Erlang B is concave in servers, so gains shrink with k and the ordered
   `y[k] ≥ y[k+1]` model is exact. `B` is computed here with the standard recurrence.
7. **CP-SAT (#21).** `y[s, k]` binary; maximise `Σ round(1000 × g) × y`. Constraints as quoted:
   `Σ x = points`, `COST × Σ x ≤ budget` (when given), `x ≤ room`, and `Σ x ≥ MIN_POINTS_PER_AREA`
   for each area in scope that has an eligible site. 30 s limit, fixed seed, one worker so
   results are reproducible. Status and gap are logged (see Q4).
8. **Output.** Feasible → `Allocation` with the request copied on, one item per site with
   `x ≥ 1`: `connectors = x`, `cost = COST_PER_POINT_SGD × x`, `marginal_relief = Σ g[s, 1..x]`
   (drivers per hour rescued at that site, as in the sample). `checked = False`: only the
   checker (#22) sets it. Infeasible → `InfeasibilityReport` with the request and
   `max_feasible` from one more solve that maximises `Σ x` under the other constraints;
   `binding_constraints` and `affected_areas` are left to #23.

## Verification
`tests/test_allocate.py`, on `optev.sample`, no database:
- **Reference plan:** the base scenario, 12 points island-wide. Every constraint holds
  (12 points, `x ≤ room`, ≥ 2 per area, costs). The objective is **≥ the sample's greedy plan**,
  scored by the same objective on the same effective connectors.
- **Planned capacity counts:** base has 2 planned points at `SYN-S-04`, which reduce its room and
  raise its `c`. The sample's greedy reference ignored them (it gives S-04 6 points); the test
  checks the allocator does not.
- **Budget only:** 300 000 SGD → `floor(300000 / 9250) = 32` points, cost within budget.
- **Infeasible:** 40 points in `PR` with 300 000 SGD → report with `max_feasible = 32`
  (matches the sample's report).
- **Request rules:** neither points nor budget → `ValueError`; the area filter; reject and defer
  sites never get points; a site with no demand gets nothing unless forced.
- **Math:** Erlang B equals the sample's `erlang_b` values; gains are non-increasing in k;
  weights sum to 1.
- **Reproducible:** the same request twice gives the same plan.
- Then `uv run ruff check . && uv run mypy optev && uv run pytest`.

## Open questions
Shrey, 20 Oct 2026: build with the proposals below; raise each on the PR for the team to
confirm rather than deciding it in code.

1. **Erlang B.** §2.3 rule 4 forbids importing another workstream, and `erlang_b` belongs to
   `analysis/demand.py` (#14, Sushant). Proposed: a private copy in `allocate.py`, tested equal
   to the sample's. The alternative is a shared helper, which needs a design change.
2. **Demand with only `all`.** The sample's estimates have only the `all` bin, and real
   `no_supply` sites get per-bin rows from #16. Proposed: if a site has no `wd-`/`we-` rows, use
   its `all` rate with weight 1, which gives the same result for a flat profile. Otherwise the
   sample can't be used for tests.
3. **Coverage when an area can't reach the minimum.** The design says every area in scope
   *with an eligible site* gets ≥ 2 points. An area whose eligible sites have less than 2 room in
   total makes the whole request infeasible. Island-wide on real data (about 50 areas) that also
   means any request under ~100 points is infeasible. Proposed: follow the design literally
   now and let #23 report which areas bind; raise it with the team if it bites in the demo.
4. **Solver status and gap.** "Record solver status and optimality gap", but neither the
   `Allocation` contract nor the `allocation` table has a field for them. Proposed: log both
   now; adding fields is a contract change (all four owners), so it goes to the team.
5. **Writing to Postgres.** §3.3 says the allocator writes `allocation_id` in the
   `allocation_key` format, but §4.4 defines no write function and "only checked allocations
   are written". Proposed: no database write in this PR; the write (with ids built in the same
   format, not by importing `graph`) comes with the checker (#22).
6. **Decision per scenario.** Proposed: use the scenario's own decision, else the baseline
   (step 2). Confirm with Gurneet's rules (#54), which produce the decisions.

## Checkpoint · 20 Oct 2026
- **Works:** `optev/reasoning/allocate.py` (241 lines): `allocate` plus the cost-model helpers
  `erlang_b`, `effective_connectors`, `room`, `demand_profile`, `marginal_gains`,
  `eligible_sites`, `points_for`, `budget_cap`, and the CP-SAT `solve` / `most_points`.
  16 tests in `tests/test_allocate.py`; ruff, mypy, pytest 80 passed, 8 skipped.
- **On the sample:**
  - Base, 12 points island-wide: optimal in 0.1 s. Relief 3.738 drivers/h on base's effective
    connectors; the greedy reference scores lower on the same connectors.
  - The greedy reference ignored base's 2 planned points at `SYN-S-04` and gave it 6; the
    allocator counts them and gives it 4.
  - Budget 300,000 SGD → 32 points. 40 points in PR on 300,000 SGD → infeasible,
    `max_feasible` 32, as the sample's report.
- **Left out on purpose:**
  - No database write: Q5, which goes with #22.
  - Solver status and gap are only logged: Q4.
  - `binding_constraints` and `affected_areas` are #23.
- **Not measured:** solve time on the real island-wide data (2,932 sites). It needs real demand
  estimates (#14, PR #66) and decisions (#17, PR #54).
- **Next:** team answers to Q1–Q6 on the PR; then #22 checker (with the write) and #23.
