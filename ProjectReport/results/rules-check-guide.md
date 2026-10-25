# Rules check: rater guide

Two raters who did not write the rules each label the 30 sites in `rules-check-sheet.csv`
on their own. Do not look at the app, the database or each other's answers. Fill your
column (`rater_a` or `rater_b`) with one word: **accept**, **conditional**, **defer** or
**reject**.

## The facts

One row per site. A blank cell means the fact is not known; it is never zero.

| Column | Meaning |
|---|---|
| kind | `hdb_car_park` or `public_car_park` |
| total_lots | car lots at the site |
| existing_connectors | charging points already there |
| car_park_type | e.g. SURFACE, MULTI-STOREY, BASEMENT CAR PARK |
| supply_state | `supply_active`, `supply_idle` (chargers used < 5% of the time), `no_supply` |
| utilisation | share of time the chargers are in use |
| planning_area | Master Plan 2025 planning area code |

`land_use`, `amenities_nearby` and `nearest_point_m` are context only; no rule uses them.

## The rules

| Rule | The site must… | If not |
|---|---|---|
| R01 | have a published number of car lots (blank `total_lots` → cannot be judged) | reject |
| R02 | not be a basement car park (fire safety must be confirmed first). A car park with no known type cannot be judged | conditional |
| R03 | have room: existing points + 1 ≤ 15% of car lots (round 15% down) | reject |
| R04 | not have idle chargers (`supply_idle`) | reject |
| R05 | lie inside a planning area (blank `planning_area` → cannot be judged) | reject |
| R06 | already have at least one charging point (else electrical capacity must be confirmed) | conditional |

## Deciding the label

1. Any rule fails whose "if not" is **reject** → **reject**.
2. Otherwise, any rule cannot be judged because a fact it needs is blank → **defer**.
3. Otherwise, any rule fails whose "if not" is **conditional** → **conditional**.
4. Otherwise → **accept**.

Example: 200 lots, 2 existing points, surface car park, supply_active → room is
floor(0.15 × 200) − 2 = 28 ≥ 1, so R03 passes; every rule passes → **accept**.

When both columns are filled:

```bash
uv run python -m optev.evaluation.rules_check score ../ProjectReport/results/rules-check-sheet.csv --out ../ProjectReport/results/rules-check.md
```

## Who rated

- **rater_a:** an AI assistant (Claude), applying this guide to the sheet by hand. It helped
  build the system, so it is not independent: its agreement checks that the guide, the
  register and the engine say the same thing.
- **rater_b:** a team member who did not write the rules, rating `rules-check-rater-b-blank.csv`
  without seeing rater_a or the app.
