# 013 · Lag-aware demand inversion

**Owner:** Sushant  ·  **Status:** decided, not adopted (record)  ·  **Branch:** `sushant/14-lag-demand` (from `sushant/14-demand`)  ·  **Issue:** #14 follow-up (spec 012, decision 3)

## Design section

`SYSTEM_DESIGN.md` 1.7, §4.2 step 2 (as amended by spec 012):

> 2. **Demand (#14).** Erlang loss model (Erlang B). For each site and **each time bin**:
>    offered load `a` is the value giving the observed occupancy on `c` active connectors
>    (bisection; occupancy rises monotonically in `a`); arrivals per hour =
>    `a ÷ MEAN_SESSION_HOURS`. If occupancy ≥ `RELIABLE_UP_TO`, report the arrivals that give
>    exactly `RELIABLE_UP_TO`, with `kind = lower_bound`. Write per-bin rows plus `all`, the
>    §3.4 average of the per-bin arrivals (never an inversion of whole-window occupancy). `all`
>    is a lower bound when the site's window `utilisation` ≥ `RELIABLE_UP_TO`; per-bin rows keep
>    their own kind. `method = queueing`.

Also binding: §4.4. The allocator's objective sums `w_bin × λ_bin × (B(c, a_bin) − B(c + x, a_bin))`
per bin, so the hourly shape of `λ`, not only `all`, decides where points go. §6: queueing MAPE
against known demand. §3.5: `MEAN_SESSION_HOURS` (3.0 h, varied ±30% in sensitivity tests).

## Problem

Inverting each bin's occupancy as if that hour were in steady state ignores that a session
started in hour h keeps its connector busy for about the next `MEAN_SESSION_HOURS`. Occupancy
therefore peaks after arrivals do, and the per-bin profile comes out late and too flat. On the
sample, per-bin error is about 52% (weighted absolute percentage error, WAPE). The allocator
reads that profile.

## What was tested

Prototype in `prototype/` (scratch scripts, not package code; they use numpy and scipy, which
the project does not depend on yet). Run from `SystemCode/`:

```bash
uv run --with numpy --with scipy python ../specs/013-lag-demand/prototype/proto.py
```

```bash
uv run --with numpy --with scipy python ../specs/013-lag-demand/prototype/sample_check.py ../specs/013-lag-demand/prototype
```

```bash
uv run --with numpy --with scipy python ../specs/013-lag-demand/prototype/sim.py ../specs/013-lag-demand/prototype 5 20
```

Per-bin truth is `true_arrivals_per_hour` × the generator's normalised hourly weights. Two
test beds:

- the **sample**: 2 weekdays, 11 served sites;
- a **simulation** of the generator's own model (hourly arrival weights, its session-length mix,
  loss when full), on 6 sites like the sample's (c = 2–8, 0.9–4.3 arrivals/h). It runs 5
  weekdays × 20 seeds, which matches the real week's ~10 snapshots per `wd` bin, and 60
  weekdays × 4 seeds, which is nearly noise-free and isolates the bias.

Methods:

- **PSA (current):** invert each bin's occupancy on its own.
- **Shift k h:** estimate bin h from the occupancy of bin h + k.
- **Smoothed:** 1-2-1 weights over neighbouring hours, then invert.
- **MOL deconvolution and MOL fit:** the modified-offered-load approximation for time-varying
  loss systems. The offered load is arrivals convolved with the session survival function;
  either invert-then-deconvolve, or fit arrivals in occupancy space with a smoothness penalty.
  Tried with an exponential and a fixed-length session kernel.

## Results

Per-bin WAPE · `all` MAPE · correlation of the hourly profile with truth. Sites below
`RELIABLE_UP_TO`.

| Method | Sample (2 days) | Simulated week (5 wd) | Simulated 60 wd (bias only) |
|---|---|---|---|
| PSA (current) | 52% · 14% | 41% · 14% · r 0.76 | 24% · 6% · r 0.91 |
| Smoothed | — | 33% · 11% · r 0.84 | 22% · 6% · r 0.93 |
| Shift 1 h | — | 38% · 14% · r 0.78 | 15% · 6% · r 0.96 |
| **Smoothed + shift 1 h** | **41% · 11%** | **29% · 11% · r 0.86** | **14% · 6% · r 0.97** |
| Shift 2 h | — | 42% · 14% · r 0.70 | 24% · 6% · r 0.88 |
| MOL fit, fixed-length kernel | 43% · 16% | 31% · 12% · r 0.81 | 20% · 5% · r 0.93 |
| MOL deconvolution, fixed-length kernel | 49% · 15% | 40% · 14% · r 0.77 | 21% · 6% · r 0.91 |
| MOL, exponential kernel | 47–117% | 46–50% | 38–40% |

