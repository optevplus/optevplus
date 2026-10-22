# 019 · app shell: map, rankings, selection controls

**Owner:** Gurneet  ·  **Status:** ready for review  ·  **Branch:** `gurneetkb/30-app-shell`
**Issue:** #30  ·  **WBS:** 6.3 App shell: map, rankings, selection controls

## Design section
SYSTEM_DESIGN.md §4.6:

> Streamlit multipage app. `app/data.py` is the only module that reads data: from Postgres when
> `DATABASE_URL` is set, otherwise from `optev.sample`, so every page works before the database
> is ready.
> | Map (shell, #30) | Gurneet | Sites coloured by outcome, sized by allocated points; demand as H3 hexagons; controls |
> Sidebar controls: planning area (or island-wide), number of points, optional budget, scenario.
> Selecting a site calls `scenario.planned.select_site` and re-runs allocation. **No business
> logic in the app.**

WBS 6.3 done-when: "a scenario's rankings render on the map and a site can be selected."

## Approach
- **`app/data.py`**: `load() -> AppData` is a bundle of contracts: areas, sites, car parks, latest indicators, `all`-bin demand, baseline decisions, register, scenarios with planned picks, recent allocations, and references.
  - **Postgres** (`DATABASE_URL` from the environment or `SystemCode/.env`): reads the §3.2 tables.
  - **Sample:** decisions come from `rules.screen` over the sample, so the map always reflects the current register.
  - **References:** there's no table for them yet, so they come from the sample's reference list.
- **`app/shell.py`**: pure, tested without Streamlit.
  - `plan` calls the allocator (#21) when it's installed, otherwise uses the stored plan for the same request.
  - `site_rows`, `ranking`, `demand_hexes` (H3, resolution 8) and `funnel` arrange the data for display.
  - Every figure is named with its layer: observed, inferred or recommended.
- **`app/main.py`** (the Map page):
  - sidebar request
  - funnel metrics
  - pydeck map: dots coloured by outcome and sized by recommended points, over demand hexagons
  - ranked table
  - site selection through `scenario.planned.select_site` / `clear_selection`, which needs Postgres; the sample is read-only
- **`h3`** is added as a dependency (the design names H3 hexagons).

## Verification
- `tests/test_app_shell.py` has 11 tests:
  - the sample bundle
  - Postgres loading through a fake connection (every query in `data.SQL`)
  - the stored-plan fallback
  - layer labels, with utilisation `None` and never 0 (invariant 2)
  - ranking order
  - hexagon sums
  - the funnel
  - the real page rendering on the sample, via Streamlit `AppTest`
- ruff, mypy, pytest: 219 passed, 23 skipped.

## Open questions
1. The allocator gets the observed `all` demand. Scenario demand (#28) should replace it for
   `low`/`base`/`high` once it exists.
2. Selections are written with `selected_by="app"`. There's no login, so a planner name could be a sidebar field.

## Checkpoint · 22 Oct 2026
- Map page renders on the sample. Not yet run on Neon (no `DATABASE_URL` here).
- Next: Rules page (#31) on top of `AppData`.
