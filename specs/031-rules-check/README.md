# 031 · Rules check: two raters, 30 sites

**Owner:** Gurneet  ·  **Raters:** Gurneet, Shrey  ·  **Design:** SYSTEM_DESIGN.md §6, Stage 4
rules: "30 test sites, two raters, κ ≥ 0.7; target 100% agreement and 100% reason codes".

## Steps
1. **Pick** (needs `DATABASE_URL` and a pipeline run on Neon):
   `uv run python -m optev.evaluation.rules_check pick`
   This draws 30 sites stratified by the system's outcome (8 accept, 8 conditional, 7 defer,
   7 reject), seed 25, in shuffled order. It writes:
   - `rating_gurneet.csv`, `rating_shrey.csv`: the same 30 sites with **evidence only**
   - `system_key.csv`: the system's verdicts. **Raters must not open this file before
     rating.** Commit it only after both sheets are filled.
2. **Rate independently.** Each rater fills only their own `verdict` and `reason` columns,
   without looking at the other sheet, the key, the app or the database decisions.
3. **Score:** `uv run python -m optev.evaluation.rules_check score`
   This writes `results.csv` (every verdict per site), `disagreements.csv` and `summary.md`
   (agreement and Cohen's κ for rater vs rater and each rater vs the system).

## How to judge a site
Use only the evidence columns. Give one verdict:

| Verdict | Use it when |
|---|---|
| **accept** | Nothing you can see stops new points here. |
| **conditional** | Points could go here only once something is confirmed on site (e.g. fire-safety provisions, electrical capacity). |
| **defer** | The evidence is too incomplete to decide: a fact you'd need is missing (see `missing`). A data gap is never a reject. |
| **reject** | The evidence shows the site should get no more points (e.g. no room left within the lot share, chargers idle, outside any planning area). |

In `reason`, write one short line. It's used to explain disagreements.

**Evidence columns.**
- **Site:** `kind`, `planning_area`, `land_use` (MP2025), `car_park_type`, `total_lots`.
- **Chargers:** `existing_connectors` (active chargers).
- **Use:** `supply_state` and `utilisation` (over the collected week), and `observation_coverage` (data quality).
- **Surroundings:** `nearest_charger_m`, `amenities_nearby`, `residents_in_area`.
- **Demand:** `demand_per_h` with `demand_kind` (`lower_bound` means the site was saturated).
- **`missing`:** lists every field with no value.

## Caveat for the report
The design asks for raters "who did not write the rules". Gurneet wrote them, so her agreement
with the system is not independent evidence. Shrey's verdicts and the rater-vs-rater κ carry the
weight. State this in §8.1b, or swap in Sushant or Ghanashyam as the second rater.
