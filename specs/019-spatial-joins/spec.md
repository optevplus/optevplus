# 019 · Spatial joins: close out #10

**Owner:** Shrey  ·  **Status:** approved 21 Oct 2026; built  ·  **Branch:** `shrey/10-spatial-joins` (from `main`)
**Issue:** #10 (1.5 · Spatial joins at 100 / 150 / 300 m)

## Design section
SYSTEM_DESIGN.md §4.1, method step 3 (1.13 on `main`):

> Build `station_site` at the thresholds in `MATCH_THRESHOLDS_M`, keeping one row per
> station-site pair with the smallest threshold met. A station's connectors count toward
> `candidate_site.existing_connectors` at its nearest site only (ties by `site_id`), so no
> connector is counted twice.

§3.5: `MATCH_THRESHOLDS_M` (50, 100, 200). §4.1 step 4 (coverage, #12): share of stations
matched at each threshold.

## Problem
The issue text predates the design. It asks for 100 / 150 / 300 m, three association tables
and `ST_DWithin` in PostGIS. The binding design says 50 / 100 / 200 m, **one** `station_site`
table tagged with the smallest threshold, and nearest-site attribution. Gurneet's conform
(#53, merged) already implements the design: `conform.associate` and
`conform.count_existing`, tested in `tests/test_conform.py`; coverage (#12) reports stations
matched per threshold. What is left from the issue's "done when" is the reconciliation:
**connector totals reconcile against the source**.

## Contracts touched
None changed. Reads `Station`, `Connector`, `CandidateSite` and the `StationSite` rows.

## Approach
Test only, no production code (the design names no reconciliation function):
- `tests/test_conform.py::test_connector_totals_reconcile_with_the_source`: on
  `optev.sample`, Σ `existing_connectors` over all sites + active connectors at stations with
  no site within `max(MATCH_THRESHOLDS_M)` == active connectors in the source; and each
  station's connectors land at exactly one site.
- Comment on #10 that the design (1.6) superseded 100/150/300 m and three tables, with links
  to #53 and this test, and ask the reviewer to close it with this PR.

## Verification
`uv run ruff check .`, `uv run mypy optev`, `NEO4J_URI= uv run pytest`: all pass, new test
included. No database run.

## Open questions
1. If the team still wants 100 / 150 / 300 m, that is a design PR to `MATCH_THRESHOLDS_M`
   (§3.5), not code. I'd leave the design as is.
2. Should the reconciliation also be reported on the real data, e.g. a coverage key? That is
   #12 (Ghanashyam's `coverage.py`); I'd raise it there rather than add it here.

## Checkpoint · 21 Oct 2026
- **Works:** `test_connector_totals_reconcile_with_the_source`: one sample station moved out to
  sea; Σ `existing_connectors` + connectors at stations beyond 200 m == active connectors.
  ruff, mypy, pytest pass. No production code changed; no database run.
- **Decisions:** design thresholds stay (50 / 100 / 200 m); the issue's 100 / 150 / 300 m and
  three tables are superseded by design 1.6 and #53.
- **Next:** reviewer closes #10 with this PR.
