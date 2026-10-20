# 008 · rules: register, engine, screening

**Owner:** Gurneet  ·  **Status:** complete on the sample, ready for review
**Branch:** `gurneetkb/17-rule-register`  ·  **Issues:** #17, #18, #19
**WBS:** 3.1 rule register · 3.2 rules engine, four outcomes, reason capture · 3.3 eligibility
screening

## Design section
SYSTEM_DESIGN.md §4.4, Rules (#17–#19, Gurneet), as of v1.7 (this PR adds `screen`,
`write_decisions`, **Checks** and **Screening**):

> ```python
> # optev/reasoning/rules.py
> REGISTER = Path(__file__).parent / "register.toml"
> def load_register(path: Path = REGISTER) -> tuple[list[Rule], dict[str, Outcome]]
> def site_facts(site: CandidateSite, car_park: CarPark | None,
>                indicators: SiteIndicators, context: dict[str, object]) -> dict[str, object]
> def evaluate(site_id: str, facts: dict[str, object], rules: list[Rule],
>              on_fail: dict[str, Outcome], scenario_id: str | None = None) -> Decision
> def screen(sites, car_parks, indicators, context, rules, on_fail, scenario_id=None)
>     -> tuple[list[Decision], dict[Outcome, int]]
> def write_decisions(cur, rules, on_fail, decisions) -> dict[str, int]
> ```
> - **Evaluation.** Evaluate **every** rule, never stop at the first failure. A rule whose
>   required fact is missing gives `passed = None`.
> - **Outcome policy**, in this order: any failing rule with `on_fail = reject` → **reject**;
>   else any unevaluated rule → **defer**; else any failing `conditional` rule →
>   **conditional**; else **accept**. A missing fact alone never rejects.

Tables: `rule`, `decision`, `rule_result` (§3.2). Baseline decisions use `scenario_id = 'observed'`.

## Basis
Built and tested on `optev.sample` (the team moves to the real data later). Rules read only
facts the collected week can produce (#52): `total_lots`, `existing_connectors`,
`supply_state`, `utilisation`.

## Register (`optev/reasoning/register.toml`, #17)
| id | condition | source · ref | facts | on_fail |
|---|---|---|---|---|
| R01 | Car capacity is published for the site | gov_dataset · `ds-hdb-availability` | total_lots | reject |
| R03 | Existing points plus one new point stay within `MAX_SHARE_OF_LOTS` of the car lots | math_constraint · `doc-lta-ev-factsheet-2021` | total_lots, existing_connectors | reject |
| R04 | Sites whose chargers are idle (`IDLE_BELOW`) get no more points | project_assumption · `asm-idle-threshold` | supply_state | reject |

- Ids follow the sample, so results can be compared with `sample.decisions`.
- **R01** cites data.gov.sg Car Park Availability, the proposal's source and the feed that
  supplies lot counts (the sample cites URA capacity, which the proposal does not list). It can
  only pass or defer: a missing `total_lots` is a data gap (defer), never a reject.
- **R03**: the LTA factsheet (4 Mar 2021) says new HDB car parks "cater sufficient electrical
  capacity to support EV slow charging for 15 per cent of their car parking lots" (checked).
- `load_register` refuses a broken register, listing every problem at once: invalid fields,
  `on_fail` other than reject/conditional, duplicate ids, facts outside the design's ten,
  template placeholders outside the rule's `required_facts`, a `source_ref` whose prefix does not
  match its class (§3.3 `ds-` / `doc-` / `asm-`), an empty or malformed file.

**Not in the register yet:**
- **R02** (basement → conditional) needs `car_park_type`, not in the collected week. It also has
  no official source: the proposal's LTA safety page, SCDF Fire Code 2023 cl. 10.4 and the
  LTA/BCA/SCDF reply of 5 Sep 2024 set no basement-specific condition for chargers (checked
  17 Oct 2026). Re-add with a source, or as `project_assumption`.
- **R05** (inside a planning area) needs MP2025 boundaries, not in the collected week.
- So no rule gives `conditional` yet. The engine supports it (tested with a stand-in rule).

## Engine (#18)
- **Checks** are functions in `rules.CHECKS`, keyed by `rule_id`. A register rule with no check
  raises; it never silently defers.
- **Forward chaining.** `derive` adds derived facts while their inputs are present, until none
  can fire: `room = max(0, floor(MAX_SHARE_OF_LOTS × total_lots) − existing_connectors)`.
  R03 passes when `room ≥ 1` (same as the sample's `existing + 1 ≤ 0.15 × lots`).
- **Reason capture.** Every rule gets a `RuleResult`. `detail` names the missing facts when
  unevaluated (`total_lots missing`) or the computed value (`room 89`). Decisions survive a
  JSON round trip through the contract.
- `outcome` applies the §4.4 policy; a failing rule without `on_fail` is an error.

## Screening (#19)
- `site_facts` joins site, car park (`car_park_type`), indicators (`supply_state`,
  `utilisation`) and context (`land_use`, `amenities_nearby`, `nearest_point_m`). Missing values
  are absent, never 0; `utilisation` stays absent where there is no supply (invariant 2).
- `screen` evaluates every site with its **latest** indicators window and returns the funnel,
  all four outcomes always present. A site without indicators is still screened; rules needing
  them defer, and it is logged.
- `write_decisions` upserts `rule` from the register, then `decision`, and replaces that
  (site, scenario)'s `rule_result` rows, so a rerun gives the same tables.

**Sample funnel:** accept 25 · reject 2 (S-13 no room, S-14 idle) · defer 3 (S-27, S-28, S-30:
no lot count) · conditional 0. S-06 and S-11 were conditional in the sample only through R02.

## Verification
- `tests/test_rules.py` (register, 20 tests) and `tests/test_screen.py` (engine and screening,
  26 tests), on the sample: every shared rule result equals `sample.decisions`; outcomes match the
  sample wherever the sample's R02/R05 passed; outcome policy order; missing facts defer;
  latest window used; funnel; the allocator's eligible set; SQL with a fake cursor.
- ruff, mypy, full pytest: 135 passed, 8 skipped (live DB and graph tests).

## Open questions
1. Which further collected-data rules to add (e.g. on `utilisation`)? Each needs a cited source
   or a declared assumption, plus a check in `CHECKS`.
2. Who reads `decision`/`rule_result` back for the pipeline (#35)? `screen` takes contracts; the
   Postgres reads belong with the pipeline step "rules for every site".

## Checkpoint · 17 Oct 2026
- Register and loader (#17) built; verify steps pass.

## Checkpoint · 19 Oct 2026 · task 3 complete on the sample
- **Built:** engine (#18) and screening (#19) in `rules.py` (~310 lines). Design v1.7 names
  `screen` and `write_decisions` and states how checks and derived facts work.
- **Stacked on #53** (1.4, design v1.6), which merges first; until then this PR's diff also
  shows #53's commits. Spec renumbered 004 → 008, since 004 is taken on other branches.
- **Moving to real data later:** run `screen` over `candidate_site`, `car_park`,
  `site_indicators` and `site_context` from Postgres, then `write_decisions`.
