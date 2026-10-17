# 004 · rule register

**Owner:** Gurneet  ·  **Status:** ready for review  ·  **Branch:** `gurneetkb/17-rule-register`
**Issue:** #17  ·  **WBS:** 3.1 Rule register: conditions, sources, required facts

## Design section
SYSTEM_DESIGN.md §4.4, Rules (#17–#19, Gurneet):

> ```python
> # optev/reasoning/rules.py
> REGISTER = Path(__file__).parent / "register.toml"
> def load_register(path: Path = REGISTER) -> tuple[list[Rule], dict[str, Outcome]]
> ```
> - **Register.** `reasoning/register.toml`, one entry per rule with every `Rule` field plus
>   `on_fail` (`reject` or `conditional`). Each rule cites its source class and `source_ref`:
>   a document, dataset or assumption id. Rules come from the policy documents and datasets in
>   the proposal's references; any rule based on our own judgement is `project_assumption`.
> - **Facts.** Keys available to rules: `kind`, `planning_area`, `total_lots`,
>   `existing_connectors`, `car_park_type`, `supply_state`, `utilisation`, `land_use`,
>   `amenities_nearby`, `nearest_point_m`. A missing value is absent from the dict, never 0.

`site_facts` and `evaluate` are #18/#19, not this issue.

## Problem
There was no rule register. The sample's five rules are illustrative ("the real register comes
from #17"). The engine (#18) needs a file it loads, not prose (WBS 3.1 "done when").

## Basis: the collected week
Rules read only facts that the collected week can produce (merged in #52, loaded in Neon): HDB
car park availability (lots available, **total lots**) and LTA EVCBatch (connector status). From
those, conform and the indicators give `total_lots`, `existing_connectors`, `supply_state` and
`utilisation`. Tested on `optev.sample` until the week is loaded.

## Register (`optev/reasoning/register.toml`)
| id | condition | source · ref | facts | on_fail |
|---|---|---|---|---|
| R01 | Car capacity is published for the site | gov_dataset · `ds-hdb-availability` | total_lots | reject |
| R03 | Existing points plus one new point stay within `MAX_SHARE_OF_LOTS` of the car lots | math_constraint · `doc-lta-ev-factsheet-2021` | total_lots, existing_connectors | reject |
| R04 | Sites whose chargers are idle (`IDLE_BELOW`) get no more points | project_assumption · `asm-idle-threshold` | supply_state | reject |

- Ids follow the sample so #18 can compare its results with `sample.decisions` for these rules.
- **R01** cites data.gov.sg Car Park Availability, the proposal's source and the feed that
  supplies lot counts. The sample cites URA capacity, which is not in the proposal.
- **R03**: the LTA factsheet (4 Mar 2021) says new HDB car parks "cater sufficient electrical
  capacity to support EV slow charging for 15 per cent of their car parking lots" (checked).
- **R01** can only pass or defer, by the design's policy: a missing `total_lots` is a data gap
  (defer), never a reject. It makes that gap visible in every decision.

**Not in the register yet**, because their facts are not in the collected week:
- **R02** (basement car park → conditional) needs `car_park_type` (HDB Carpark Information).
  It also has no official source: the proposal's LTA safety page, SCDF Fire Code 2023 cl. 10.4
  and the LTA/BCA/SCDF reply of 5 Sep 2024 set no basement-specific condition for chargers
  (checked 17 Oct 2026). Re-add it only with a source, or as `project_assumption`.
- **R05** (inside a planning area) needs `planning_area` (MP2025 boundaries).
- No `gov_policy` rule remains, so no rule can give `conditional` yet.

## Approach
`optev/reasoning/rules.py`: `REGISTER`, `load_register()` (stdlib `tomllib`). Each entry is
validated into `Rule`, and a broken register raises one `ValueError` listing every problem:
- an invalid `Rule` field (pydantic)
- `on_fail` other than `reject` / `conditional`
- a duplicate `rule_id`
- a `required_facts` key that is not one of the ten design facts
- a template placeholder outside the rule's own `required_facts` (so rendering never meets a
  missing fact; computed numbers such as room left go in `RuleResult.detail`, #18)
- a `source_ref` that doesn't match its class: `ds-` dataset, `doc-` document, `asm-`
  assumption. These are the graph's `Dataset` / `Document` / `Assumption` ids (spec 005).
- an empty or malformed file

No threshold is written in the register; rules name the `optev.assumptions` value.

## Verification
`uv run pytest tests/test_rules.py` (20 tests): the shipped register loads; rules read only
collected facts; they agree with the sample rules they share; templates render with a sample
site's facts; no number is written inline; every fault above raises, all at once.
ruff, mypy, full pytest: 53 passed, 1 skipped.

## Open questions
1. Which collected-data rules should join R01, R03 and R04 (e.g. on `utilisation`)? The team
   decides; each needs a cited source or a declared assumption.
2. The reference list (`ds-`, `doc-`, `asm-` ids with titles and URLs) lives only in the
   sample. The graph loader (#25) will need it for real data.

## Checkpoint · 17 Oct 2026
- **Works:** register, loader, 20 tests; verify steps pass.
- **Next:** #18 `evaluate` (every rule, outcome policy in §4.4), then #19 `site_facts` and
  screening.

## Checkpoint · 17 Oct 2026 (2)
- Merged main (#51, #52). No shared files with the 1.4 branch (#53), which merges first.
  Suite: 67 passed, 4 skipped (live DB tests).
- The facts the rules read come from conform and the indicators. In Neon these need
  `car_park`/`station`/`connector`, which are still empty (see spec 003 checkpoint 4), so the
  register is exercised on the sample until they are loaded.
