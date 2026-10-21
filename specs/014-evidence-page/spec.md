# 014 · Evidence page (#34)

**Owner:** Ghanashyam  ·  **Status:** built, in review  ·  **Branch:** `ghanashyam/34-evidence-page`

## Design section
> | Evidence (#34) | Ghanashyam | Ask why; answer with its evidence trail |
> **No business logic in the app.** — SYSTEM_DESIGN.md §4.6

Issue #34: every figure carries whether it is observed, simulated or planned; done when this
part of the system can be explained from the screen alone.

## Approach
- `optev/app/pages/5_Evidence.py`: ask in your own words (→ `explain`) or pick one of the eight
  retrieval questions (→ `retrieve`). Shows the answer or a red **Refused** banner, then the
  evidence. Without a model configured it shows the evidence and says so.
- `optev/app/evidence.py`: pure `sections()` that arranges rows into labelled tables; nothing
  computed. Layers: observed, inferred (estimates), rule, declared (assumptions), recommended
  (optimiser plan), planned (planner pick).

## Verification
- 4 unit tests (questions match retrieval, every section labelled, lower bound shown as
  "at least", numbers unchanged) and 2 live AppTest runs on Aura (a rejection with R03; a
  visible refusal for SYN-S-99).
- Ran the app locally: SYN-S-13 shows reject, R03 failed (room 0), LTA factsheet with link.

## Checkpoint · 20 Oct 2026
- **Works:** above. Stacked on #62 (explanation); merge that first.
- **Next:** the app shell (#30) can link here; written answers appear once the LLM key is set.
