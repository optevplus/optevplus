# OptEV+ app review, 25 Oct 2026

Retest of every screen on the real data (branch `ghanashyam/app-redesign`, PR #103), with a
scripted browser run: 30 steps across all six pages, both themes, desktop 1440×900 and phone
390×844. Result: **no crashes, no tracebacks, no browser console errors, no ids on screen.**
The items below are what still needs changing, by owner. Priority: **P1** before the demo
video, **P2** before submission, **P3** nice to have.

## Ghanashyam

| # | Pri | Where | Issue | Fix |
|---|---|---|---|---|
| G1 | P1 | Ask Why | Comparing two sites is refused: the model cites `[A76]` instead of `[hdb:A76]`, and the check rejects it. Other site questions are refused now and then for the same reason. | In `graph/explain.py`, accept a citation that matches an evidence id once its prefix (`hdb:`, `ura:`, `cc:`, `hawker:`) is restored. |
| G2 | P1 | Ask Why | "Which areas are near saturation?" answers with "0.6818181818181818" and lists sources as "PG · SE"; the table repeats the area in capitals. | Round shares in the evidence (2 dp or %), map area codes in sources to names, drop the duplicate name column. |
| G3 | P1 | All pages | Slow first loads: Eligibility 18.6 s, Demand 20 s, Ask Why ~60 s with the answer, phone ~30 s. Each page loads the whole dataset into its own cache. | One shared cached loader for all pages; Ask Why reads only site names, not the full bundle. |
| G4 | P2 | Website | Light-mode gradient headline: green #7ED957 on white is 1.76:1, below the 3:1 minimum for large text. | End the text gradient on #2FA35A (3.2:1) in light mode; keep dark mode as is. |
| G5 | P2 | Website | If Neon is unreachable, every page shows a Python traceback. | Catch it in `app/data.py`: a short "data is unavailable" message on every page. |
| G6 | P2 | Ask Why | The public site spends the OpenAI key with no limit. | Cap questions per session (e.g. 15) and say so on the page. |
| G7 | P3 | Ask Why | "Why can't a request be met?" in Pick a Question returns "No evidence": its default area has no stored impossible request. | Default to an area with a stored report, or explain that none is stored. |
| G8 | P2 | Report, deck | Figures and slides show the old app. | Re-take after #103 merges. |

## Shrey (allocation, checker, deployment)

| # | Pri | Where | Issue | Fix |
|---|---|---|---|---|
| S1 | P1 | Deployment | Ask Why on optevplus.streamlit.app cannot answer: the secrets hold only `DATABASE_URL`. | Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (README §5 D). |
| S2 | P1 | Deployment | Anyone on the public site can write to the shared database: Select Site / Clear Selection change `planned_capacity` in Neon. | Give the deployed app a read-only Neon role, and add a `OPTEV_READ_ONLY=1` secret that hides the two buttons (Ghanashyam adds the flag to the page). |
| S3 | P1 | Deployment | `pyproject.toml` says `streamlit>=1.39`, but the app now needs ≥ 1.64 (top menu, session-kept widgets). | Raise the floor to `streamlit>=1.64`; after #103 merges, check the Cloud build log and click every page once. |
| S4 | P2 | Deployment | The light/dark toggle writes the theme to browser storage; Streamlit Cloud may block it in its frame. | After merge, click the toggle on the live site; if it does nothing, ⋮ → Settings still works; tell Ghanashyam. |
| S5 | P3 | Allocation | The checker cannot see planned capacity (known limitation in the report). | Leave for future work. |

## Sushant (data, demand, patterns)

| # | Pri | Where | Issue | Fix |
|---|---|---|---|---|
| U1 | P2 | Demand | The table shows the word "None" where utilisation or time-full is missing. Missing must read as blank or "—", never as a value. | Return `None` as empty in `demand_view.demand_table` display, or format the column so missing shows "—". |
| U2 | P2 | Data | 2 car parks (e.g. Blk 253/254 Ang Mo Kio Street 21) report 0 car lots in every reading and are rejected for "no room". They likely have only motorcycle or heavy-vehicle lots. | Treat 0 car lots as "no car lots" (exclude from candidates) or defer them; say which in the report. |
| U3 | P3 | Demand | "Method" line reads "regression: linear, 1856 sites, leave-area-out MAE 0.35/h…". | Plain wording: "Estimated from 1,856 similar sites (typical error 0.35 drivers an hour)." |

## Gurneet (rules, eligibility, app shell)

| # | Pri | Where | Issue | Fix |
|---|---|---|---|---|
| R1 | P1 | Eligibility | The rule register's Condition column shows internal names: "within MAX_SHARE_OF_LOTS of the car lots", "used under IDLE_BELOW of the time". | Write the values in words in `register.toml` conditions ("15% of the car lots", "5% of the time"), keeping the `optev.assumptions` names in a separate field or comment. |
| R2 | P2 | Eligibility | The decision table opens on community clubs (sorted by id), most of them deferred for missing data. | Sort car parks first, then by outcome (reject, conditional, defer, accept) and place name. |
| R3 | P3 | Eligibility | "If one failed rule were waived: waive Power Capacity Confirmed → defer" reads like code. | "Without *Power Capacity Confirmed* this site would be **Defer**." |

## Architecture and website, at a standard level

**In place and sound**
- Five-stage pipeline with one source of truth (PostgreSQL); the graph is rebuilt from it and only explains.
- CI runs lint, types and 400+ tests on every PR and on main; all green.
- Daily keep-alive job stops Neo4j Aura from pausing (last runs successful).
- Secrets only in `.env` (git-ignored) or platform secrets; nothing in the repo.
- Graph queries are fixed and parameterised; user text never becomes Cypher. Answers must cite retrieved evidence or are refused.
- Observed, simulated and planned data are kept apart in separate tables.
- Independent plan checker; impossible requests get a clear report.
- Light and dark themes, responsive layout on a phone, no raw ids on screen.

**Gaps (owners above)**
- Public write access to the database (S2): fix before sharing the link with examiners.
- Performance on a cold start (G3).
- Unbounded LLM spend on the public site (G6).
- Error handling when the database is down (G5).
- Dependency floor for Streamlit (S3); the lock file pins exact versions locally but Streamlit Cloud installs from `requirements.txt`.
- Accessibility contrast of one brand colour (G4).
