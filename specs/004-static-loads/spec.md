# 004 · static loads

**Owner:** Shrey  ·  **Status:** approved 17 Oct 2026; built, not yet run on Neon  ·  **Branch:** `shrey/55-static-loads` (from `gurneetkb/1.4-conform-sites`, merges after #53)
**Design PR:** #58 (`shrey/55-design-stg-tables`: §3.2 rows + migration 004)
**Issue:** #55 (WBS 1.4a)  ·  **Unblocks:** conform (#9, PR #53)

## Design section
SYSTEM_DESIGN.md §4.1, interface:

> ```python
> # optev/ingest/static.py
> def load_static() -> dict[str, int]             # rows loaded per static source
> ```

§4.1, method step 2:

> 2. **Static loads.** URA places with `NO_CAR > 0` only. Petrol stations filtered to service
>    stations by name; if too noisy, drop them and record why.

and from step 3 (conform, which reads what this loads): *"Convert SVY21 to WGS84 with pyproj
(EPSG:3414 → 4326) … Fill `site_context` by point-in-polygon on MP2025 land use and planning
areas."* §3.2: *"Ingest-internal staging tables are allowed if prefixed `stg_`."* §3.3 ids:
`hdb:<car_park_no>`, `ura:<PP_CODE>`, `hawker:<id>` / `cc:<id>` / `petrol:<id>` from the source
dataset, station = LTA `locationId` (*now `postalCode`, design 1.14; decision 8*), connector = LTA `evCpId`, planning area = URA `PLN_AREA_C`.
§2.3 rules 3 and 6 (installed only once seen active; upserts keyed on the primary key).

## Problem
Neon holds only the collected readings. `planning_area`, `car_park`, `station` and `connector`
are empty (spec 003, checkpoint 4), so `conform()` builds no sites: readings carry ids, not
coordinates. Land use, amenities and residents have no table at all, so conform leaves
`site_context.land_use`, `residents_in_area` and amenity sites empty.

## Sources
Every data.gov.sg file comes from
`https://api-open.data.gov.sg/v1/public/api/datasets/<id>/poll-download` (keyless; returns a
signed S3 link valid 1 h). Ids found in the data.gov.sg catalogue on 17 Oct 2026. **Every
source was downloaded for the Neon load on 19 Oct 2026** (`data/raw/<name>_2026-10-19.*`,
including the EVCBatch snapshot); the ids were first checked on 17 Oct 2026.

| # | Source | Dataset id | Format, CRS | Updated | Size | Rows seen 17 Oct |
|---|---|---|---|---|---|---|
| 1 | MP2025 Planning Area Boundary (No Sea) | `d_2cc750190544007400b2cfd5d7f53209` | GeoJSON, WGS84 | 27 Feb 2026 | 2.2 MB | 55 (48 Polygon, 7 MultiPolygon) |
| 2 | HDB Carpark Information | `d_23f946fa557947f93a8043bbef41dd09` | CSV, SVY21 x/y | 8 Oct 2026 | 0.3 MB | 2,273, all ids distinct, all with x/y |
| 3 | LTA DataMall `EVCBatch` (one snapshot) | — (`LTA_ACCOUNT_KEY`) | JSON link to file, WGS84 | live; snapshot 19 Oct 2026 | 3.3 MB | 2,799 locations, 9,208 charging points, 11,698 connectors |
| 4 | MP2025 Land Use Layer | `d_a8c3546b26712e35021f3a681d0353ae` | GeoJSON, WGS84 | 27 Mar 2026 | **190 MB** | 113,394 plots (113,001 Polygon, 393 MultiPolygon), 2.73 M vertices, 33 `LU_DESC` values |
| 5 | Hawker Centres (GeoJSON), NEA | `d_4a086da0a5553be1d89383cd90d07ecd` | GeoJSON, WGS84 | 17 Oct 2026 | 0.14 MB | 129 |
| 6 | Community Club / PAssion WaVe Outlet, PA | `d_9de02d3fb33d96da1855f4fbef549a0f` | GeoJSON, WGS84 | 2 Oct 2026 | 0.09 MB | 128 (122 `CC`, 6 `PAssionWave`) |
| 7 | Licensed premises for petroleum products, Customs | `d_f5db74053e49ce79039f1b13549d1efb` | GeoJSON (KML), WGS84 | 6 Jun 2024 | 0.02 MB | 21 — **dropped**, see below |
| 8 | Resident Population by Planning Area/Subzone of Residence and Type of Dwelling (Census 2020) | `d_7f243956483d5901f237e6f87b096636` | CSV | 18 Jun 2021 | 0.03 MB | 388 lines; one `<Area> - Total` row per planning area |
| 9 | Capacity of URA Parking Places (GeoJSON) | `d_9bf8620ecfdc8a5f8f77e3f02160af5c` | GeoJSON, WGS84 | 7 Oct 2026 | 0.3 MB | 774; 659 with `NO_CAR > 0`, ids distinct |

Not used: *Amendment to Master Plan 2025 Land Use Layer* (`d_7a03324bed531cdff76a16239b0e84e1`,
21 Sep 2026, 190 MB) — see Q4. *Community Clubs* (`d_f706de1427279e61fe41e89e24d440fa`, 2024) is an
older copy of source 6.

**Petrol stations are dropped (design §4.1 step 2).** The Customs list has 21 premises and every
one is an oil terminal, refinery or power station (Jurong Island, Pulau Bukom, Pulau Sebarok,
Tuas, Senoko; e.g. Vopak Terminals, Singapore Refining Co, Tuas Power Generation). None is a retail
service station, so the name filter keeps 0 rows. No `petrol:` sites are loaded; the loader logs
this once. It is a licence list for bulk storage, not a station list.

## Tables
Existing tables (`001_init.sql`), written as the design defines them:

| Table | Columns written | From | Left alone (owned by conform) |
|---|---|---|---|
| `planning_area` | `code` = `PLN_AREA_C`, `name` = `PLN_AREA_N`, `region` = `REGION_N`, `geom` = `ST_Multi(...)` 4326 | 1 | — |
| `car_park` | HDB: `car_park_id` = `'hdb:'‖car_park_no`, `name` = `address` (the registry has no name), `car_park_type`, `planning_area` (point-in-polygon), `geom`. URA: `car_park_id` = `'ura:'‖PP_CODE`, `name` = `PARKING_PL`, `total_lots` = `NO_CAR` (only `NO_CAR > 0`), `planning_area`, `geom` | 2, 9 | HDB `total_lots` (NULL on insert; an update keeps conform's value), `has_live_feed` |
| `station` | `station_id` = `postalCode` (see decision 8), `operator`, `address`, `planning_area` (point-in-polygon), `geom`; `provenance` default `observed` | 3 | — |
| `connector` | `connector_id` = `evCpId`, `station_id`, `plug_type`, `power_kw` | 3 | `ever_active` |

New staging tables, `migrations/004_static.sql`, each also listed in SYSTEM_DESIGN.md §3.2
(so `tests/test_design.py` passes) and noted in the §10 change log:

```sql
-- One row per amenity that could become a candidate site (§3.3 ids). conform links it to a car
-- park within AMENITY_LINK_M or makes it a standalone site.
CREATE TABLE IF NOT EXISTS stg_amenity (
    amenity_id  text PRIMARY KEY,           -- 'hawker:<OBJECTID>' | 'cc:<OBJECTID>'
    kind        text NOT NULL CHECK (kind IN ('hawker_centre', 'community_facility',
                    'petrol_station')),     -- SiteKind values
    name        text NOT NULL,
    address     text,
    status      text,                       -- hawker STATUS, cc DESCRIPTION, as published
    geom        geometry(Point, 4326) NOT NULL
);

-- MP2025 land-use plots, only what point-in-polygon needs, geometry simplified (below).
CREATE TABLE IF NOT EXISTS stg_land_use (
    land_use_id text PRIMARY KEY,           -- source OBJECTID
    lu_desc     text NOT NULL,              -- e.g. RESIDENTIAL, COMMERCIAL
    geom        geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS stg_land_use_geom_idx ON stg_land_use USING GIST (geom);

-- Residents per planning area (Census 2020, the "<Area> - Total" rows).
CREATE TABLE IF NOT EXISTS stg_residents (
    planning_area text PRIMARY KEY REFERENCES planning_area(code),
    residents     integer NOT NULL CHECK (residents >= 0),      -- Total
    residents_hdb integer CHECK (residents_hdb >= 0),           -- HDBDwellings_Total
    source_year   integer NOT NULL                              -- 2020
);
```

`petrol_station` stays in the `kind` check so the source can be restored without a migration.
Hawker centres keep every `STATUS` (including the 6 "Under Construction"); the status column lets
conform or the rules decide (Q5). Community clubs keep `DESCRIPTION = 'CC'` only (the Dataset
Guide: "filter on DESCRIPTION").

## Contracts touched
Reads/produces `PlanningArea`, `CarPark`, `Station`, `Connector`, `Coordinate`. Parsed rows are
validated through these models (bad rows logged and skipped). Amenities, land use and residents
have no contract and stay inside ingest as `stg_` rows. **No contract changes.**

## Approach
`optev/ingest/static.py` (target under ~300 lines):

- `download(dataset_id, name) -> Path`: poll-download, then fetch the signed URL into
  `<repo>/data/raw/<name>_<YYYY-MM-DD>.<ext>` (gitignored by `data/raw/`, which git anchors at the repo root, so `SystemCode/data/raw/` would **not** be ignored). Reuses today's file
  if present. Retries with backoff: poll-download answers without a URL when called in quick
  succession (seen 17 Oct). EVCBatch: `LTA_ACCOUNT_KEY` from the environment only, link followed
  at once (it expires in minutes), as the collector did.
- Pure parsers, one per source, each returning rows plus a skipped count and never raising on a
  bad record: `parse_planning_areas`, `parse_hdb_car_parks` (SVY21 → WGS84 with
  **`conform.svy21_to_wgs84`**, which returns None outside Singapore → skipped),
  `parse_ev_batch` → (`Station`s, `Connector`s), `parse_amenities` (hawker, cc),
  `parse_land_use`, `parse_residents` (name → code by upper-casing both names against
  `planning_area.name`; an unmatched name is logged and skipped), `parse_petrol` (name filter,
  kept so the drop is reproducible and tested).
- Writers: one transaction per source. `INSERT … ON CONFLICT (pk) DO UPDATE SET … WHERE (cols)
  IS DISTINCT FROM (EXCLUDED cols)`, so a second run updates nothing. Updates touch only the
  columns in the table above, never `total_lots`, `has_live_feed` or `ever_active`. Geometry goes
  in as GeoJSON text through psycopg parameters (`ST_GeomFromGeoJSON(%s)`), never formatted.
  Order: planning areas first, then car parks and stations (`planning_area` set by
  `ST_Contains` in the same statement), then the rest.
- **Land use size:** load into a temp table, `ST_SimplifyPreserveTopology(geom, tol)` and keep
  `lu_desc` only, then report `pg_total_relation_size('stg_land_use')` and
  `pg_database_size` before and after. Tolerance in Q3.
- `load_static() -> dict[str, int]`: runs all sources, returns rows loaded per source, e.g.
  `{"planning_area": 55, "hdb_car_park": 2273, "ura_car_park": 659, "hawker": 129,
  "community_club": 122, "petrol": 0, "land_use": 113394, "residents": 55}` plus `station` and
  `connector` once EVCBatch is confirmed.
- `optev-db load-static` in `cli.py`, beside `migrate` and `load-collected`, loading
  `SystemCode/.env` through the existing `_database_url()`; prints one line per source.

## Verification
- `tests/test_static.py`, no network: small fixtures in the shape of each source (a 2-feature
  planning-area GeoJSON with sample codes TM/PR, HDB CSV rows, an EVCBatch payload, hawker/cc
  features, land-use features, residents CSV lines, the petrol KML description). Each parser:
  happy path, one bad record skipped and counted, ids per §3.3. Writers checked with a fake
  cursor: upsert SQL only, parameters only, protected columns never in an update. Residents name
  matching on the sample's planning areas. CLI usage test beside `tests/test_cli.py`.
- Live test (skipped without `DATABASE_URL`): run the writers inside a transaction that is rolled
  back; a second write of the same rows reports 0 changed.
- `uv run ruff check . && uv run mypy optev && uv run pytest`, then on Neon:
  `uv run optev-db migrate && uv run optev-db load-static` twice (second run: no changes), then
  `uv run optev-db conform` runs on the real tables (issue #55 "done when").
- Report in the checkpoint: rows per source, rows skipped and why, land-use size, database size.

## Decisions (approved 17 Oct 2026)
1. **Branch base:** from PR #53's branch; this PR merges after #53.
2. **URA:** loaded, 659 places with `NO_CAR > 0`, as `ura:<PP_CODE>` with `total_lots = NO_CAR`,
   because §4.1 step 2 names it. Issue #55 left it out; the PR says so.
3. **Land use:** `ST_SimplifyPreserveTopology(geom, 0.00001)`, keeping `OBJECTID`, `LU_DESC` and
   geometry only. The writer measures `stg_land_use` inside its transaction and rolls back with
   `LandUseTooLarge` above 60 MB, so the stop-and-ask is enforced, not only documented.
4. **MP2025 base layer**, not the amendment.
5. **Residents: Census 2020** (`d_7f243956483d5901f237e6f87b096636`), `source_year = 2020`. Area
   totals sum to 4,044,250 against the file's national 4,044,210: the census rounds to tens. The
   file writes `Changi- Total` once; the parser accepts it, so all 55 areas match.
6. **Hawker centres:** all 129 kept, `status` recorded (6 "Under Construction").
7. **Ids:** `hawker:<OBJECTID>` and `cc:<OBJECTID>` per §3.3. **Stability risk:** `OBJECTID` is
   the publisher's row id and may be renumbered when a layer is republished. A re-load would then
   add rows under new ids and leave the old ones, so the amenity count would grow. Compare counts
   after any re-download before trusting a re-run.
8. **EVCBatch, confirmed on the 19 Oct snapshot.** Locations carry `address`, `name`,
   `postalCode`, `latitude`, `longtitude` (LTA's spelling) and `chargingPoints`. **There is no
   `locationId`**, which §3.3 named, so `station_id = postalCode`: present on all 2,799 locations
   and unique, while coordinates are not (46 pairs shared). Agreed with Shrey on 19 Oct; §3.3 is
   fixed in design PR #58. `operator` is per charging point and 42 locations have more than one,
   so `station.operator` is the sorted set joined with `'; '`. Connector `plug_type` =
   `plugType`, `power_kw` = `powerRating` (a string; non-numeric or ≤ 0 left NULL, none today).
   The snapshot's 11,698 `evCpId`s are exactly the 11,698 in `connector_reading` (checked
   read-only), so every reading traces to a station.
9. **Conform is not edited.** Reading `stg_amenity`, `stg_land_use` and `stg_residents` is a
   follow-up for Gurneet, listed in the PR.
10. **Credentials:** `SystemCode/.env` has both `DATABASE_URL` and `LTA_ACCOUNT_KEY` (checked
    without printing them). Read-only Neon checks passed on 17 Oct 2026: 692 MB used,
    `planning_area`, `car_park`, `station`, `connector` empty, `stg_collect_slot` the only `stg_`
    table.

## Open questions (as drafted, now answered above)
1. **Branch base.** `svy21_to_wgs84` is only on `gurneetkb/1.4-conform-sites` (PR #53, open).
   Branch from it, or wait for #53 to merge and rebase? (Proposed: branch from it, and merge
   after #53.)
2. **URA car parks.** §4.1 step 2 names "URA places with `NO_CAR > 0`" and conform already maps
   `ura:` → `public_car_park`, but the task list leaves URA out. Load the 659 into `car_park` as
   `ura:<PP_CODE>`? If so, set `total_lots = NO_CAR` (the registry is the capacity source for
   URA, unlike HDB), and conform's `match_feed` will count them all `registry_without_feed`.
3. **Land-use tolerance.** Measured 17 Oct: 113,394 plots, 2.73 M vertices. Unsimplified, the
   geometry alone is ~50 MB in PostGIS (16 B per vertex), ~60 MB with the GiST and key indexes,
   which would take Neon from ~690 MB to ~750 MB of 1 GB. Proposed:
   `ST_SimplifyPreserveTopology(geom, 0.00001)` (~1.1 m, below the 50 m matching threshold),
   keeping `OBJECTID`, `LU_DESC` and geometry only, with every plot kept, roads included (a
   surface car park can sit on a road plot). Expected about 30–40 MB; the actual size is measured
   and reported. If it comes out above 60 MB, stop and ask before going further.
4. **Land use base or amendment.** Load the MP2025 layer (Mar 2026), or the Amendment (Sep 2026,
   same size, newer)? Proposed: the base layer, as named in the design and the Dataset Guide.
5. **Residents source.** The Dataset Guide names SingStat's yearly table (planning area × dwelling
   type). data.gov.sg only has the Census 2020 version, keyless. The yearly one (June 2025) is on
   SingStat's Table Builder, not data.gov.sg. Proposed: Census 2020 now, recorded as such.
6. **Hawker status.** Keep the 6 under-construction centres (status recorded) or drop them?
7. **Amenity ids.** `OBJECTID` is the only id in both files; it may change when the publisher
   reloads the layer. Fine for §3.3, or prefer postal code?
8. **Station operator.** If EVCBatch gives the operator per charging point, not per location,
   `station.operator` takes the location's single operator, or a `;`-joined list when there are
   several. Field names are confirmed against one live payload before coding.
9. **Conform reads the stg_ tables.** Conform today passes no amenities and leaves land use and
   residents NULL. Reading `stg_amenity`, `stg_land_use`, `stg_residents` is a change to
   Gurneet's conform (#53); this spec does not edit conform.
10. **Credentials.** `SystemCode/.env` on this machine has the template `DATABASE_URL` and an
    empty `LTA_ACCOUNT_KEY`. Neon size (~690 MB) and the EVCBatch shape cannot be checked here
    until both are filled in.

## Checkpoint · 17 Oct 2026
- **Works:** `optev/ingest/static.py` (download with retry into `<repo>/data/raw/`, pure parsers,
  upsert writers that skip unchanged rows, land-use size guard), `optev-db load-static`,
  migration 004 (via design PR #58). 17 tests in `tests/test_static.py` plus one live test that
  rolls back. ruff, mypy, pytest: 86 passed, 5 skipped (`test_graph_live` needs `NEO4J_URI=` in
  the shell because `.env` holds the template Neo4j URI; unrelated, fails the same on `main`).
- **Real files, parsed only (no database):** planning areas 55, HDB 2,273, URA 659, hawker 129,
  CC 122, petrol 0, residents 55, land use 113,394; 0 skipped in each.
- **Not run on Neon:** no `migrate`, no `load-static` (held until approved). Land-use size is
  still the estimate (30–40 MB simplified); the writer reports and enforces it on the first run.
- **Blocked: EVCBatch.** `LTA_ACCOUNT_KEY` gets 401 from every DataMall endpoint tried
  (EVCBatch, BusArrival v3, CarParkAvailabilityv2, TrafficIncidents), so the key is not accepted.
  `station`/`connector` are not loaded and `parse_ev_batch` is not written (decision 8). Next:
  a working key, or one raw `.dat` from Sushant's collected week, then confirm the fields.
- **Found:** `data/raw/` in `.gitignore` is anchored at the repo root; `SystemCode/data/raw/` is
  not ignored. RAW points at the root folder; a test guards it.
- **Size:** `static.py` is ~386 lines, over the ~300 guideline (SQL constants are ~60 of them).
- **Next:** EVCBatch parser; then, when told, `migrate`, `load-static` twice (second: 0 changed),
  report sizes, `conform`.

## Checkpoint · 19 Oct 2026
- **EVCBatch done.** New key works. `download_ev_batch`, `parse_ev_batch`, `write_stations`,
  `write_connectors`; stations and connectors in one transaction. Today's snapshot parses to
  2,799 stations and 11,698 connectors, 0 skipped, and matches the week's connector ids exactly.
- **Design:** station id is `postalCode` (no `locationId` in the feed). Main took 1.4 and 1.5
  and #53 takes 1.6, so #58 is now **1.7**; #58 merged main and is mergeable again. This branch
  merged the latest #53 (conform traces each reading to a coordinate) and #58.
- **Verify:** ruff, mypy, pytest 110 passed, 9 skipped (with `NEO4J_URI=`); 21 static tests.
- `static.py` is ~486 lines, well over the ~300 guideline; splitting needs a design change
  (§4.1 names only `static.py`).
- **Next, with Shrey's go-ahead:** `optev-db migrate`, `load-static` twice (second: 0 changed),
  record land-use and database size and download dates, `optev-db conform`, mark #59 ready.

## Checkpoint · 19 Oct 2026 (2) · loaded into Neon
- **Run with Shrey's go-ahead:** `migrate` (004 applied), `load-static` ×3, `conform`.
- **Run 1:** planning_area 55, hdb_car_park 2,273, ura_car_park 659, station 2,799,
  connector 11,698, hawker 129, community_club 122, petrol 0, land_use 113,394, residents 55;
  0 records skipped anywhere. **`stg_land_use` 32.8 MB** (limit 60 MB).
- **Run 2:** 0 changed everywhere except 1 land-use plot (`676044`, a road), rewritten with a
  value identical to a fresh recompute; cause not found (the earlier value was overwritten).
  **Run 3:** 0 changed in every source, so the load is idempotent.
- **Conform:** 2,932 sites (2,273 HDB + 659 URA; amenities wait for conform to read
  `stg_amenity`), 11,462 connectors `ever_active`, 6,840 `station_site` rows (50 m 1,963 /
  100 m 743 / 200 m 4,134), 2,049 sites with chargers holding 9,441 connectors. Counted:
  1,997 car parks with a live feed, 935 without (659 URA + 276 HDB), 10 feed ids with no
  registry row (e.g. `hdb:ACE`), 504 stations with no site within 200 m.
- **Planning areas:** every car park and site has one; 1 station (`018988`, Marina Coastal
  Drive) lies 3 m outside the "No Sea" Straits View polygon and stays NULL.
- **Database:** 692 MB → **735.5 MB** of 1 GB.
- **Next:** reviews on #53, #58, #59; Gurneet's follow-up to read the `stg_` tables in conform.
