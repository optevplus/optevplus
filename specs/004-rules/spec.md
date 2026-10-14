# 004 · rules

**Owner:** Gurneet  ·  **Status:** ready for review  ·  **Branch:** `gurneetkb/17-rules-engine`
**WBS:** 3.1 Rule register (#17) · 3.2 Rules engine (#18) · 3.3 Eligibility screening (#19)

## Design section
SYSTEM_DESIGN.md §4.4, Rules (#17–#19):

> ```python
> # optev/reasoning/rules.py
> REGISTER = Path(__file__).parent / "register.toml"
> def load_register(path: Path = REGISTER) -> tuple[list[Rule], dict[str, Outcome]]
> def site_facts(site, car_park, indicators, context) -> dict[str, object]
> def evaluate(site_id, facts, rules, on_fail, scenario_id=None) -> Decision
> ```
> - **Register.** `reasoning/register.toml`, one entry per rule with every `Rule` field plus
>   `on_fail` (`reject` or `conditional`). Each rule cites its source class and `source_ref`.
> - **Facts.** `kind`, `planning_area`, `total_lots`, `existing_connectors`, `car_park_type`,
>   `supply_state`, `utilisation`, `land_use`, `amenities_nearby`, `nearest_point_m`. A missing
>   value is absent from the dict, never 0.
> - **Evaluation.** Evaluate **every** rule. A missing required fact gives `passed = None`.
> - **Outcome policy:** failing `reject` rule → reject; else unevaluated → defer; else failing
>   `conditional` → conditional; else accept.

Tables: `rule`, `decision`, `rule_result` (002). Baseline decisions use `scenario_id = 'observed'`.

## Problem
The allocator needs the screened set, and every planner-facing verdict needs a reason. Today
there is no register, no engine, and nothing writes `decision` or `rule_result`.

## Contracts touched
Reads `CandidateSite`, `CarPark`, `SiteIndicators`. Produces `Rule`, `RuleResult`, `Decision`.
No contract changes.

## Approach
- **`register.toml`** holds R01–R05, the sample's five cited rules. They cover all four
  source classes, and every `source_ref` resolves in `sample.references`. Thresholds are not
  in the file: R03 reads `MAX_SHARE_OF_LOTS`. R04 reads `supply_state`, which analysis sets
  with `IDLE_BELOW`. Templates are filled from the facts plus computed values (`room`, `share`).
- **`rules.py`**: each rule's test is a named check in `CHECKS`. The loader refuses
  duplicates, a bad `on_fail`, a rule with no check, a missing `source_ref`, or a fact
  outside the §4.4 list. Applicability runs before the missing-fact gate (`APPLIES_TO`):
  R02 concerns car parks only, so a hawker centre passes it rather than deferring.
  This matches the sample's reference decisions.
- **`screen.py`** (#19): `screen_sites` screens every site and returns the funnel (count per
  outcome, failures and gaps per rule). A site with no indicators is deferred, not dropped.
  `write_decisions` upserts `rule`, `decision`, and replaces that site's `rule_result` rows.
  `screen(scenario_id)` does read → screen → write against Postgres.

Notes on rule behaviour, all following "a missing fact never rejects":
- R01 and R05 cannot fail, only defer. Unknown lots or a point outside every planning-area
  polygon are data gaps, not judgements.
- Scenario runs reuse observed facts. Planned capacity affects the allocator's room
  (`effective_connectors`), not eligibility.

## Proposed design additions (PR to SYSTEM_DESIGN.md §4.4)
Names this spec adds beyond §4.4, for the team to approve or rename:
`rules.facts_without_indicators`, `rules.evaluate_rule`, `rules.decide`, `rules.CHECKS`,
`rules.APPLIES_TO`, `rules.FACTS`; `optev/reasoning/screen.py` with `screen_sites`,
`write_decisions`, `screen`.

## Verification
`uv run pytest tests/test_rules.py`: 26 tests. All 30 sample sites give the reference
outcome and the same `passed` per rule; R03 room values match. Also covered: every
outcome-precedence pair, missing-fact → defer, 0 connectors treated as a fact,
`no_supply` ≠ idle, malformed registers refused, the JSON round trip of every `Decision`,
and the funnel (23 accept · 2 conditional · 2 reject · 3 defer). The SQL is checked for
parameter binding with a fake cursor.

## Open questions
1. R01–R05 are the sample's illustrative rules (sample README). Before the report, confirm
   `doc-lta-ev-safety` supports R02, and decide whether more rules are needed
   (land use, petrol stations). Adding one = one TOML entry + one check + a test.
2. §6 asks for agreement with 30 sites labelled by two raters (κ ≥ 0.7). Those labels don't
   exist yet.
3. Open decision §9.3 (minimum points per chosen site, 3–6 per the HDB tender) may become
   an R03 variant ("room ≥ minimum") instead of ≥ 1.

## Checkpoint · 14 Oct 2026
- **Works:** register, engine and screening on the sample. ruff, mypy and all rules tests pass.
- **Not yet run:** `screen()` / `write_decisions` against a live Neon. No database was available.
- **Next:** the design PR for the added names, then the Rules page (#31), which reads `decision`
  and `rule_result`.