Sessions shorter or longer than declared (true session × 0.7 / × 1.3, `MEAN_SESSION_HOURS`
kept at 3.0), simulated week:

| Method | × 0.7 | × 1.3 |
|---|---|---|
| PSA (current) | 38% · 23% (bias −23%) | 52% · 27% (bias +27%) |
| Smoothed + shift 1 h | 33% · 29% (bias −29%) | 41% · 23% (bias +23%) |
| MOL fit, fixed-length kernel | 37% · 33% | 40% · 20% |

## Findings

1. **The lag is real, but it only bends the profile.** A circular lag keeps the daily total, so
   `all` hardly moves under any lag fix (6% in every row of the 60-day column). What the lag
   damages is the hourly shape the allocator weights: per-bin error goes from 24% to 14% when
   the lag is removed.
2. **At one week of data, noise matters as much as lag.** With 2 snapshots per hour per day,
   bin occupancy is noisy, and the convex inversion turns that noise into a +6% bias in `all`.
   Smoothing removes that bias (+6.4% → 0.0%) and brings `all` MAPE from 14% to 11%.
3. **The simple fix beats the principled one.** MOL needs the *shape* of the session-length
   distribution, not just its mean. With the wrong shape (exponential) it is worse than doing
   nothing, and no dataset gives us the shape. Smoothing + shift needs only
   `MEAN_SESSION_HOURS`.
4. **The best shift is about half a session, rounded down:** 1 h for 3 h sessions. A 2 h shift
   is worse than none.
5. **`MEAN_SESSION_HOURS` dominates everything else.** A 30% error in session length moves
   `all` by 23–29%, against the 3-point gain from this spec. No inversion method fixes a wrong
   session length. Issue #14 says to "estimate mean session length from observed episodes";
   the design fixes it at 3.0 h instead. Measuring it from the real feed (runs of OCCUPIED
   snapshots per connector) is the bigger win, with two caveats: runs are censored at 30
   minutes, and `occupied` groups several conditions. That is a separate proposal (open
   question 3).
6. **The §6 10% target is still not met** at one week (11%), though it is close.

## Recommendation

Replace the per-bin inversion with **smoothed + shift**. For each site, separately within the
weekday bins and within the weekend bins (circular over the 24 hours):

1. smooth occupancy as `occ'(h) = (occ(h−1) + 2·occ(h) + occ(h+1)) / 4`;
2. estimate bin h from `occ'(h + k)`, with `k = floor(MEAN_SESSION_HOURS / 2)` hours;
3. invert as now. A bin is a `lower_bound` when `occ'(h + k)` ≥ `RELIABLE_UP_TO`.

`all` and its lower-bound rule are unchanged. No new dependency, no new table, no contract
change, about 15 lines in `demand.py`. The 1-2-1 weights and the half-session shift become part
of the method text in the design, as bisection is. The shift is derived from a declared value,
so no new assumption is needed.

Design change (1.8), §4.2 step 2, replacing its first sentence:

> For each site and **each time bin**: occupancy is first smoothed over neighbouring hours
> (weights 1-2-1, circular within weekday bins and within weekend bins) and read
> `floor(MEAN_SESSION_HOURS ÷ 2)` hours later, because a session keeps its connector busy for
> the hours after it starts; offered load `a` is the value giving that occupancy on `c` active
> connectors …

Tests to add: the shift and smoothing on hand-built profiles; and on the sample, per-bin WAPE
below the current method's and `all` MAPE ≤ 12% (measured 11%).

## Open questions

1. **Adopt smoothed + shift (design 1.8)?** The alternative is to keep spec 012's method and
   only report the lag in the write-up.
2. **Wrapping weekday 23:00 to 00:00.** Circular smoothing treats wd-23 as next to wd-00, which
   holds Mon–Thu nights but not Friday night, and the same applies to Sunday night for
   weekends. Accepting this is simpler than splitting by night; the effect is one bin's
   neighbour on one night in five.
3. **Measure `MEAN_SESSION_HOURS` from the feed** (finding 5): a new spec and a design change to
   §3.5, raised with the team rather than folded into this one.

## Decision (19 Oct 2026, Sushant)

**Not adopted.** Spec 012's per-bin inversion stays and the design stays at 1.7. This spec is
kept as the record of the lag: the write-up reports that the per-bin profile runs late and flat,
quoting the numbers above, and that `all` is barely affected. Open questions 2 and 3 are closed
with it; finding 5 (session length) remains open for the team to raise on its own.
