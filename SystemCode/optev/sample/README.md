# Shared sample data

A small, **entirely synthetic** slice of Tampines (20 sites) and Pasir Ris (10 sites), typed with
the frozen contracts. Build and test against it now; swap in real data when it lands. Every id
starts with `SYN-`, so it can never be mistaken for observed data.

```python
from optev.sample import load, connector_readings, car_park_readings, truth

s = load()                      # everything below, as contract objects
readings = connector_readings() # 46 connectors x 96 snapshots, every 30 min over 2 days
```

## What's inside

| Field | What | Count |
|---|---|---|
| `planning_areas` | Tampines (TM), Pasir Ris (PR) | 2 |
| `car_parks` | HDB and public car parks with lots and type | 26 |
| `stations`, `connectors` | Existing chargers; one connector never active (a planned unit) | 11, 46 |
| `sites` | Candidate sites: 26 car parks, a hawker centre, a community facility, two petrol stations | 30 |
| `near` | Station-to-site associations, the shape ingest (#10) will produce | 11 |
| `indicators` | Utilisation and saturation per site; one idle site, one feed gap | 30 |
| `estimates` | Arrivals per hour per site; one lower bound | 30 |
| `rules`, `decisions` | Five sample rules across all four source classes; all four outcomes appear | 5, 30 |
| `scenarios` | low / base / high growth; one planner selection in base | 3 |
| `allocation`, `infeasibility` | A reference plan for 12 points island-wide with no budget, and an impossible request: 40 points in Pasir Ris on $300k | 1, 1 |
| `references` | Datasets, a policy document and declared assumptions the rules cite | |

## Where to start, by workstream

- **Rules (#17–19):** feed `sites`, `car_parks` and `indicators` to your engine; compare with `decisions`.
- **Optimiser (#20–23):** use `estimates`, `decisions` and the cited cost per point; compare with `allocation` and `infeasibility`.
- **Demand (#13–16):** compute indicators from `connector_readings()`, infer demand, and score it against `truth()`.
- **Graph (#25–26):** load everything, including `near` and `references`.
- **App (#30–34):** sites have coordinates, and `allocation` gives something to draw.

## Know this before you rely on it

- **The demand estimates are deliberately naive.** They invert occupancy over the whole two days,
  and arrivals peak in the evening, so busy sites come out 30–40% below the true demand. That's the
  problem `time_bin` exists for: estimating per hour should do better. `truth()` lets #14 measure it.
- **Lower bounds hold.** The one saturated site's bound sits below its true demand, as it must.
- **No-charger estimates are a stand-in** for the regression (#16), not a model.
- **Rules and decisions are illustrative.** The real register comes from #17. `rule_on_fail` is
  sample-only: the contract leaves that choice to the rules engine.
- **The allocation is a greedy reference,** with at least 2 points per planning area and at most 15% of a site's lots. It is not the
  CP-SAT optimiser, but its plan respects every constraint, so it's a fair check.
- **`truth.json` is an answer key.** Use it to score models, never as a model input.

## Regenerating

```bash
uv run python -m optev.sample.generate
```

The generator is seeded and uses only arithmetic, so the output is byte-identical on every machine.
`tests/test_sample.py` fails if the committed files drift from what the generator produces.
