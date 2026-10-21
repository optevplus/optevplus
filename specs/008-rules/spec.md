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
**A rule is in the register because a source supports it** (a government dataset, a policy
document or a declared assumption), never because its facts happen to be loaded. Missing data
only decides whether a rule evaluates or defers. (Corrected 20 Oct 2026 after review of #54,
which had trimmed the register to the facts the collected week provided.)

Tests run on `optev.sample`. `screen_all` runs the same code on Postgres.

## Register (`optev/reasoning/register.toml`, #17)
| id | condition | source · ref | facts | on_fail |
|---|---|---|---|---|
| R01 | Car capacity is published for the site | gov_dataset · `ds-hdb-availability` | total_lots | reject |
| R02 | A basement car park needs its fire-safety provisions for EV charging confirmed first | gov_policy · `doc-mha-ev-carparks-2026` | kind (+ car_park_type for car parks) | conditional |
| R03 | Existing points plus one new point stay within `MAX_SHARE_OF_LOTS` of the car lots | math_constraint · `doc-lta-ev-factsheet-2021` | total_lots, existing_connectors | reject |
| R04 | Sites whose chargers are idle (`IDLE_BELOW`) get no more points | project_assumption · `asm-idle-threshold` | supply_state | reject |
| R05 | The site lies inside a Master Plan 2025 planning area | gov_dataset · `ds-mp2025-areas` | planning_area | reject |
| R06 | Electrical capacity must be confirmed before points are added where no charger runs yet | gov_policy · `doc-mot-ev-reply-2025` | existing_connectors | conditional |

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

- **R05** is back (it was dropped in #54 only because planning areas weren't loaded; Shrey's
  #59 loads them). Conform assigns the area by point-in-polygon, so a present `planning_area`
  means inside one and passes. A site outside every polygon has none, so R05 **defers** it as a
  data gap: the design's policy that a missing fact never rejects applies to R05 too.
- **R06** cites the MOT written parliamentary reply of 14 Oct 2025 (Acting Minister Jeffrey
  Siow): deploy "in carparks with high charging demand, electrical capacity permitting"
  (checked 20 Oct 2026). No dataset reports spare electrical capacity, so the check treats it as
  shown only where chargers already run (`existing_connectors ≥ 1`); everywhere else it fails
  with `electrical capacity to be confirmed` → **conditional**. That reading of the policy is a
  judgement for review.
- **R02 is back** (20 Oct 2026). Source: MHA written parliamentary reply of 8 Sep 2026
  (Minister K Shanmugam), "Adequacy of fire safety standards for electric vehicles in enclosed
  and multi-storey car parks": "sprinklers are required for enclosed basement carparks", and
  SCDF has mandated "at least one emergency main isolation shut-off switch ... within 15 metres
  of an electric vehicle (EV) charging station" (checked 20 Oct 2026; the MHA reply of
  10 Sep 2024 and the LTA/BCA/SCDF reply of 3 Sep 2024 say the same). No source says a basement
  needs a *review*; what they state is a basement-specific requirement that no dataset can
  confirm, so a basement car park is **conditional** on confirming it.
  - Not a car park (hawker, community club, petrol): passes, `not a car park`.
  - Car park whose type contains BASEMENT: fails → conditional,
    `basement: confirm sprinklers and EV isolation switch`.
  - Car park of unknown type: `passed = None` → **defer**, never assumed safe. On real data that
    is every URA car park (#59 loads type for HDB only, ~659 sites), which needs a team call.
  - Required fact is `kind`, not `car_park_type`, so non-car-park sites are not deferred; the
    check reads the type for car parks only (design 1.14 lets a check return None for that).
- `doc-mha-ev-carparks-2026` and `doc-mot-ev-reply-2025` are added to the sample's references,
  so the graph can link R02 and R06.

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

**Sample funnel (R01–R06):** accept 8 (chargers already running, room, not idle, not a
basement) · conditional 17 (16 with no charger yet; S-11 is a basement) · reject 2 (S-13 no
room, S-14 idle) · defer 3 (S-27, S-28, S-30: no lot count). All four outcomes appear.

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

## Checkpoint · 20 Oct 2026 · follow-up to #54
- **Register:** R05 back; R06 added (the first `conditional` rule). Every rule's `source_ref`
  must be a known reference (test). Sample funnel: accept 9 · conditional 16 · reject 2 · defer 3.
- **`screen_all` + `python -m optev.reasoning screen [--scenario ID] [--dry-run]`:** reads
  `candidate_site`, `car_park`, `site_indicators`, `site_context`; screens; writes; prints the
  funnel. Tested end to end on the sample through a fake connection. Design v1.14.
- **Real data: not run yet.** Needs `site_indicators` (Sushant's #64, open) and `DATABASE_URL`
  on this machine. Run: `uv run python -m optev.reasoning screen --dry-run`, check all four
  outcomes appear, then without `--dry-run`, and post the funnel on the PR.
- Expected on real data: R05 defers any site outside every planning-area polygon; R06 makes
  sites without chargers conditional; R04 rejects idle ones; R01 defers sites with no lots.
- `rules.py` is ~380 lines, over the ~300 guideline; the Postgres runner could move out.
- Suite: 146 passed, 11 skipped (live DB and graph tests).

## Checkpoint · 20 Oct 2026 (2) · R02 back
- R02 (basement, gov_policy, conditional) cites the MHA reply of 8 Sep 2026. Checks may now
  return `passed = None` (design 1.14). Sample funnel: accept 8 · conditional 17 · reject 2 ·
  defer 3. Suite: 154 passed, 11 skipped.
- **Team call:** URA car parks have no type, so R02 defers all ~659 of them. Options: load a
  type for URA, or treat URA surface/multi-storey as known (needs a source).
