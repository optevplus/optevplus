# 011 · Site indicators

**Owner:** Sushant  ·  **Status:** approved  ·  **Branch:** `sushant/13-indicators`  ·  **Issue:** #13

## Design section

`SYSTEM_DESIGN.md` 1.5, §4.2 Stage 2 · Measurement & inference (`analysis/`):

```python
# optev/analysis/indicators.py
def site_indicators(window_start: datetime, window_end: datetime) -> list[SiteIndicators]
def occupancy_by_bin(window_start: datetime, window_end: datetime) -> dict[str, dict[str, float]]
    # site_id -> time_bin -> mean occupancy
```

> 1. **Indicators (#13).** Per snapshot, occupancy = occupied ÷ (occupied + available) over the
>    site's matched connectors; unavailable connectors are excluded. `utilisation` = mean over
>    snapshots; `saturated_fraction` = share of snapshots with none available and at least one
>    occupied; `observation_coverage` = snapshots seen ÷ expected. `supply_state`: `no_supply`
>    with no active connectors, `supply_idle` below `IDLE_BELOW`, else `supply_active`;
>    `unobserved` when coverage is too low to say.

Also binding: §2.3 (invariants 2 and 3, upserts keyed on the primary key), §3.4 (time bins,
SGT), §3.5 (`IDLE_BELOW`, `SNAPSHOT_MINUTES`), §3.6 (tests run on `optev.sample`).
Tables read: `candidate_site`, `station_site`, `connector`, `connector_reading`.
Table written: `site_indicators` (`002_pipeline.sql`, PK `site_id, window_start, window_end`).

## Problem

Nothing turns the 3.8 M connector readings into a per-site measure. Demand inference (#14),
patterns (#15), the rules (#17–19) and the app all start from `site_indicators` and the
per-bin occupancy, so stage 2 onwards is blocked on this.

## Contracts touched

Produces `SiteIndicators`. Reads `CandidateSite`, `Connector`, `ConnectorReading`, and the
station-site association (`near` in the sample, `station_site` in Postgres). No contract change.

## Approach

1. **Pure core** (no database), so tests run on `optev.sample` — see Q1:
   - `compute_indicators(sites, near, connectors, readings, window_start, window_end)
     -> list[SiteIndicators]`
   - `compute_occupancy_by_bin(sites, near, connectors, readings, window_start, window_end)
     -> dict[str, dict[str, float]]`
2. **Site → connectors.** A site's connectors are those of every station matched to it in
   `station_site`/`near` (threshold rule: Q3), keeping only `ever_active` connectors
   (invariant 3). `active_connectors` = that count.
3. **Snapshots.** Expected = number of `SNAPSHOT_MINUTES` slots in `[window_start, window_end)`
   (330 for the collected week). A snapshot is *seen* for a site if any of its connectors has
   a reading at that slot. Per seen snapshot: occupied and available counts; unavailable
   excluded. Snapshots with neither occupied nor available are seen but carry no occupancy.
4. **Indicators per site.**
   - no active connectors → `no_supply`, utilisation and saturated_fraction `None`,
     coverage 1.0 (as the sample does: there is nothing to observe).
   - coverage below the threshold (Q2) → `unobserved`, utilisation `None`.
   - else utilisation = mean occupancy over snapshots with occupancy; saturated_fraction over
     the same snapshots; `supply_idle` if utilisation < `IDLE_BELOW`, else `supply_active`.
   - `dwell_opportunity` left `None` (Q4).
5. **Per bin.** Each snapshot is put in `wd-HH`/`we-HH` by its SGT slot time; mean occupancy
   per bin; `all` = `(5 × mean of wd bins + 2 × mean of we bins) / 7` (§3.4). Only sites with
   `supply_active` or `supply_idle`; bins with no snapshots are omitted.
6. **Postgres wrappers.** `site_indicators` and `occupancy_by_bin` read the four tables for the
   window with one parameterised query each (`connector_reading` filtered on `collected_ts`,
   using the existing index), call the core, and `site_indicators` upserts into
   `site_indicators`. Readings are aligned to slots by flooring `collected_ts` to the
   30-minute slot (load_collected already chose one poll per slot within 150 s).
7. `analysis/CLAUDE.md` gets a one-line pointer to this spec.

## Verification

- `uv run pytest tests/analysis/test_indicators.py`:
  - On `optev.sample`, `compute_indicators` reproduces `s.indicators` for all 30 sites
    (supply_state, active_connectors exact; utilisation, saturated_fraction, coverage to 4 dp).
    The generator computes them the same way, so this is a real cross-check.
  - The never-active connector is not counted; the feed-gap station (SYN-ST-05) gives
    coverage 92/96; the idle site is `supply_idle`; no-charger sites have utilisation `None`.
  - `compute_occupancy_by_bin`: bins are valid §3.4 values, `all` matches the formula, a
    `no_supply` site is absent.
  - Unit tests for the edge cases: all-unavailable snapshots, low coverage → `unobserved`.
  - Live test (skipped without `DATABASE_URL`, rolled back): `site_indicators` writes rows and
    a second run leaves the same rows.
- `uv run ruff check .`, `uv run mypy optev`, `uv run pytest` all pass.
- On real data (once #9/PR #53 has filled `candidate_site`, `station_site`, `connector`):
  every site has a row for the week window with a coverage figure.

## Open questions

1. **Pure functions not in the design.** §4.2 only defines the two Postgres-reading functions,
   but §3.6 needs tests on the sample. *Proposed:* add `compute_indicators` and
   `compute_occupancy_by_bin` to §4.2 (as 1.4 did for the graph's `load`/`load_all`), in a
   small design PR. Alternative: keep them private (`_compute…`) and test through them.
2. **"Coverage too low to say" has no value.** *Proposed:* new assumption
   `MIN_COVERAGE = Assumption(0.5, "share of expected snapshots", "Project assumption")` in
   `optev/assumptions.py` and §3.5. Needs your number.
3. **Which match threshold, and double counting.** `station_site` keeps each station-site pair
   at the smallest threshold met (50/100/200 m), and a station can match several sites.
   *Proposed:* count a station at every site it matches within 100 m. Alternatives: 50 m only;
   or each station only at its nearest site.
4. **`dwell_opportunity`** is in the contract and table but §4.2 does not define it.
   *Proposed:* leave `None` in this issue.
5. **Issue text vs design.** #13 asks for occupancy episodes and occupied connector-time;
   §4.2 measures mean occupancy over snapshots and #14 uses the declared
   `MEAN_SESSION_HOURS`, not observed episodes. *Proposed:* follow the design and update the
   issue text to match.
6. **Window.** *Proposed:* the real run uses `[7 Oct 2026 14:00, 14 Oct 2026 11:00)` SGT, which is
   exactly the 330 loaded slots.

## Decisions

Approved as proposed by Sushant, 19 Oct 2026:

1. *Decided:* `compute_indicators` and `compute_occupancy_by_bin` are public and added to §4.2
   by a small design PR (`SYSTEM_DESIGN.md` 1.6, renumbered 1.10 on merging main).
2. *Decided:* `MIN_COVERAGE` = 0.5 of expected snapshots, declared in `optev/assumptions.py`
   and §3.5.
3. *Decided:* a station counts at every site it matches within 100 m. **Superseded 21 Oct
   2026** (review of PR #63): a station counts at its nearest site only (smallest `distance_m`,
   ties by `site_id`, as design 1.6 already binds for conform), and only if that site is within
   100 m. Its chargers are one queue with one stream of arrivals; counting it at two sites
   doubles both demand and existing chargers for Erlang B.
4. *Decided:* `dwell_opportunity` stays `None` in this issue.
5. *Decided:* follow the design over the issue text; update #13 to match.
6. *Decided:* real window `[7 Oct 2026 14:00, 14 Oct 2026 11:00)` SGT.

## Checkpoint · 19 Oct 2026

- **Works:** `SYSTEM_DESIGN.md` 1.6 and `MIN_COVERAGE` committed on their own branch
  `sushant/13-design-indicators` for the design PR. `optev/analysis/indicators.py` has the four
  §4.2 functions; `tests/test_indicators.py` (11 tests) reproduces all 30 sample indicators to
  4 dp, and the live test (rolled back) shows the Postgres counts give the same indicators and
  the upsert is re-runnable. ruff and mypy pass; pytest passes except 5 graph tests that fail
  the same way on `main` (Neo4j host does not resolve).
- **Decisions:** counting is done in SQL (`GROUP BY site, slot`) for Postgres and in Python for
  contracts, both feeding one `_measure`, so 3.8 M readings never become Python objects. A
  reading goes to its *nearest* slot, not the floor, because `load_collected` may keep a poll
  up to 150 s before the slot. With only weekday or only weekend bins in a window, `all` is the
  mean of the bins present (the sample covers Thu–Fri only).
- **Blocked:** the real run needs `candidate_site`, `station`, `connector`, `station_site`,
  all empty in Neon until #9 (PR #53) lands.
- **Next:** design PR reviewed; then the implementation PR; then
  `site_indicators([7 Oct 14:00, 14 Oct 11:00) SGT)` once #53 merges; then #14.

## Checkpoint · 21 Oct 2026

- **Works:** main merged into #63 and #64; design renumbered 1.10 (main reached 1.9).
  `nearest_site` keeps each station's nearest `station_site` row; the two SQL queries use the
  same rule (`DISTINCT ON (station_id) ... ORDER BY station_id, distance_m, site_id`). Two new
  tests (shared station, tie); the live test adds a farther row for a sample station and still
  reproduces the sample. ruff, mypy and pytest pass except the graph tests (Neo4j host in
  `.env` does not resolve, as before).
- **Next:** #66 and #67 merged down the chain; real run once #63/#64 merge.
