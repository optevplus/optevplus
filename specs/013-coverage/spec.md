# 013 · Coverage and freshness reporting (#12)

**Owner:** Ghanashyam  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/12-coverage`

## Design section

> ```python
> # optev/ingest/coverage.py
> def coverage_report(window_start: datetime, window_end: datetime) -> dict[str, float]
> ```
> **Coverage (#12).** Write to `coverage_report`: snapshot completeness per feed, median
> freshness (`collected_ts − provider_ts`), share of stations matched at each threshold,
> share of sites with a planning area, amenities linked to a car park. — SYSTEM_DESIGN.md §4.1

Issue #12: done when it is a queryable table that refreshes, not a script someone ran once.

## Approach
- `measure(conn, start, end)` computes every metric it can and names the ones it cannot: a
  metric whose inputs are not loaded (stations, sites, amenities) is skipped, never written as
  0, because 0 would read as "nothing matched" instead of "not measured".
- `write(conn, metrics)`: one row per metric, one shared `run_at`, so runs stay comparable.
- `optev-db coverage` measures the collected week (from `stg_collect_slot`) and writes a run.
- Metrics: `<feed>_slot_completeness` (against the half-hour slots in the window),
  `<feed>_freshness_median_s` (p95 in the detail), `connector_presence_median`,
  `connectors_in_every_slot`, `stations_matched_{50,100,200}m`, `sites_with_planning_area`,
  `car_parks_with_live_feed`, `amenities_linked_to_car_park` (`AMENITY_LINK_M`, EPSG:3414).

## Verification
- Unit: slot counting, including the collected week = 330.
- Live (`uv run --env-file .env pytest tests/test_coverage.py`), rolled back: a known 4-slot
  week gives 0.75 EV completeness, 60 s median freshness, the expected presence; skipped
  metrics never appear as values; a run writes exactly its metrics under one `run_at`.

## Checkpoint · 19 Oct 2026
- **First run written to Neon** for 7 Oct 14:00 – 14 Oct 10:30 SGT: both feeds 330/330 slots;
  EV data 76 s old at the median (p95 98 s); car park data 132 s (p95 1,032 s, about 17 min);
  11,580 of 11,698 charging points (99.0%) appear in every slot.
- **Not measured yet:** station matching, sites with a planning area, live-feed car parks,
  amenities linked; their inputs come from #53 (conform) and #59 (static loads).
- **Next:** rerun `optev-db coverage` after #53 and #59 load; numbers go into the report (#43).
