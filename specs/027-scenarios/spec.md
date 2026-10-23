# 027 · Scenarios: growth fit and projected demand

**Owner:** Shrey (B), Sushant (A, if he takes it)  ·  **Status:** approved 22 Oct 2026; part B built; part A amended and built 22 Oct 2026  ·  **Branch:** `shrey/28-scenarios` (from `main`)
**Issue:** #28 (6.1 · Scenario generation from the collected baseline; leads Sushant + Shrey)

## Design section
SYSTEM_DESIGN.md §4.3 (1.14 on `main`):

> ```python
> # optev/scenario/project.py
> def make_scenarios() -> list[Scenario]                                   # low, base, high
> def project(estimates: list[DemandEstimate], scenario: Scenario) -> list[DemandEstimate]
> ```
> Scenarios use `GROWTH` and `HORIZON_MONTHS`; #28 replaces the placeholder multipliers with a
> growth rate fitted to monthly EV registrations and checked against the LTA dashboard.
> Projected demand = observed estimate × multiplier, per site and bin, written to
> `scenario_demand` with its `scenario_id`, **never** to `demand_estimate`. Lower bounds stay
> lower bounds. [...] **Checked by.** Top-10 stability under ±20% growth, ±10% demand [...];
> back-cast error of the growth fit on recent months.

§3.2: `scenario` and `scenario_demand` are written by scenario, read by reasoning, graph, app.
§6 stage 3: top-10 stability ≥ 7 of 10; back-cast MAPE. Dataset Guide v2, F12: data.gov.sg
"New Registration of Cars by Make" (Month, Fuel Type, Number; ends May 2025); F13: LTA EV and
Charging Points Dashboard (total EVs, copied by hand).

## Problem
Nothing produces `scenario` or `scenario_demand`, so the allocator and the app can only use
`observed`, and `GROWTH_LOW/BASE/HIGH` (1.4 / 1.8 / 2.2) are uncited placeholders that the
design says must be replaced before the report. The issue's done-when: a scenario produces
demand the allocator can work from.

