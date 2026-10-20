# 009 · Planned capacity (#29)

**Owner:** Ghanashyam (with Gurneet)  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/29-planned-capacity`

## Design section

> ```python
> # optev/scenario/planned.py
> def select_site(scenario_id: str, site_id: str, connectors: int,
>                 selected_by: str) -> PlannedCapacity
> def clear_selection(scenario_id: str, site_id: str) -> None
> def effective_connectors(scenario_id: str, sites: list[CandidateSite]) -> dict[str, int]
> ```
> Planner selections go to `planned_capacity`. When solving a scenario,
> `effective_connectors` = existing + planned for that scenario only. — SYSTEM_DESIGN.md §4.3

Issue #29: done when selecting and then deselecting leaves observed data byte-for-byte unchanged.

## Problem
The app lets a planner pick a site; nothing recorded that pick, and the allocator had no way to
see it, without writing into observed stock (invariant 1).

## Contracts touched
Reads `CandidateSite`; produces `PlannedCapacity`. No contract or table change: uses
`planned_capacity` from migration 001.

## Approach
- `select_site` validates the scenario (`observed` or a row in `scenario`) and the site (a row
  in `candidate_site`), then replaces any earlier pick for that scenario and site. One pick per
  pair, so re-selecting never adds points twice.
- `clear_selection` deletes the pair's pick; clearing nothing is fine.
- `effective_connectors` = existing + that scenario's picks, via a pure `combine()` that the
  app can also use on the sample's `Scenario.planned` without a database.
- Public functions open a connection from `DATABASE_URL` (loading `SystemCode/.env`);
  `_`-prefixed versions take a connection so tests can roll back.

## Verification
- Unit (no database): combine adds only this scenario's picks; ignores unknown sites; the
  sample's base pick lands on base only; a pick of 0 points is refused.
- Live (`uv run --env-file .env pytest tests/test_planned.py`), rolled back: select, re-select,
  clear leaves `candidate_site`, `station`, `connector` (md5 of every row) and both reading
  tables (count, max id) unchanged; picks count only in their own scenario; unknown scenario or
  site refused.

## Checkpoint · 19 Oct 2026
- **Works:** all of the above; 7 tests pass, 3 of them against Neon. Nothing persisted.
- **Decided:** re-selecting replaces (a planner changes their mind; adding would double count).
  `observed` is an allowed scenario, so picks can sit on today's supply.
- **Next:** the app calls `select_site` from the map (Gurneet, #30) and the allocator calls
  `effective_connectors` (Shrey, #21).
