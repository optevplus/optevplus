# 022 · Unmet-requirement reporting

**Owner:** Shrey  ·  **Status:** approved 21 Oct 2026; built  ·  **Branch:** `shrey/23-unmet-requirement` (from `shrey/20-allocator`)
**Issue:** #23 (4.4 · Unmet-requirement reporting)  ·  **Builds on:** #68 (allocator), #69 (checker)

## Design section
SYSTEM_DESIGN.md §4.4 (1.13 on `main`), "Unmet requirement (#23)":

> When infeasible: `max_feasible` = the most connectors any feasible plan allows;
> `binding_constraints` = each constraint group (requested, budget, room) whose removal alone
> makes the request feasible; `affected_areas` stays empty (kept on the contract; no per-area
> constraint exists). With only a budget, `requested_connectors` = `floor(budget / COST_PER_POINT_SGD)`.

And §3.3: infeasibility report id `<scenario>:<area or all>:requested=<n>`.

## Problem
`allocate` (#68) already returns an `InfeasibilityReport` with `max_feasible`, but
`binding_constraints` is always empty. A planner sees "you can have at most 40" and not why:
too little room in the area's car parks, or too little budget.

## Contracts touched
Reads/produces `InfeasibilityReport` (`contracts/decisions.py`), unchanged:
`scenario_id`, `planning_area`, `requested_connectors`, `max_feasible`, `binding_constraints`,
`affected_areas`. No contract change.

## Approach
All in `optev/reasoning/allocate.py`.

1. The constraints are cardinality only, so feasibility needs no second solve: with `points`
   (requested, or derived from the budget), the request fits iff `points ≤ Σ room` and
   (`cap` is None or `points ≤ cap`), `cap = budget_cap(budget)`.
2. `binding(points, rooms, cap) -> list[str]`, in the order `budget`, `room`: a group binds
   when it falls short **and** every other group fits, i.e. removing it alone makes the
   request feasible. This is the rule the sample's answer key uses
   (`optev/sample/generate.py::over_request`, `binding_constraints = ["budget"]` for PR / 40
   points / SGD 300,000), which the graph and app already read.
3. `allocate` fills `binding_constraints` on the report; `affected_areas` stays `[]`;
   `max_feasible` is unchanged (`most_points`).

Not in scope: writing the `infeasibility` table (pipeline, #35) and the app view (#32).

## Verification
New tests in `tests/test_allocate.py`, on `optev.sample`:
- more points than all the room, no budget → `["requested", "room"]`, `max_feasible` = total room;
- points within room but over the budget → `["requested", "budget"]`, `max_feasible` = cap;
- over both room and budget → `["requested"]` only (removing either alone is not enough);
- budget only, room too small → `requested_connectors == floor(budget / 9250)`, `["requested", "room"]`;
- a feasible request still returns an `Allocation` (unchanged);
- `affected_areas == []` in every case.
Then `uv run ruff check .`, `uv run mypy optev`, `NEO4J_URI= uv run pytest`: all pass.

## Decisions (were open questions)
1. **`requested` is never listed.** The sample's answer key never lists it, and removing the
   target trivially "fits" (place 0), so it says nothing. The planner's lever is `max_feasible`.
2. **Over both room and budget lists nothing**, since neither alone is enough; `max_feasible`
   still says how far to scale down. Changing that is a design PR, not code.
3. The report id (§3.3) is not built here: the contract has no id field.

## Checkpoint · 21 Oct 2026
- **Works:** `binding` and the filled report; the PR / 40 / SGD 300,000 case now equals the
  sample's `infeasibility` exactly. 5 new tests (budget only binds, room only, both → none,
  budget-only request, `binding` table). ruff, mypy, pytest pass.
- **Next:** PR on top of #68 (base `shrey/20-allocator`); retarget to `main` once #68 merges.

## Checkpoint · 22 Oct 2026
- Renumbered from 018 to **022** (018 is taken by #80); the allocator spec is now 021.
  Merged `shrey/20-allocator`. No code change.
