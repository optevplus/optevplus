# 018 · Unmet-requirement reporting

**Owner:** Shrey  ·  **Status:** draft, awaiting Shrey's OK  ·  **Branch:** `shrey/23-unmet-requirement` (from `shrey/20-allocator`)
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
All in `optev/reasoning/allocate.py`; no new public function (the design names none).

1. The constraints are cardinality only, so feasibility needs no second solve. With
   `points` (requested, or derived from the budget), `total_room = Σ room` over eligible sites
   and `cap = budget_cap(budget)`, the request is feasible iff
   `points ≤ total_room` and (`cap` is None or `points ≤ cap`).
2. A private `_binding(points, total_room, cap) -> list[str]` returns, in the fixed order
   `requested`, `budget`, `room`, each group whose removal alone makes it feasible:
   - `requested`: dropping `Σx = points` leaves only `≤` constraints, so always feasible
     → always listed when infeasible (the planner can ask for fewer, up to `max_feasible`).
   - `budget`: listed iff a budget was given and `points ≤ total_room`.
   - `room`: listed iff `cap` is None or `points ≤ cap`.
3. `allocate` fills `binding_constraints` from `_binding` when it returns a report;
   `affected_areas` stays `[]`. `max_feasible` stays `most_points(rooms, cap)`.
4. Budget-only: `requested_connectors` on the report is already
   `floor(budget / COST_PER_POINT_SGD)` via `points_for`; a test pins it.

Not in scope: writing to the `infeasibility` table (no writer is named in §4.4; that is the
pipeline, #35), app display (#32).

## Verification
New tests in `tests/test_allocate.py`, on `optev.sample`:
- more points than all the room, no budget → `["requested", "room"]`, `max_feasible` = total room;
- points within room but over the budget → `["requested", "budget"]`, `max_feasible` = cap;
- over both room and budget → `["requested"]` only (removing either alone is not enough);
- budget only, room too small → `requested_connectors == floor(budget / 9250)`, `["requested", "room"]`;
- a feasible request still returns an `Allocation` (unchanged);
- `affected_areas == []` in every case.
Then `uv run ruff check .`, `uv run mypy optev`, `NEO4J_URI= uv run pytest`: all pass.

## Open questions
1. **`requested` is always binding.** Read literally, removing the points target always makes
   the request feasible (place 0). I list it anyway, since it is the planner's own lever
   ("ask for at most `max_feasible`"). Alternative: list it only when nothing else is. Your call.
2. **Over both room and budget** gives `["requested"]` alone, which hides that room and budget
   both fall short. That is what "removal alone" says; changing it is a design PR, not code.
3. Should the report id (§3.3) be built here? The contract has no id field, so I leave it to
   whoever writes the `infeasibility` table.
