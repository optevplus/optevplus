# 016 · checker

**Owner:** Shrey  ·  **Status:** approved 20 Oct 2026 (proposals as written); built, open questions raised on the PR  ·  **Branch:** `shrey/22-checker` (from `main`)
**Issue:** #22 (4.3 independent feasibility checker)  ·  **Depends on:** #21 (PR #68) only for
end-to-end use; this branch does not need it  ·  **Unblocks:** #23, #32, #35

## Design section
SYSTEM_DESIGN.md §4.4 (version 1.8 on `main`, after #70):

> **Checker (#22, Shrey).** `optev/reasoning/checker.py`, `check(allocation, decisions, sites)
> -> Allocation`; the request (area, points, budget) is read from the allocation. It **must not
> import `allocate.py`**. It re-tests every constraint above independently, fills `violations`,
> and sets `checked = True`. Only checked allocations are written or shown.

"Every constraint above" is the allocation list in §4.4: eligible sites (accept or
conditional, inside `planning_area`), room `floor(MAX_SHARE_OF_LOTS × total_lots) −
effective_connectors` floored at 0, `Σx = requested_connectors` if given, `COST_PER_POINT_SGD ×
Σx ≤ budget` if given (budget only: as many points as it pays for), `x ≤ room`, and each
item's `cost = COST_PER_POINT_SGD × connectors`. Design 1.8 (#70) removed the minimum per
planning area, so there is no coverage check. "Checked by": 0 violations on a good plan, and "the checker
catches every planted fault". Issue #22: "Done when a deliberately broken plan is caught."
`reasoning/CLAUDE.md`: "whatever proposes a plan must not be what approves it."

## Problem
The allocator's plan is unchecked (`checked = False`), and nothing may show or store a plan
until something independent has re-tested it. There is no checker.

## Contracts touched
Reads `Allocation`, `AllocationItem`, `Decision`, `CandidateSite`. Returns a copy of the
`Allocation` with `violations` filled and `checked = True`. **No contract changes.**

## Approach
`optev/reasoning/checker.py`, pure, written from the design text alone: it imports only
`optev.contracts` and `optev.assumptions`, never `allocate.py`. A test enforces that.

`check` returns `allocation.model_copy(update={"violations": [...], "checked": True})`, so the
input object is never changed. It sets `checked = True` even when there are violations,
because "checked" means "has been re-tested" and the violations say whether it passed (Q2).

One violation per broken constraint instance. Each is a string `"<code>: <detail>"` that names
the site or area, e.g. `room: SYN-S-04 has 6, room 4`. The codes:

| Code | Re-test |
|---|---|
| `unknown_site` | every item's site is in `sites` |
| `duplicate_site` | at most one item per site |
| `not_eligible` | the site's decision is accept or conditional (the scenario's own decision, else the baseline one, as in the allocator) |
| `outside_area` | with a `planning_area`, every item's site is in it |
| `points` | `Σx = requested_connectors`; with only a budget, `Σx = floor(budget / COST_PER_POINT_SGD)` |
| `budget` | `COST_PER_POINT_SGD × Σx ≤ budget` |
| `room` | `x ≤ floor(MAX_SHARE_OF_LOTS × total_lots) − existing_connectors`, floored at 0 (see Q1) |
| `cost` | each item's `cost = COST_PER_POINT_SGD × connectors` (to the cent) |

The checker deliberately repeats arithmetic that `allocate.py` also does (room, the budget
floor, which decision applies) instead of sharing it. Two independent copies is the point.

## Verification
`tests/test_checker.py`, on `optev.sample`, no database:
- **A good plan passes:** the sample's reference `allocation` (12 points island-wide) gives 0
  violations and `checked = True`; the input object is unchanged.
- **Every planted fault is caught,** one test per code. Each takes the good plan and breaks one
  thing: a rejected site, an unknown site, a duplicated item, a site outside the area, 11
  points instead of 12, over budget, more than room, a wrong cost.
  Each gives exactly that code.
- **Budget-only plans:** 32 points on 300 000 SGD pass; 31 fail `points`.
- **Independence:** `checker.py` imports neither `allocate` nor anything outside
  `optev.contracts` and `optev.assumptions` (checked by reading its imports).
- Then `uv run ruff check . && uv run mypy optev && uv run pytest`.

## Open questions (raised on the PR, not decided in code)
1. **Planned capacity is invisible to the checker.** Room uses `effective_connectors` =
   existing + the scenario's planned, but `check(allocation, decisions, sites)` gets no
   `Scenario`, so it can only see `existing_connectors`. It would pass a plan that
   overfills a site with planned points. Options: add `scenario: Scenario` to the signature (a
   design change), or have the caller pass sites whose `existing_connectors` already include
   planned. Proposed: raise it; code uses `existing_connectors` and documents the gap.
2. **`checked = True` with violations.** Proposed as above (checked = re-tested). The
   alternative is `checked = False` when anything fails. The app (#32) and the write need to
   agree on which rows count as "checked".
3. **Writing to Postgres.** §4.4 says only checked allocations are written, but defines no write
   function (raised on #68 as Q5). Proposed: still no write in this PR; it needs a design line
   naming the function.
4. **Violation format.** The design gives no format for `violations`. Proposed: the codes
   above, which #23's constraint groups (requested, budget, room) map onto.

## Checkpoint · 20 Oct 2026
- **Works:** `optev/reasoning/checker.py` (103 lines): `check` and `violations`, with its own
  room, budget floor and decision choice. Imports only `optev.contracts`, `optev.assumptions`
  and the standard library; a test parses its imports to keep it that way.
- **Tests:** 15 in `tests/test_checker.py`. The sample's reference plan passes with 0
  violations. Every planted fault is caught by its own code: not eligible, unknown site,
  duplicate, outside area, points, budget-only points, budget, room, coverage, cost.
  ruff, mypy, pytest 79 passed, 8 skipped.
- **Cross-check, not committed:** the allocator from PR #68, run from a scratch copy, produced
  plans for 12 points island-wide, 300 000 SGD, 5 points in TM, and 20 points with
  200 000 SGD. All pass this checker with 0 violations.
- **Raised on the PR:** Q1 (planned capacity invisible), Q2 (`checked` with violations),
  Q3 (no write function), Q4 (violation format).
- **Next:** #23 unmet-requirement reporting (`binding_constraints`, `affected_areas`).

## Checkpoint · 20 Oct 2026 (2) · design 1.8
- Merged main (#53, #54, #70). Following #70, the `coverage` check and `MIN_POINTS_PER_AREA`
  are gone. A test now confirms that an area with 0 points is not a violation: the
  regenerated sample plan puts nothing in PR. 15 tests.
