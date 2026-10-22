# 029 · Demand page: indicators, patterns and estimates

**Owner:** Sushant  ·  **Status:** ready for review  ·  **Branch:** `sushant/33-demand-page`
·  **Issue:** #33  ·  **WBS:** 6.4c

## Design section
SYSTEM_DESIGN.md §4.6: | Demand (#33) | Sushant | Indicators, patterns, estimates; lower bounds
marked as such |. "`app/data.py` is the only module that reads data … **No business logic in the
app.**" WBS 6.4c: "Every figure on screen carries whether it is observed, simulated or planned.
Done when your part of the system can be explained from the screen alone."

Tables read (§3.2): `site_indicators`, `demand_estimate` (every bin, §3.4), `site_pattern`.

## Problem
The Map page shows one inferred rate per site, but nothing on screen says how busy a site was
measured to be, when in the day its demand falls, which usage pattern it belongs to, or that a
saturated site's figure is only a lower bound.

## Contracts touched
Reads `SiteIndicators`, `DemandEstimate`, `CandidateSite`. No contract change: the pattern is a
plain `site_id -> cluster` map and `cluster -> label` map, the shapes `find_patterns` and
`label_patterns` already return.

## Approach
- **`app/data.py`** (extended, defaults keep other pages unchanged): `AppData` gains
  `profiles: list[DemandEstimate]` (the `wd-`/`we-` bins), `patterns: dict[str, int]` and
  `pattern_labels: dict[int, str]`.
  - Postgres: `demand_estimate WHERE time_bin <> 'all'` and `site_pattern`.
  - Sample: the sample has `all` rows only, so, as with decisions, the analysis package is run
    over the sample's readings (`compute_indicators`, `compute_occupancy_by_bin`,
    `infer_demand`, `find_patterns`, `label_patterns`) over the readings' own window. The
    `all` estimates stay the sample's, so the Map and Allocation pages are unchanged.
- **`app/demand_view.py`**: pure functions over `AppData`, tested without Streamlit.
  - `figure(estimate)`: `"at least 5.31"` for a lower bound, `"2.51"` for a point, `None` when
    there is no estimate.
  - `demand_table(data, planning_area)`: one row per site; indicator columns named
    `(observed)`, pattern and demand columns `(inferred)`, the estimate's note as its method.
    `utilisation` stays `None` without supply (invariant 2).
  - `profile(data, site_id)`: the hourly rows for one site, weekday and weekend, with a
    lower-bound flag.
  - `pattern_rows(data)`: each cluster, its label and its sites.
  - `supply_counts(data)`: sites per `supply_state`, all four always present.
- **`app/pages/4_Demand.py`**: metrics by supply state, the per-site table, the patterns, and
  one site's hourly profile with lower-bound hours marked "at least".

## Verification
`tests/test_app_demand.py` on `from_sample()`: lower bounds read "at least"; every column is
labelled observed or inferred; no-supply sites keep `utilisation` `None`; profiles cover the
served sites' 24 `wd` bins; patterns match `find_patterns`; the page renders (`AppTest`).
`uv run ruff check . && uv run mypy optev && uv run pytest` pass.

## Open questions
- None blocking. Observed occupancy per bin is not stored in any table, so the profile shows
  inferred arrivals per bin, not occupancy.

## Checkpoint · 22 Oct 2026
- Works: `4_Demand.py` renders on the sample; `demand_view.py` with 9 tests in
  `tests/test_app_demand.py`; ruff and mypy clean.
- `AppData` gained `profiles`, `patterns`, `pattern_labels` with defaults, so the Map, Rules and
  Allocation pages are untouched. Postgres reads `demand_estimate` bins and `site_pattern`.
- Decision: on the sample, hourly bins and patterns come from running the analysis package over
  the sample readings (as decisions come from the rules engine); `all` stays the sample's, so the
  sample's daily figure and its hourly profile disagree. Real data has no such gap.
- Not verified against Postgres (no DATABASE_URL here). The six `test_graph_*` failures in the
  full run also fail on `main`; they are unrelated.
- Next: review by Gurneet (owner of `data.py`), then check the page on the loaded database.
