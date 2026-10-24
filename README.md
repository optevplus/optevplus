# OptEV+ | Intelligent EV Charging Infrastructure Planner

### [ Practice Module ] Project Submission — NUS-ISS Intelligent Reasoning Systems

---

## SECTION 1 : PROJECT TITLE
**OptEV+ | Intelligent EV Charging Infrastructure Planner**

---

## SECTION 2 : EXECUTIVE SUMMARY / PAPER ABSTRACT

Singapore aims to deploy 60,000 EV charging points by 2030. With more than half already
in place and most HDB car parks served, the planning question has shifted: not which car
park lacks a charger, but which sites receive the next tranche, how many at each, and on
what evidence.

OptEV+ collects live government feeds, infers charging demand from observed occupancy
while reporting the reliability of those estimates, applies eligibility and feasibility
rules, allocates charging points under budget and capacity constraints, and retains the
evidence behind every site it accepts, rejects or defers.

---

## SECTION 3 : CREDITS / PROJECT CONTRIBUTION

| Official Full Name | Student ID | Work Items (Who Did What) | Email |
| :--- | :---: | :--- | :--- |
| Ghanashyam Ramia Kasthurirangan Pandurengan | A0357701E | Team lead. Knowledge graph and explanation layer (cognitive techniques); coverage and freshness reporting; evidence view; installation guide | A0357701E@u.nus.edu |
| Gurneet Kaur Bhuller | A0354164E | EV charging point collector and data conforming; rules engine and eligibility screening (decision automation); app shell and planned capacity | A0354164E@u.nus.edu |
| Shrey Yadav | A0354457W | Car park collector, spatial joins and planning areas; cost model, allocator and feasibility checker (resource optimisation); deployment | A0354457W@u.nus.edu |
| Sushant Maramkulam Shiji | A0354938M | Source checks, database and data access; indicators, demand inference and pattern discovery (knowledge discovery); scenario generation | A0354938M@u.nus.edu |

Shared by all four: evaluation (one baseline each, plus the experiment harness), end-to-end
integration, report sections and the two videos. Work items follow the GitHub issue
assignments and will be updated to what each person delivered.

---

## SECTION 4 : VIDEO OF SYSTEM MODELLING & USE CASE DEMO

_Business case and system design videos — to be added._

---

## SECTION 5 : USER GUIDE

**Live system:** https://optevplus.streamlit.app (Streamlit Community Cloud, `main`, reading Neon).

You need **Python 3.12+**, **[uv](https://docs.astral.sh/uv/)** and **git**. Everything else
is installed by uv. Pick one of the two paths below.

### A. Run with the team's databases (Neon + Aura)

```bash
git clone https://github.com/optevplus/optevplus.git
cd optevplus/SystemCode
cp .env.example .env          # then fill in DATABASE_URL and NEO4J_* (ask the team)
uv sync --extra dev
uv run optev-db migrate       # creates or updates every table; safe to re-run
uv run streamlit run optev/app/main.py
```

Open http://localhost:8501 and choose **Evidence** in the sidebar.

### B. Run offline, with no credentials (sample data)

Uses the synthetic sample (`optev/sample`, every id starts with `SYN-`) and a local Neo4j.
Needs [Docker](https://docs.docker.com/get-docker/).

```bash
git clone https://github.com/optevplus/optevplus.git
cd optevplus/SystemCode
uv sync --extra dev
docker compose up -d          # local Neo4j on bolt://localhost:7687
cp .env.example .env
```

In `.env`, leave `DATABASE_URL` empty and set:

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=optevlocal
```

Then load the sample into the graph and start the app:

```bash
uv run python -m optev.graph load --sample
uv run streamlit run optev/app/main.py
```

### C. Run the whole pipeline offline (local Postgres)

With Postgres and PostGIS installed locally (e.g. `brew install postgresql@17 postgis`), the
sample goes into a scratch database and every stage runs on it:

```bash
createdb optev && psql -d optev -c "CREATE EXTENSION postgis;"
export DATABASE_URL=postgresql://localhost/optev
uv run optev-db migrate
uv run python -m optev.sample.seed_db                 # the sample, as if collected
uv run python -m optev.pipeline run --scenario base --points 12
```

### Try it

On the **Evidence** page, ask in plain words or pick a question:

| Ask | What you should see |
|---|---|
| Why was SYN-S-13 rejected? | Rejected by rule R03 (no room within 15% of its lots), citing the LTA factsheet |
| Where does the demand estimate for SYN-S-04 come from? | A lower bound ("at least"), with the reliability assumption behind it |
| Compare SYN-S-04 and SYN-S-13. | Both sites side by side |
| Why was SYN-S-99 rejected? | **No evidence**: the system refuses instead of guessing |

Written answers need a language model. Add to `.env` (any one provider):

```
LLM_PROVIDER=deepseek        # or gemini | anthropic | openai_compatible (+ LLM_BASE_URL)
LLM_API_KEY=...
LLM_MODEL=deepseek-chat
```

Without it, the page shows the evidence and says no model is configured.

### Command reference

Run from `SystemCode/`.

| Command | What it does | Needs |
|---|---|---|
| `uv run optev-db migrate` | Create or update every table | Postgres |
| `uv run optev-db load-collected <folder>` | Load the collected week of readings | Postgres, raw files |
| `uv run optev-db conform` | Build candidate sites from car parks, stations and readings | Postgres |
| `uv run optev-db coverage` | Measure data completeness and freshness | Postgres |
| `uv run python -m optev.pipeline run --scenario base --area TM --points 12` | Every stage end to end; `--from STEP` restarts part-way (`python -m optev.pipeline steps` lists them) | Postgres, Neo4j |
| `uv run python -m optev.graph load` | Rebuild the graph from Postgres (`load_all`) | Postgres, Neo4j |
| `uv run python -m optev.graph load --sample` | Load the sample into the graph (`clear --sample` removes it) | Neo4j |
| `uv run python -m optev.graph ask why_not_site site_id=SYN-S-13` | One fixed graph query, raw evidence | Neo4j |
| `uv run python -m optev.graph explain "Why was SYN-S-13 rejected?"` | Written, cited answer, or a refusal | Neo4j (+ model) |
| `uv run python -m optev.evaluation.harness` | Comparison table: optimiser vs baselines | nothing (sample) |
| `uv run python -m optev.evaluation.explain_eval` | Stage 5 scores on the 20 questions (`--llm` for answers) | Neo4j (+ model) |
| `uv run pytest` | Tests; database tests skip without credentials | nothing |

### If something goes wrong

| Symptom | Fix |
|---|---|
| `DATABASE_URL is not set` | Fill it in `SystemCode/.env` (path A), or use path B |
| Neo4j: "Failed to DNS resolve" or "Unable to retrieve routing information" | Aura Free pauses after 3 days without a write: resume it at console.neo4j.io |
| Neo4j: "certificate verify failed" on macOS | Handled already (certifi); update with `uv sync` |
| Postgres connection times out | Some networks block port 5432; try another network |
| Tests fail on Windows with line endings | `git config core.autocrlf false`, then re-clone (the repo forces LF) |

---

## SECTION 6 : PROJECT REPORT / PAPER

See `ProjectReport/`.

---

## SECTION 7 : MISCELLANEOUS

See `Miscellaneous/`.
