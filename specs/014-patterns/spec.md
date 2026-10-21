# 014 · Pattern discovery across sites and time of day

**Owner:** Sushant  ·  **Status:** approved  ·  **Branch:** `sushant/15-patterns` (from `sushant/14-lag-demand`)  ·  **Issue:** #15

## Design section

`SYSTEM_DESIGN.md` 1.7, §4.2 Stage 2 · Measurement & inference (`analysis/`):

```python
# optev/analysis/patterns.py
def find_patterns(occupancy: dict[str, dict[str, float]]) -> dict[str, int]   # site -> cluster
```

> 3. **Patterns (#15).** k-means (scikit-learn) on each site's 48-value occupancy profile
>    (`wd-00…wd-23`, `we-00…we-23`), min-max normalised per site; k from 3 to 6, chosen by
>    silhouette score; fixed `random_state`. Write `site_pattern` with a human label per cluster
>    (e.g. "evening residential").

Also binding: §2.2 (scikit-learn for k-means), §3.4 (time bins), §5 (`find_patterns` runs after
`infer_demand`), §6 (patterns: silhouette, target ≥ 0.5).
Table written: `site_pattern` (`002_pipeline.sql`: `site_id` PK → `candidate_site`,
`cluster integer >= 0`, `label text`).

Issue #15 adds: "Done when each site has a shape and the grouping holds when refitted on days
held back." The design does not define that check (open question 2).

## Problem

Nothing groups sites by when in the day they are busy, so the app and the graph cannot say
"this site behaves like these others", and `site_pattern` is empty.

## Contracts touched

Reads the `occupancy_by_bin` dict (site → time bin → mean occupancy), as `infer_demand` does.
Produces `dict[str, int]`. `site_pattern` has no contract (the label is design open decision 5);
no contract change.

## Approach

- `find_patterns(occupancy)`: one 48-value vector per site, in `wd-00…we-23` order; `all` is
  ignored. Each vector min-max normalised per site. KMeans for k = 3…6 (only k < number of
  sites), `random_state` fixed, `n_init=10`; keep the k with the best silhouette. Returns
  site → cluster, clusters numbered by first appearance in sorted site order so the ids are
  stable across runs.
- Missing bins and flat profiles: see open questions 4 and 5.
- Labels and writing `site_pattern`: see open questions 3 and 6.
- Add `scikit-learn` to `pyproject.toml` dependencies (named by §2.2, not installed today).
- Pure functions, no Postgres, under ~150 lines.

## Verification

`uv run ruff check . && uv run mypy optev && uv run pytest`. New `tests/test_patterns.py`:
- Every site in `occupancy` gets a cluster; clusters are 0…k−1 with 3 ≤ k ≤ 6.
- Deterministic: two runs give the same dict.
- Synthetic profiles with known shapes (evening, daytime, overnight, flat) are recovered.
- On the sample: residential (HDB, evening) and commercial (public, daytime) sites land in
  different clusters; silhouette recorded here, not asserted against 0.5 (finding 1).
- Held-back days: the check agreed in open question 2.
- `write_patterns` (if agreed) against Postgres, rolled back, only when `DATABASE_URL` is set.

## Findings from a prototype on the sample (before any code)

11 served sites, 2 weekdays, so only the 24 `wd` bins exist; no gaps in those bins.

| k | Silhouette | Refit on day 1 vs day 2 (ARI) | Day 2 assigned to day-1 centroids, agreement |
|---|---|---|---|
| 2 | 0.20 | 0.53 | 100% |
| 3 | 0.15 | 0.20 | 100% |
| 4 | 0.15 | 0.07 | 91% |
| 5 | 0.13 | | |
| 6 | 0.10 | | |

1. **Silhouette is far below the §6 target of 0.5 at every k.** The sample was generated with
   only two shapes (residential evening, commercial daytime), and 11 sites is too few. The
   target can only be judged on the real week (hundreds of sites).
2. **The design's k range (3–6) excludes the sample's true k (2).** k = 2 scores best.
3. **Saturated sites lose their shape.** S-03 and S-04 (utilisation 0.90, 0.95) are near 1 all
   day; min-max normalising stretches the noise, and their "peak" lands at 01:00–02:00.
4. **"Holds when refitted" depends on how it is measured.** Refitting from scratch on held-back
   days agrees poorly once k ≥ 3 (ARI 0.20), but assigning held-back days to the fitted centroids
   agrees 91–100%.

## Decisions (20 Oct 2026, Sushant: recommended answers accepted, applied as design 1.8, renumbered 1.12 on merging main)

1. **k stays 3–6.** Fewer than 4 sites to cluster raises `ValueError` (silhouette needs
   k < number of sites). Ties in silhouette go to the smaller k.
2. **Held-back check:** `holdout_agreement(train, held) -> float` fits on `train`, assigns the
   `held` profiles to the fitted centroids and returns the share of common sites that keep
   their cluster; §6 target ≥ 0.8. On the real week: train `[7 Oct 14:00, 11 Oct 00:00)`
   (Wed–Sat), held back `[11 Oct 00:00, 14 Oct 11:00)` (Sun–Tue), SGT; both contiguous, so
   `occupancy_by_bin` serves both, and each holds weekdays and one weekend day. A full refit's
   ARI is recorded in the spec, not a target.
3. **Labels:** `label_patterns(occupancy, patterns) -> dict[int, str]`, from each cluster's mean
   normalised profile: `flat` when it is zero everywhere; else the band of its weekday peak
   (`overnight` 00–05, `morning` 06–11, `daytime` 12–17, `evening` 18–23) + `" peak"`, then
   `", busier on weekdays"` or `", busier on weekends"` when the halves' means differ. No
   threshold, so nothing new in `optev.assumptions`. Duplicate labels get `" (cluster n)"`.
4. **`write_patterns(conn, patterns, labels) -> int`**, upsert on `site_id`, no commit, like
   `write_estimates`. Stale rows are left, as every other analysis writer does (§2.3 rule 6
   holds: a re-run gives the same rows).
5. **Missing bins** are filled with the site's mean over the same half, or over all its bins
   when a half is missing. A site with fewer than `MIN_COVERAGE` × 48 bins gets no cluster.
6. **Flat profiles** normalise to zeros and are clustered as usual.
7. **No centroid table.** Centroids only make labels.
8. **`pattern_silhouette(occupancy, patterns) -> float`** is added so §6's metric has a named
   source for the evaluation harness, rather than reaching into private profile code.

## Open questions (answered above)

1. **k range.** Keep 3–6 as designed (recommended: the real week has hundreds of sites, and the
   sample's two shapes are an artefact of the generator), or widen to 2–6?
2. **Held-back-days check (issue #15).** Proposed: fit on the week minus held-back days, assign
   the held-back days' profiles to the fitted centroids, and report the share of sites that keep
   their cluster, target ≥ 0.8; ARI of a full refit reported alongside. This adds a §6 row
   (design 1.12). Which days to hold back on the real week (e.g. one weekday and one weekend day)?
3. **Labels.** The design wants "a human label per cluster" but not how. Proposed: a
   deterministic rule on the cluster centroid: the peak band of its weekday half
   (`overnight` 00–05, `morning` 06–11, `daytime` 12–17, `evening` 18–23), plus `flat` when the
   centroid's range is small, plus `weekend` / `weekday` when one half is clearly busier. Site
   kind ("residential") is not used, since a cluster mixes kinds. Exposed as
   `label_patterns(occupancy, patterns) -> dict[int, str]` (a new function: design 1.12).
4. **Writing `site_pattern`.** No writer is defined. Proposed
   `write_patterns(conn, patterns, labels) -> int` in `patterns.py`, upsert on `site_id`, no
   commit, like `write_estimates` (design 1.12). Stale rows for sites no longer clustered: leave
   them, or delete first?
5. **Missing bins.** On the sample and with weekend-only gaps, a site may lack some of the 48
   bins. Proposed: fill a missing bin with the site's mean over its bins of the same half
   (`wd`/`we`), and the overall mean if a half is wholly missing; sites with fewer than half the
   48 bins are left out (no row). On the sample that means clustering on 24 `wd` bins plus 24
   filled `we` bins, which carry no shape.
6. **Flat profiles** (max = min, e.g. a site at 0 all week): normalise to all zeros and cluster
   as usual (recommended), or leave out?
7. **"Demand shape per group" (issue).** Neither the design nor `site_pattern` stores a cluster's
   centroid, and #16 spreads `all` by site kind, not cluster. Proposed: no new table; the
   centroid is used only to make the label. Say if #16 or the app should use cluster shapes
   instead.

## Checkpoint · 20 Oct 2026

- **Works:** `optev/analysis/patterns.py` with `find_patterns`, `label_patterns`,
  `pattern_silhouette`, `holdout_agreement`, `write_patterns`; `tests/test_patterns.py` (12 tests,
  one live). ruff, mypy, pytest pass; the live `write_patterns` test passed on Neon, rolled back.
- **Design 1.12** applied to `SYSTEM_DESIGN.md` §4.2 step 3, §6 and the change log; needs a
  CODEOWNER's review in the PR. `scikit-learn` added to `pyproject.toml` and `uv.lock`.
- **Finding 5 (with the agreed gap fill):** the sample's `we` half is filled with each site's
  mean, which carries the normalised level. k = 3 (silhouette 0.30) then sets apart the two
  saturated sites (S-03, S-04, "overnight peak") and the idle S-14 ("daytime peak"), and puts
  the daytime public sites S-13, S-23 with the evening HDB sites ("evening peak"). The real
  week has weekend bins, so this should not recur there; check it when it runs.
- **Held-back day on the sample:** fit on day 1, assign day 2: 100% of 10 common sites keep
  their cluster (S-05 has no day-1 bins); a full refit's ARI is 0.60.
- **Not this issue's fault:** 5 graph tests fail locally because the Neo4j Aura host does not
  resolve, as in spec 012.
- **Branch** is cut from `sushant/14-lag-demand` (stacked on #13 and #14); rebase once they merge.
- **Next:** PR for #15; run `holdout_agreement` and `pattern_silhouette` on the real week with
  the §4.2 windows; the pipeline (#35) calls `find_patterns` → `label_patterns` → `write_patterns`.
