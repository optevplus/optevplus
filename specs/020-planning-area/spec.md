# 020 · Planning area, land use and amenity sites in conform

**Owner:** Shrey  ·  **Status:** draft, awaiting Shrey's OK  ·  **Branch:** `shrey/11-planning-area` (from `shrey/55-static-loads`, which has the `stg_` tables)
**Issue:** #11 (1.6 · Planning area assignment)  ·  **Builds on:** #58, #59 (migration 004, `load_static`)

## Design section
SYSTEM_DESIGN.md §4.1 (1.13 on `main`, 1.14 with #58), method step 3:

> Build `candidate_site` from car parks plus amenities with **no** car park within
> `AMENITY_LINK_M`; an amenity near a car park becomes `site_context.amenities_nearby` for
> that car park, never a second site. [...] Fill `site_context` by point-in-polygon on MP2025
> land use and planning areas.

§3.2 (1.14): `stg_amenity`, `stg_land_use`, `stg_residents` are written by `load_static` and
**read by conform**. §4.1 step 4: coverage reports the share of sites with a planning area.

## Problem
`conform()` assigns a planning area by `ST_Contains` (Gurneet, #53), but it still builds car
park sites only ("no amenity source yet") and leaves `site_context.land_use` and
`residents_in_area` NULL. The `stg_` tables that fill them are loaded in Neon (spec 004), but
nothing reads them; Gurneet's spec 003 checkpoint leaves that to the static-loads work.
Sites outside every planning-area polygon stay NULL; the issue asks for the nearest area plus
a flag, which the design does not define.

## Contracts touched
None changed. Reads `CandidateSite` (amenities become `CandidateSite` with `kind`
`hawker_centre` / `community_facility`, `site_id` = `stg_amenity.amenity_id`), writes the
§3.2 tables `candidate_site` and `site_context` only.

## Approach
In `optev/ingest/conform.py` (Gurneet's module; ingest is shared):
1. `READ_AMENITIES` from `stg_amenity` → `parse_rows(CandidateSite, ...)` → passed to
   `conform_records` as `amenities` (the core already links or keeps them, and is tested on
   the sample). Drop the "no amenity source" log line.
2. After `FILL_PLANNING_AREA`, two set-based updates:
   - `FILL_LAND_USE`: `site_context.land_use = stg_land_use.lu_desc` where `ST_Contains`;
     if plots overlap, the smallest `land_use_id` wins (deterministic, re-runnable).
   - `FILL_RESIDENTS`: `site_context.residents_in_area = stg_residents.residents` via the
     site's `planning_area`.
3. Count sites left without a planning area / land use in `issues` and log them, so the run
   says how many fell outside every polygon.
4. `conform.py` is already ~450 lines; the new SQL goes in the existing constants block.

## Verification
- Unit: a test that `stg_amenity`-shaped rows parse into amenity `CandidateSite`s and flow
  through `conform_records` on the sample (linked vs standalone).
- Live (skipped without `DATABASE_URL`): one test inside a **rolled-back** transaction that
  runs `write` + the fills against Neon and checks every site has `land_use`/`residents` or is
  counted. Nothing is committed.
- ruff, mypy, `NEO4J_URI= uv run pytest` pass.
- **Re-running `optev-db conform` on Neon only with your explicit OK**, afterwards.

## Open questions
1. **Points outside every polygon.** The design keeps them NULL; the issue wants "nearest
   centroid + flag". A flag needs a column the design lacks (a table change). Options:
   (a) keep NULL, report the count (this spec, no design change); (b) design PR: nearest
   planning area by `ST_Distance` and a coverage count `sites_outside_planning_area`, no new
   column. I'd do (a) now and raise (b) with Ghanashyam if the count is not ~0.
2. **Overlapping land-use plots:** smallest `land_use_id` wins. Fine, or prefer largest overlap?
3. `residents_in_area`: `residents` (all) or `residents_hdb`? I'd use `residents`, per the
   `site_context` column name.
