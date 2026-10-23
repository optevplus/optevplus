# 030 · Baseline: extend sites that already have chargers

**Owner:** Sushant  ·  **Status:** approved 22 Oct 2026; built  ·  **Branch:** `sushant/38-extend-existing`
**Issue:** #38 (7.1c · Baseline: extend sites that already have chargers)

## Design section
SYSTEM_DESIGN.md §6:

> **Baselines**, each producing an `Allocation` for the same request (area, points) and rules, scored by the
> same objective: busiest first (#36), spatial spread (#37), extend sites that already have
> chargers (#38), population share and random averaged over 100 seeds (in the harness, #39).
> **End-to-end number:** unmet demand covered per new point against the best baseline.

`evaluation/CLAUDE.md`: compare fairly by walking each baseline's ranking under the same
request and rules, so only the selection logic differs. Issue #38: done when it produces an
allocation directly comparable with the system's.

## Problem
There is no baseline for the incumbent operator's habit: add points where chargers already
are, because the cabling and the concession are there. Without it the optimiser is not
compared with the most likely real-world rule.

## Contracts touched
Reads `CandidateSite` and the scenario's `PlannedCapacity` through `harness.effective`;
returns `Allocation`. No contract change.

## Approach
**`extend_existing(request, inputs) -> Allocation`** in `evaluation/baselines.py`, a harness
`Method` next to `busiest_first` and `spatial_spread`:
- the candidates are the eligible sites with room (`harness.eligible`, `harness.room`), as
  for every other method;
- a site "already has chargers" when its effective connectors (`harness.effective`: existing
  plus the scenario's planned picks) are above 0, the same test `spatial_spread` uses;
- charging sites are ranked by effective connectors, most first, ties by `site_id`;
- points go round-robin, one at a time down the ranking, until the request is met or every
  charging site is at its room, so every existing site is extended before any gets a second;
- if charging sites run out of room, the remaining points go to the other eligible sites in
  `site_id` order (as `busiest_first` treats unmeasured sites), so it still places the points;
- never reads demand or utilisation.

Registered in `harness.sample_inputs` as "extend existing (#38)".

## Verification
New tests in `tests/test_baselines.py`, on the sample through the harness:
- places the requested points with 0 violations; the request is copied onto the plan;
- only sites with effective connectors > 0 get points while they have room; SYN-S-04 counts
  (2 existing + 2 planned);
- round-robin: with 12 points and 9 charging sites, each gets 1 and the 3 largest get 2;
- falls back to non-charging sites in `site_id` order once charging sites are full;
- ignores demand; respects the area; stops when all room runs out;
- the harness table lists "extend existing (#38)".
ruff, mypy, pytest pass; `uv run python -m optev.evaluation.harness` prints the row.

## Decisions (were open questions)
1. **Round-robin** (approved), not fill to room: it extends every site, while filling the
   largest site first would put all 12 sample points at SYN-S-02, much like busiest first.
2. **Planned picks count** as "already has chargers" (approved, as in `spatial_spread`), not
   only observed `existing_connectors`.
3. **Fallback to non-charging sites** (approved) rather than stopping short.

## Checkpoint · 22 Oct 2026
- **Works:** `baselines.extend_existing`; registered in `harness.sample_inputs` as
  "extend existing (#38)".
- **Sample table (12 points, base, island-wide):** extend existing 2.854 drivers rescued / h,
  0.84× the best of random and population share, 0 violations. It is the weakest method
  (busiest first 3.658, spatial spread 3.632, optimiser 3.743): spreading points thinly over
  sites that already have chargers rescues little.
- **Tests:** 5 new in `tests/test_baselines.py`. ruff, mypy, pytest pass.
- **Next:** PR to `main`, review by a CODEOWNER other than Sushant.

## Checkpoint · 23 Oct 2026
- **Fixed:** KeyError on real data (1,856 charging sites, 12 points). The round-robin stopped
  partway through its first round, and the room filter read `counts[sid]` for sites it never
  reached; it now reads `counts.get(sid, 0)`.
- **Tests:** a new test with fewer points than charging sites (3 vs 9) fails on the old line
  and passes on the fix. ruff, mypy, pytest pass.
