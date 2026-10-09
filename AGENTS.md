# OptEV+

Decides where Singapore's next public EV charging points go, how many at each site, and
why — with the evidence retained. NUS-ISS IRS practice module, Group 25. Ships 25 Oct 2026.

These instructions are for any AI coding assistant (Codex, Cursor, Copilot, Claude Code).
Claude Code reads them through `CLAUDE.md`.

## Layout

`SystemCode/optev/` — one package per workstream:

| Package | Owns | Person |
|---|---|---|
| `contracts/` | Pydantic models. **Frozen** — changes need all four owners | All four |
| `ingest/` | Collectors, conforming, spatial joins, coverage reporting | Shrey, Gurneet (+ Sushant, Ghanashyam) |
| `analysis/` | Indicators, demand inference, patterns | Sushant |
| `scenario/` | Projection, synthetic generation, planned overlay | Sushant, Shrey · Gurneet, Ghanashyam |
| `reasoning/` | Rules (Gurneet); allocator, feasibility checker (Shrey) | Gurneet, Shrey |
| `evaluation/` | Baselines and experiment harness | Shared, one baseline each |
| `graph/` | Neo4j schema, loading, retrieval | Ghanashyam |
| `app/` | Streamlit UI: shell (Gurneet), result views by workstream | All four |

Before working in a package, read its `CLAUDE.md` (a few lines: what belongs there and the
one rule that matters) and `SystemCode/optev/contracts/`. Build against the contracts, never
against another package's source. Until real data lands, build and test against the
synthetic sample in `SystemCode/optev/sample/` (`from optev.sample import load`). Owners follow
the GitHub issue leads;
`.github/CODEOWNERS` is the enforced copy.

## Three invariants

1. **Observed, simulated and planned data never merge.** A planner's selection goes to
   `planned_capacity`, never to `station` or `connector`. Measurement must not move
   because someone made a decision.
2. **`utilisation` is `None`, not `0`, where there is no supply.** Zero sorts a site to
   the bottom of a ranking as if nobody wanted to charge there.
3. **A connector counts as installed only once seen AVAILABLE or OCCUPIED.** The feed
   also carries planned and removed units under the same status.

## Commands

Run from `SystemCode/`:

```bash
uv sync --extra dev                       # setup
uv run ruff check .                       # verify, step 1: lint
uv run mypy optev                         # verify, step 2: types
uv run pytest                             # verify, step 3: tests
uv run streamlit run optev/app/main.py    # the app
```

## How to work on an issue

1. **One issue, one branch:** `<name>/<issue>-<short>`, e.g. `gurneet/17-rule-register`. Never commit to `main`.
2. **Plan before code.** Copy `specs/000-template/spec.md` to `specs/NNN-<short-name>/spec.md`
   (next free number) and fill in the problem, the contracts used, the approach and how it
   will be verified. Show the plan to the human and wait for an OK before writing code.
3. **Every function gets a test.** Run the three verify steps; all must pass before a PR.
4. **Checkpoint before stopping.** Append a dated `## Checkpoint` section to the spec: what
   works, what is half-built, decisions taken and why, what to do next. Under 20 lines.
5. **Never** change `contracts/` without all four owners, commit `.env`, credentials or
   data files, or merge your own PR.

## Deeper docs

`specs/NNN-<name>/` per workstream — read the one you are working on, not all of them.
