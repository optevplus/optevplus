# 020 · Rules page: decisions and rule results

**Owner:** Gurneet  ·  **Status:** ready for review  ·  **Branch:** `gurneetkb/31-rules-page`
(stacked on `gurneetkb/30-app-shell`, #84)  ·  **Issue:** #31  ·  **WBS:** 6.4a

## Design section
SYSTEM_DESIGN.md §4.6: | Rules (#31) | Gurneet | Each site's decision and every rule result
with its source class |. WBS 6.4a: "Every figure on screen carries whether it is observed,
simulated or planned. Done when your part of the system can be explained from the screen alone."

## Approach
- **`app/rules_view.py`**: pure functions, tested without Streamlit.
  - `register_rows`: each rule's condition, outcome on failure, facts read, and source type, title and link.
  - `decision_table`: one row per site, filterable by outcome and area.
  - `rule_results`: every rule result for one site, with its source.
  - `waivers`: the outcome if one failed rule were waived. It's computed with the engine's own `rules.outcome`, never recomputed here (WBS 3.2: "so a planner can see whether one waiver would change the result").
- **`app/pages/2_Rules.py`**: the register in an expander, then the funnel, the decision table, and "Why this outcome?" for a chosen site.
  - Missing data reads as "unevaluated (missing data)" and is never shown as failed.
  - A deferred site is told that filling the data, not a waiver, would settle it.

## Verification
- `tests/test_app_rules.py` has 6 tests:
  - sources and links resolved (assumptions have no link)
  - filters
  - every rule shown in register order
  - unevaluated distinct from failed
  - waivers: S-13 waive R03 gives accept, S-14 waive R04 gives accept
  - the page renders on the sample (Streamlit `AppTest`)
- ruff, mypy, pytest pass.

## Checkpoint · 22 Oct 2026
- Rules page renders on the sample. With #72 merged it shows R01–R06, including conditional.