## Contracts touched
`Scenario`, `DemandEstimate` (`EstimateKind`), unchanged. Writes the §3.2 tables `scenario`
and `scenario_demand` only. Reads `demand_estimate` (Sushant's `write_estimates`, #14).

## Approach

### B · Projection (Shrey) — `optev/scenario/project.py`
1. `make_scenarios()`: `low`, `base`, `high` from `GROWTH` and `HORIZON_MONTHS`, provenance
   simulated, `baseline_window` = the collected week. Pure.
2. `project(estimates, scenario)`: every estimate × `scenario.growth_multiplier`, same
   `site_id`, `time_bin` and `kind` (a lower bound stays a lower bound), `note` says
   "simulated: × m (<scenario>)". Scales **arrival rates**, never occupancy. Pure.
3. **Writer (design gap):** `write_scenarios(conn, scenarios, demand) -> dict[str, int]`
   upserts `scenario` and replaces each scenario's `scenario_demand` rows. Needs a one-line
   design change (1.17, in this PR), as `write_estimates` got in 1.11. Plus `python -m optev.scenario.project`
   to read `demand_estimate`, project, write. **Run on Neon only with your OK.**
4. Stability check (§6 stage 3): `top10_stability` is evaluation, not this PR, unless you want it.

### A · Growth fit (Sushant) — offline, no new module
**Amended 22 Oct 2026, approved by Sushant.** The approved fit, `log r_m = a + g·m` on the
counts, gives g = 0.061/month (108% a year) and 116,000 new EVs a month by Dec 2030, against
a COE-capped market of about 4,500 cars a month. So the fit is on the **share** instead.
- Script `specs/027-scenarios/fit/fit.py` (precedent: `specs/013-lag-demand/prototype/`),
  reading the data.gov.sg file from `data/raw/registrations/` (gitignored; never committed).
  data.gov.sg reports electric cars from Jul 2022 only, so the fit has 35 months, not 36.
- Monthly electric share of new cars `s_m`; fit `logit s_m = a + b·m` by least squares.
- Registrations per month = fitted share × `T`, new cars a month (LTA M03, Jan–Aug 2026).
- `E0` = 72,067 electric cars on 31 Aug 2026 (LTA M09, cars only). Fleet at the collected
  week `E_B = E0 + r̂(Sep 2026)`; at the horizon `E_H = E_B + Σ r̂` over Oct 2026–Dec 2030
  (51 months). No scrappage: Jan–Aug 2026 the fleet grew by 99.7% of registrations.
  **Multiplier = E_H / E_B**, assuming charging demand scales with the electric-car fleet.
- `low` / `high`: `b` at the bounds of its 80% confidence interval (t, 33 df) **and** `T` at
  the lowest / highest month of 2026; `base`: point fit, mean `T`.
- Back-cast: fit on all but the last 12 months, predict their electric registrations, MAPE.
  Out of sample: predict Jan–Aug 2026 (LTA M03), which the fit never sees.
- Result into `assumptions.py` as cited values; sample `SCENARIOS` and `entities.json`
  regenerated to match (`test_design` ties them); design 1.18 (§3.5, §4.3, §9 #4).

## Verification
- B on `optev.sample`: three scenarios with the configured multipliers; `project` scales every
  rate exactly, keeps site, bin and kind, never returns occupancy; the projected `base`
  demand equals what the allocator tests already use; a live test of `write_scenarios` in a
  rolled-back transaction (skipped without `DATABASE_URL`).
- A: the fit script prints `g`, its CI, the three multipliers and the back-cast MAPE.
- ruff, mypy, `NEO4J_URI= uv run pytest` pass.

## Open questions
1. **Who does A?** It's assigned to Sushant. I'd message him first (draft in chat) and build B now.
2. **Writer name and the design PR (1.15)** for `write_scenarios`: OK?
3. **A's model:** fleet-ratio multiplier, log-linear fit on 36 months, 80% CI for low/high.
   Alternatives: fixed ±20% around base (matches the stability test) or LTA's 2030 target as
   `high`. Only matters if you end up doing A.
4. **Data after May 2025:** data.gov.sg stops there; the guide says take later months from
   DataMall's monthly statistics (manual). The fit works without them; add if time allows.

## Checkpoint · 22 Oct 2026
- **B works:** `optev/scenario/project.py`: `make_scenarios`, `project`, `write_scenarios`,
  `run`, and `python -m optev.scenario.project`. Design 1.17 adds `write_scenarios` (main had
  reached 1.16). 9 tests in `tests/test_project.py`: multipliers, scale-rates-only, lower
  bounds kept, observed list untouched, projected `base` gives the allocator the same plan as
  hand-scaled demand, writer SQL order and no write to `demand_estimate`, CLI without a
  database; live write test rolls back (not run here). ruff, mypy, pytest: 324 passed.
- **Not run on Neon:** `python -m optev.scenario.project` waits for Shrey's OK.
- **A open:** growth fit; Sushant asked first. Multipliers stay the placeholders until then.
- Renumbered 026 → **027** (22 Oct): 026 is taken by #87.

## Checkpoint · 22 Oct 2026 (part A)
- **Fit works:** `uv run python ../specs/027-scenarios/fit/fit.py` from `SystemCode/`. Share
  11.7% → 42.4% (Jul 2022–May 2025), b = 0.0522/month, 80% CI [0.0480, 0.0565].
  Back-cast MAPE 8.3% (last 12 months); Jan–Aug 2026 predicted 21,586 vs LTA 23,028 (−6.3%).
- **Multipliers:** low 3.26, base 3.65, high 3.99 (fleet Dec 2030 243k / 274k / 301k; share
  of new cars 95–97% by then). In `assumptions.py`; design 1.18; sample regenerated.
- **Decision:** share not counts (counts outgrow the market); low/high vary market size too,
  since the slope CI alone is narrow (3.52–3.67 at fixed T).
- **Caveat for the report:** assumes public charging demand scales with the fleet. More home
  and condo charging would make this an upper bound. The low–high spread (±9%) is inside the
  ±20% stability test.
- **Next:** rerun `python -m optev.scenario.project` on Neon (with Shrey's OK) so
  `scenario_demand` carries the new multipliers; the report quotes the cited table in §3.5.
