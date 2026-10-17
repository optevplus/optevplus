# 001 · conform

**Owner:** Gurneet  ·  **Status:** built, not yet run on a database  ·  **Branch:** `gurneetkb/1.4-conform-sites`
**WBS:** 1.4 Conform: projection, entity resolution, defensive parsing

## Design section
SYSTEM_DESIGN.md §4.1, method step 3:

> **Conform.** Convert SVY21 to WGS84 with pyproj (EPSG:3414 → 4326); compute every distance
> in EPSG:3414 metres. Set `connector.ever_active` once a connector is seen available or
> occupied. Build `candidate_site` from car parks plus amenities with **no** car park within
> `AMENITY_LINK_M`; an amenity near a car park becomes `site_context.amenities_nearby` for
> that car park, never a second site. Build `station_site` at the thresholds in
> `MATCH_THRESHOLDS_M`, keeping one row per station-site pair with the smallest threshold
> met. Fill `site_context` by point-in-polygon on MP2025 land use and planning areas.

Interface: `optev/ingest/conform.py` · `def conform() -> dict[str, int]  # rows upserted per table`.
Ids per §3.3. Tables per §3.2 (`car_park`, `station`, `connector`, `connector_reading`,
`candidate_site`, `station_site`, `site_context`). §2.3 rules 3, 5, 6.

## Problem
Nothing turns car parks, amenities, stations and readings into the candidate-site tables that
stage 2 reads. This restarts 1.4 from `main`, built **only on what `optev.sample` contains**.
The earlier attempt (`gurneetkb/data-conforming`) is not carried over; only `stg_amenity`
returns, by decision (Q3).

## What the sample does and doesn't give us
| Has | Lacks |
|---|---|
| 26 car parks, 11 stations, 46 connectors (WGS84) | Raw registry rows in SVY21 |
| 4 amenity sites (hawker, community, 2 petrol) | MP2025 land-use / planning-area polygons |
| 4,416 connector readings, car-park readings | Residents by planning area |
| `sites` and `near` to check output against | Any amenity source table |

So on the sample, 1.4 is: projection helpers (round-trip tested), `ever_active` from readings,
amenity linking, `candidate_site`, `station_site`, `existing_connectors`, and the
`amenities_nearby` / `nearest_point_m` columns of `site_context`. Land use, residents and
planning-area containment are left `NULL` until real polygons exist (PostGIS `ST_Contains` in the
DB path only, not tested on sample).

## Contracts touched
Reads `CarPark`, `Station`, `Connector`, `ConnectorReading`, `CandidateSite`, `Coordinate`.
Produces `CandidateSite`, `Connector` (with `ever_active`). No contract changes.

## Approach
`optev/ingest/conform.py` (one module, under ~300 lines):
- `svy21_to_wgs84(x, y) -> Coordinate`, `metres(a, b) -> float` (both via pyproj EPSG:3414).
- `ever_active(connectors, readings) -> list[Connector]`: true once seen available/occupied;
  never flips back to false.
- `build_sites(car_parks, amenities) -> (sites, amenities_nearby)`: car parks become sites;
  an amenity within `AMENITY_LINK_M` of a car park adds 1 to that car park's count instead.
- `associate(stations, sites) -> list[dict]`: every station-site pair within the largest
  `MATCH_THRESHOLDS_M`, tagged with the smallest threshold met.
- `existing_connectors(...)` and `nearest_point_m(...)` per site.
- `conform_records(...)`: all of the above, pure, run by the tests on the sample.
- `conform()`: reads the §3.2 tables with psycopg, calls `conform_records`, upserts by primary
  key in one transaction (re-runnable, §2.3 rule 6). Thresholds from `optev.assumptions`.
- `pyproj` added to dependencies (named by the design). `optev-db conform` CLI verb.

## Verification
`uv run pytest tests/test_conform.py`, on the sample:
- SVY21 ↔ WGS84 round trip within 1 m; a known point lands in Singapore bounds.
- `ever_active` is false only for `SYN-ST-02-9`, matching the sample.
- All 4 amenities are > 150 m from a car park, so 30 sites, equal to `sample.sites`.
- `existing_connectors` per site equals `sample.sites`.
- Every `sample.near` pair is produced at its threshold (plus the extras in Q1).
- Malformed / out-of-country rows are counted, not raised; a second run gives identical output.
Then ruff, mypy, full pytest.

## Decisions (Gurneet, 17 Oct 2026)
1. **`station_site` follows the design:** every pair within 200 m, at the smallest threshold
   met. 14 rows on the sample. The sample's 11 `near` rows are a subset; the 3 extras are
   ST-05→S-07 (166 m, 200), ST-09→S-30 (178 m, 200), ST-11→S-26 (57 m, 100).
2. **A station's connectors count at its nearest site only** (ties by id), so no plug is
   counted twice. The design is silent here: **needs a one-line PR to SYSTEM_DESIGN.md §4.1.**
3. **Amenities come from `stg_amenity`** (`migrations/003_staging.sql`), which `load_static`
   (#6–#11) will write: `amenity_id` (§3.3 id), `kind`, `total_lots`, `geom`. §3.2 allows `stg_`
   tables; `test_design.py` now leaves them out of the design-table check.

Also within the design's room:
- Car-park site id = its §3.3 car-park id; kind from the prefix (`hdb:` → HDB, `ura:`/`mall:` →
  public). An id with no known prefix is counted as `unknown_source_car_park` and skipped.
- An amenity within `AMENITY_LINK_M` (≤ 150 m) links to its nearest car park.
- `ever_active` never flips back to false.
- `nearest_point_m` is the distance to the closest station with an active connector, at any range.
- Planning area: the car park's own, else PostGIS `ST_Contains`. Points outside every polygon
  stay `NULL`. `land_use` and `residents_in_area` stay `NULL`: the design names no table for
  MP2025 land-use polygons or residents yet.

## Checkpoint · 17 Oct 2026
- **Works:** `optev/ingest/conform.py` (pure core plus `write`/`conform`), `optev-db conform`,
  migration 003, pyproj dependency. 20 tests in `tests/test_conform.py`. ruff, mypy and the full
  pytest suite pass (52 passed, 1 live graph test skipped).
- **Not run:** against Neon/PostGIS; no database yet. SQL checked with a fake cursor only.
  First real run: `uv run optev-db migrate && uv run optev-db conform`.
- **Size:** `conform.py` is ~375 lines, over the ~300 guideline. If review asks, the SQL block can
  move out, but the design names only `conform.py`.
- **Windows:** sample data checked out before `.gitattributes` landed is CRLF and fails
  `test_sample`; delete the four files under `optev/sample/data/` and `git checkout` them.
- **Next:** design PR for decision 2; `load_static` writes `stg_amenity`; coverage (#12) reads
  `Conformed.issues`.
