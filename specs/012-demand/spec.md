# 012 · Demand inference from occupancy

**Owner:** Sushant  ·  **Status:** approved  ·  **Branch:** `sushant/14-demand` (from `sushant/13-indicators`)  ·  **Issue:** #14

## Design section

`SYSTEM_DESIGN.md` 1.6, §4.2 (amended to 1.7 by this spec, see Decisions) Stage 2 · Measurement & inference (`analysis/`):

```python
# optev/analysis/demand.py
def erlang_b(c: int, a: float) -> float
def invert_occupancy(c: int, occupancy: float) -> float          # arrivals per hour
def infer_demand(indicators: list[SiteIndicators],
                 occupancy: dict[str, dict[str, float]]) -> list[DemandEstimate]
```

> 2. **Demand (#14).** Erlang loss model (Erlang B). For each site and **each time bin**:
>    offered load `a` is the value giving the observed occupancy on `c` active connectors
>    (bisection; occupancy rises monotonically in `a`); arrivals per hour =
>    `a ÷ MEAN_SESSION_HOURS`. If occupancy ≥ `RELIABLE_UP_TO`, report the arrivals that give
>    exactly `RELIABLE_UP_TO`, with `kind = lower_bound`. Write per-bin rows plus `all`;
>    `all` is a lower bound if any bin is. `method = queueing`. **Estimate per bin, never once
>    per whole window**: the sample shows a whole-window inversion underestimates busy sites by
>    30–40% because demand peaks in the evening.

Also binding: §3.4 (`all` = `(5 × mean of wd bins + 2 × mean of we bins) / 7`), §3.5
(`MEAN_SESSION_HOURS`, `RELIABLE_UP_TO`), §6 (queueing: MAPE by occupancy band against
`truth()`, baseline occupancy alone, target ≤ 10% below `RELIABLE_UP_TO`).
Table written: `demand_estimate` (`002_pipeline.sql`, PK `site_id, time_bin`, `method` column).

## Problem

Indicators give a level (share of time busy); the allocator needs a rate (drivers per hour),
including the drivers turned away when every point was busy. Nothing produces
`DemandEstimate` from observed occupancy yet, so #16, #28 and the allocator have no input.

## Contracts touched

Reads `SiteIndicators` (for `c = active_connectors` and `supply_state`) and the
`occupancy_by_bin` dict. Produces `DemandEstimate`. `method` is a table column, not a contract
field, so it is set when writing. No contract change.

## Approach

- `erlang_b(c, a)`: the standard recurrence `B(0)=1, B(k) = a·B(k−1) / (k + a·B(k−1))`.
  Carried occupancy per connector `ρ(a) = a·(1 − B(c, a)) / c`, increasing in `a`, bounded by 1.
- `invert_occupancy(c, occ)`: bisection on `a` for `ρ(a) = occ`, then `a ÷ MEAN_SESSION_HOURS`.
  Raises `ValueError` for `c < 1` or `occ ∉ [0, 1)`; `occ = 0` → 0. Callers cap at
  `RELIABLE_UP_TO` first, so 1.0 never reaches it.
- `infer_demand`: for every site whose `supply_state` is `supply_active` or `supply_idle` and
  that has bins in `occupancy`, one row per `wd-HH`/`we-HH` bin (cap at `RELIABLE_UP_TO` →
  `lower_bound`), then `all` from those per-bin arrivals by the §3.4 formula (the mean of the
  bins present when only weekdays or only weekends were seen, as `_bins` does), `lower_bound`
  only when the site's `utilisation` ≥ `RELIABLE_UP_TO` (decision 1). The `all` that
  `occupancy` carries is ignored: inverting it would be the whole-window estimate the design
  forbids. `no_supply` and `unobserved` sites get no row here (#16 handles `no_supply`).
- `write_estimates(conn, estimates)`: upsert on `(site_id, time_bin)` with
  `method = 'queueing'`, no commit, like `write_indicators` (decision 2).
- Under 120 lines; no Postgres in the pure functions.

## Verification

`uv run ruff check . && uv run mypy optev && uv run pytest`. New `tests/test_demand.py`:
- `erlang_b`: known values (`B(1,a) = a/(1+a)`, `B(2,1) = 0.2`), and agrees with the sample
  generator's.
- `invert_occupancy` round-trips `ρ(a)` for c in 1..8; monotonic; rejects bad input.
- `infer_demand` on the sample: every served site gets 24 `wd` rows plus `all`; no rows for
  `no_supply`; per-bin `kind` follows the cap; only the one saturated site (S-04) has `all`
  `lower_bound`, and it is below truth.
- `write_estimates` against Postgres, rolled back, only when `DATABASE_URL` is set (as #13).
- Recovery against `truth()` (`true_arrivals_per_hour` is the daily mean because the
  generator's hourly weights average 1): per-bin MAPE beats the whole-window
  `sample.estimates` baseline on busy sites, and the measured MAPE is recorded here.

## Findings from a prototype on the sample (before any code)

Prototyped in a scratch script; the sample is 2 weekdays (Thu–Fri), so every `wd` bin has 4
snapshots and there are no `we` bins.

| Site | c | util | `all`, per bin | Error vs truth | Whole-window (`sample.estimates`) |
|---|---|---|---|---|---|
| S-01 | 4 | 0.76 | lower bound | −4% | −34% |
| S-02 | 8 | 0.77 | lower bound | −9% | −37% |
| S-03 | 2 | 0.90 | lower bound | −14% | −19% |
| S-04 | 2 | 0.95 | lower bound | −57% | −48% |
| S-05 | 6 | 0.52 | point | +11% | −7% |
| S-11 | 4 | 0.70 | lower bound | +7% | −31% |
| S-13 | 3 | 0.50 | lower bound | **+35%** | −32% |
| S-14 | 4 | 0.04 | point | +4% | +4% |
| S-19 | 4 | 0.76 | lower bound | −11% | −42% |
| S-21 | 2 | 0.69 | lower bound | **+17%** | −38% |
| S-23 | 6 | 0.59 | lower bound | **+30%** | −39% |

Mean absolute error below `RELIABLE_UP_TO` (all but S-04): **14%** per bin vs **28%** whole
window. Per-bin estimation halves the error, as the design expects, but misses the §6 10% target
on this sample.

1. **9 of 11 served sites come out `lower_bound`.** With 4 snapshots per bin, almost every busy
   site has one bin at ≥ 0.93, so "`all` is a lower bound if any bin is" flags them all. #16
   trains only on `all` rows with `kind = point`, which would leave it 2 training sites.
2. **Three of those "lower bounds" are above the truth** (S-13, S-21, S-23). Occupancy lags
   arrivals by about one session (3 h spans 6 bins), so a bin after the peak shows high
   occupancy from earlier arrivals; inverting it per bin overstates that bin, and the Erlang
   inversion is convex, so noise inflates the average. The label "the data supports no more
   than this" is then false.
3. On the real week, `wd` bins get ~10 snapshots and `we` bins ~4, so the noise falls for
   weekdays but not weekends; the lag stays.

## Decisions (19 Oct 2026, Sushant)

1. **`all` is a lower bound only when window `utilisation` ≥ `RELIABLE_UP_TO`**, the issue's
   wording, instead of "if any bin is". Per-bin rows keep their own kind. Design 1.7.
2. **`write_estimates(conn, estimates) -> int`** in `demand.py` writes `demand_estimate`.
   Design 1.7.
3. **Lag (finding 2) is accepted for version 1.** The per-bin steady-state inversion stays; the
   bias is recorded here and goes in the report. A lag-aware inversion (occupancy at hour h
   reflects arrivals over the previous `MEAN_SESSION_HOURS`) was tested in spec 013 and not
   adopted; the lag is reported in the write-up.
4. **`RELIABLE_UP_TO` stays 0.93.** Two weekdays and 11 sites are too few to measure it; it is
   measured on the real week by the evaluation harness (§6).

## Checkpoint · 19 Oct 2026

- **Works:** `optev/analysis/demand.py` with `erlang_b`, `invert_occupancy`, `infer_demand`,
  `write_estimates`; `tests/test_demand.py` (17 tests, one live). ruff, mypy, pytest pass; the
  live `write_estimates` test passed on Neon and was rolled back.
- **Design 1.7** applied to `SYSTEM_DESIGN.md` §4.2 (decisions 1 and 2); it needs a CODEOWNER's
  review in the PR.
- **Measured on the sample:** `all` MAPE below `RELIABLE_UP_TO` is about 14% per bin vs 28% whole
  window; only S-04 is a lower bound, and it is below truth. The §6 10% target is not met here.
- **Not this issue's fault:** `test_graph_live.py` and three tests in `test_graph_retrieve.py` fail
  locally because the Neo4j Aura host does not resolve, the same on `sushant/13-indicators`.
- **Branch** is cut from `sushant/13-indicators`, not `main`; rebase once #13 merges.
- **Next:** PR for #14; follow-up: a lag-aware inversion (decision 3); #16 can start from
  `all` rows with `kind = point`.
