# 026 · Scenarios: growth fit and projected demand

**Owner:** Shrey (B), Sushant (A, if he takes it)  ·  **Status:** draft, awaiting Shrey's OK  ·  **Branch:** `shrey/28-scenarios` (from `main`)
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
   design PR (1.15), as `write_estimates` got in 1.11. Plus `python -m optev.scenario.project`
   to read `demand_estimate`, project, write. **Run on Neon only with your OK.**
4. Stability check (§6 stage 3): `top10_stability` is evaluation, not this PR, unless you want it.

### A · Growth fit (Sushant, or Shrey if he passes) — offline, no new module
- Script in `specs/026-scenarios/fit/` (precedent: `specs/013-lag-demand/prototype/`), reading
  the data.gov.sg file into `data/raw/` (gitignored; never committed).
- Monthly new **electric** registrations `r_m`; fit `log r_m = a + g·m` on the last 36 months.
- Fleet now `E0` from the LTA dashboard (hand-copied, cited with its month). Fleet at the
  horizon `E_H = E0 + Σ_{m=1..51} r̂_m` (no scrappage: the EV fleet is young).
  **Multiplier = E_H / E0**, assuming charging demand scales with the EV fleet.
- `low` / `high`: `g` at the bounds of its 80% confidence interval.
- Back-cast: fit on all but the last 12 months, predict them, report MAPE.
- Result goes into `assumptions.py` as cited values ("fitted to data.gov.sg ..., spec 026").

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
