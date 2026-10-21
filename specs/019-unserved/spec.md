# 019 · Demand at sites with no chargers

**Owner:** Sushant  ·  **Status:** approved  ·  **Branch:** `sushant/16-unserved`  ·  **Issue:** #16

## Design section

`SYSTEM_DESIGN.md` 1.12, §4.2 Stage 2 · Measurement & inference (`analysis/`):

```python
# optev/analysis/unserved.py
def estimate_unserved(sites: list[CandidateSite], observed: list[DemandEstimate],
                      context: dict[str, dict[str, float]]) -> list[DemandEstimate]
```

> 4. **Sites with no chargers (#16).** Supervised regression. Training rows: sites with
>    `supply_active` and an `all` estimate of `kind = point` (lower-bound labels are excluded in
>    version 1; a censored regression is the stated improvement). Features: mean car park
>    occupancy at night (wd-00…wd-05) and by day (wd-09…wd-17), total lots, site kind, land use,
>    amenities nearby, residents in area, distance to the nearest charging point. Models: linear
>    regression as the baseline, then scikit-learn `HistGradientBoostingRegressor`; keep the
>    better under leave-area-out validation. Predict `all` for `no_supply` sites, then spread it
>    across bins with the mean normalised profile of training sites of the same kind.
>    `method = regression`.

Also binding: §3.4 (bins, `all` formula), §5 (pipeline runs `estimate_unserved` after
`find_patterns`), §6 (regression: MAE and Spearman ρ on hidden sites and hidden areas against the
planning-area average; target beat baseline, ρ ≥ 0.5). Reads `site_context`
(`land_use`, `residents_in_area`, `amenities_nearby`, `nearest_point_m`), `car_park_reading`,
`demand_estimate`, `site_indicators`. Writes `demand_estimate` with `method = 'regression'`.

## Problem

`infer_demand` (#14) gives a rate only where chargers exist. Sites with no chargers, the ones
worth building at, have no estimate, so they cannot be ranked or allocated to.

## Contracts touched

Reads `CandidateSite` (`kind`, `total_lots`, `planning_area`) and `DemandEstimate` (the queueing
rows, which carry `kind`). Produces `DemandEstimate` (`kind = point`, basis in `note`). `method` is
a table column, set when writing, as in #14. No contract change.

## Approach

`optev/analysis/unserved.py`, under 300 lines, pure functions tested on the sample plus a thin
Postgres layer, the same split as `indicators.py`.

- **Training rows:** a site is a training row when `observed` has an `all` row of
  `kind = point` for it and its supply is active. `estimate_unserved` gets no `SiteIndicators`,
  so "supply_active" is taken from the caller passing only those sites' estimates (see Q2).
- **Feature vector** per site: `context[site_id]` (car park occupancy night/day, residents,
  amenities, nearest point, land use one-hot) + `total_lots` + site kind one-hot from
  `CandidateSite`. A missing key is NaN: HGB takes NaN natively; linear regression gets the
  training median (Q3).
- **Model choice:** leave-area-out (one fold per planning area among the training rows; MAE).
  Fit both, keep the lower MAE, refit it on all training rows, `random_state = 0`. Predictions
  clipped at 0.
- **Output per `no_supply` site:** `all` = prediction, `kind = point`; bins = prediction × the
  mean normalised profile (per-bin arrivals ÷ that site's `all`) of training sites of the same
  kind, falling back to all training sites when none share the kind (Q4). The profile's §3.4
  average is 1, so the bins average back to `all`. `note` records the basis, e.g.
  `regression: hgb, 9 sites, leave-area-out MAE 0.85/h; profile from 7 hdb_car_park sites`.
- **Postgres layer (Q1):** `unserved_context(window_start, window_end)` builds `context` from
  `site_context` and `car_park_reading`; `write_unserved(conn, estimates)` upserts
  `demand_estimate` with `method = 'regression'`, no commit, like `write_estimates`.

## Verification

`uv run ruff check . && uv run mypy optev && uv run pytest`. New `tests/test_unserved.py` on the
sample (indicators → `infer_demand` → `estimate_unserved`, context built from
`car_park_readings()`, kind and lots; nearest point from coordinates):
- every `no_supply` site gets `all` plus the training bins, `kind = point`; no other site does;
- the S-04 lower bound is not a training row; `supply_idle` S-14 is not either;
- bins average back to `all` by §3.4; a kind with no training sites uses the overall profile;
- deterministic: two runs give identical output; predictions ≥ 0; missing features do not fail;
- the note names the model kept and its leave-area-out MAE;
- `write_unserved` against Postgres, rolled back, only when `DATABASE_URL` is set.
- MAE and ρ against `truth()` are measured and recorded here, not asserted (finding 2).

## Findings from a prototype on the sample (before any code)

Features available on the sample: car park occupancy night/day (from `car_park_readings()`),
total lots, kind, distance to the nearest station. No land use, residents or amenities.

| Model | Leave-area-out MAE (train) | MAE on 19 no-charger sites | Spearman ρ |
|---|---|---|---|
| Linear | 1.85 | 4.00 | −0.10 |
| HGB (`min_samples_leaf=2`) | 0.85 | 1.08 | 0.57 |
| Planning-area average | — | **0.76** | — |

1. **Only 9 training rows, in 2 areas** (S-01, 02, 03, 05, 11, 13, 19, 21, 23). Leave-area-out is
   two folds. HGB's default `min_samples_leaf = 20` makes it a constant on 9 rows (Q5).
2. **Neither model beats the area average on the sample, and it cannot be expected to:** the
   generator draws served sites' demand by hand and no-charger sites' truth from
   `0.4 + 2.2 × peak car park occupancy × lots/500`, so the two groups share no relationship to
   learn. The §6 test is meaningful only on the real week. Fixing the generator is out of scope
   for #16 (Q6).

## Open questions (answered 21 Oct 2026, Sushant: as proposed for 1–6; 7 below)

1. **Design additions (1.13).** §4.2 defines only `estimate_unserved`. The pipeline also needs the
   `context` built from Postgres and the rows written. Propose `unserved_context(window_start,
   window_end) -> dict[str, dict[str, float]]` and `write_unserved(conn, estimates) -> int`, plus
   context keys `cp_occupancy_night`, `cp_occupancy_day`, `residents_in_area`,
   `amenities_nearby`, `nearest_point_m`, `land_use:<VALUE>` (1.0). OK to add to §4.2?
2. **Training filter.** `estimate_unserved` sees estimates, not supply state. `infer_demand`
   already writes rows only for `supply_active`/`supply_idle`; idle sites have near-zero demand
   and would teach the model "no demand". Propose: the caller passes `observed` filtered to
   `supply_active` sites (pipeline does it from `site_indicators`), and the function documents it.
   Alternative: change the signature to take `indicators` too, which is a design change.
3. **Missing features** (amenity sites have no car park, so no occupancy or lots): NaN for HGB,
   training median for linear. OK?
4. **Profile fallback** when no training site shares the kind (hawker, community, petrol on the
   sample and likely on the real data): overall training profile. OK?
5. **HGB settings:** `min_samples_leaf` must drop for ~10–60 rows. Propose a module constant
   `MIN_SAMPLES_LEAF = 2` with a comment (a model setting, not a declared assumption), or add it
   to `optev.assumptions`?
6. **The issue asks to use saturated sites as lower bounds; design 1.12 excludes them in version
   1.** I follow the design (only S-04 on the sample is excluded) and note the censored model as
   the follow-up. Confirm.
7. **Coverage gap:** the issue says "every candidate has an estimate". `unobserved` sites (feed gap)
   get neither queueing nor regression rows under the design. Predict them too, or leave them
   for the rules engine to defer?

## Decisions (21 Oct 2026, Sushant)

1. Q1–Q6 as proposed: `unserved_context` and `write_unserved` added as design 1.13; the caller
   passes `supply_active` + `no_supply` sites and only `supply_active` estimates; median
   imputation for linear, NaN for HGB; overall profile when no training site shares the kind;
   `MIN_SAMPLES_LEAF = 2` is a module constant; lower bounds stay out of training in version 1.
2. Q7: `unobserved` sites get no estimate; the rules engine defers them.
3. Found while building: a feature with no value in any fitted row is dropped before fitting,
   because HGB cannot bin an all-NaN column (the sample has no site context at all).
4. Training sites in fewer than two planning areas raise `ValueError`: leave-area-out needs two.
   Ties in leave-area-out MAE keep the linear baseline.

## Checkpoint · 21 Oct 2026

- **Works:** `optev/analysis/unserved.py` (`estimate_unserved`, `unserved_context`,
  `write_unserved`); `tests/test_unserved.py` (10 tests, one live). ruff, mypy pass; pytest
  passes except 10 graph tests that fail because `.env` holds a placeholder Neo4j host, as on
  `main`. The live `write_unserved` and `_CONTEXT_SQL` test passed on Neon, rolled back.
- **Design 1.13** applied to §4.2 and the change log; needs a CODEOWNER's review in the PR.
- **Measured on the sample (19 no-charger sites):** HGB kept (leave-area-out MAE 0.85/h vs
  linear 1.85); MAE 1.08/h, ρ 0.57 against `truth()`; planning-area average MAE 0.76, ρ 0.32.
  ρ meets the §6 0.5 target, MAE does not beat the baseline; finding 2 explains why the
  sample cannot show it. The real test is the collected week, via the harness (#36–#39).
- **Not built:** the pipeline call (#35) and filtering by `site_indicators` there.
- **Next:** PR for #16; follow-ups: censored regression on lower bounds (issue's ask), and a
  sample generator where served and no-charger demand share one relationship.

## Findings on the collected week (21 Oct 2026, read-only; nothing written to Neon)

Window `[7 Oct 14:00, 14 Oct 11:00)` SGT: 1851 `supply_active` sites in 36 planning areas, all
with a point `all` (none reaches `RELIABLE_UP_TO`), 983 `no_supply`, 91 idle, 7 unobserved.

1. **`nearest_point_m` is 0 m at the training sites and 72–385 m (p10–p90) at the no-charger
   sites.** A served site's nearest charging point is its own charger. The linear model
   extrapolated on it and predicted 0 arrivals at 424 of 983 no-charger sites (mean 0.14/h
   against 0.65/h on training sites). Leave-area-out cannot see this: the feature never
   varies among training rows.
2. Without it, validation is unchanged and no prediction is 0 (mean 0.33/h):

| Leave-area-out, 1851 sites | MAE (arrivals/h) | Spearman ρ |
|---|---|---|
| Linear (kept) | 0.352 | 0.477 |
| HGB | 0.360 | 0.448 |
| Held-out area predicted by the other areas' mean | 0.394 | −0.27 |
| Hidden site predicted by its own area's average (§6 baseline) | 0.376 | 0.21 |

The model beats both baselines on MAE; ρ is just under the §6 0.5 target.

## Decision (21 Oct 2026, Sushant)

5. **Drop distance to the nearest charging point from the regression features** (design 1.16,
   numbered after #58 and #72's 1.14 and 1.15). `nearest_point_m` is ignored if a context
   carries it; the rules keep it as a fact. Sample results are unchanged by it.

## Checkpoint · 21 Oct 2026 (2)

- **Works:** `NUMERIC` and `_CONTEXT_SQL` without `nearest_point_m`; new test that a context
  with the distance gives the same estimates. Branch `sushant/16-drop-nearest-point`, stacked
  on `sushant/16-spec-number` (#78).
- **Not done:** `site_indicators` and `demand_estimate` in Neon are still empty; the pipeline
  (#35) writes them. ρ 0.477 misses the 0.5 target; spec 018 (censored, on hold) won't help on
  this week, since it has no lower bounds.
- **Next:** owner review of design 1.16; then post the table above for the report.
