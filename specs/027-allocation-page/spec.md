# 027 · Allocation page (#32)

**Owner:** Ghanashyam (taken over from Shrey for the 22 Oct cut-off)  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/32-allocation-page`

## Design section
> | Allocation (#32) | The plan, estimated cost (against the budget if given), checker result, unmet requirement |
> **No business logic in the app.** — SYSTEM_DESIGN.md §4.6

## Approach
- `optev/app/pages/3_Allocation.py`: the request controls (area, points, optional budget,
  scenario); the plan from `shell.plan` (allocator, #21); the verdict from
  `reasoning.checker.check` (#22); metrics, the plan table, the checker's violations, and the
  declared values with their sources. An infeasible request shows what was asked, what fits,
  and why, in planner terms.
- `optev/app/allocation_view.py`: pure `summary`, `plan_rows`, `infeasible`, `assumption_rows`.
  Room comes from `reasoning.allocate.room`, not re-derived. Conditional sites list the rules
  they must still satisfy next to the recommendation.

## Verification
5 tests (summary and passing check, rows never exceed room, infeasible explanation, sources
named, AppTest page run for a plan and for an impossible request). Ran the app on the sample:
12 of 12 points, 9 sites, SGD 111,000, checker passed.

## Checkpoint · 22 Oct 2026
Works on the sample. On Neon it shows whatever the allocator returns for the request; the
page itself does not read data (app/data.py does).
