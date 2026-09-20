# OptEV+

Decides where Singapore's next public EV charging points go, how many at each site, and
why — with the evidence retained. NUS-ISS IRS practice module, Group 25. Ships 25 Oct 2026.

## Layout

`SystemCode/optev/` — one package per workstream, each with its own CLAUDE.md:

| Package | Owns | Person |
|---|---|---|
| `contracts/` | Pydantic models. **Frozen** — changes need all four owners | P1 |
| `ingest/` | Collectors, conforming, spatial joins, coverage reporting | P1 |
| `analysis/` | Indicators, demand inference, patterns | P2 |
| `scenario/` | Projection, synthetic generation, planned overlay | P2 |
| `reasoning/` | Rules, allocator, feasibility checker | P3 |
| `evaluation/` | Baselines and experiment harness | P3 |
| `graph/` | Neo4j schema, loading, retrieval | P4 |
| `app/` | Streamlit UI | P4 |

Work in your own package. Read `contracts/` instead of another package's source.

## Three invariants

1. **Observed, simulated and planned data never merge.** A planner's selection goes to
   `planned_capacity`, never to `station` or `connector`. Measurement must not move
   because someone made a decision.
2. **`utilisation` is `None`, not `0`, where there is no supply.** Zero sorts a site to
   the bottom of a ranking as if nobody wanted to charge there.
3. **A connector counts as installed only once seen AVAILABLE or OCCUPIED.** The feed
   also carries planned and removed units under the same status.

## Commands

```bash
cd SystemCode
uv sync --extra dev          # setup
uv run pytest                # tests
uv run ruff check . && uv run mypy optev
uv run streamlit run optev/app/main.py
```

`/verify` runs lint, types and tests together. `/spec <name>` scaffolds a spec.

## Deeper docs

`specs/NNN-<name>/` per workstream — read the one you are working on, not all of them.
