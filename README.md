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

**Live system:** _deployment URL to be added._

To run locally:

```bash
git clone <repo-url> && cd optevplus/SystemCode
cp .env.example .env          # fill in Neon, Aura and LTA credentials
uv sync --extra dev
uv run optev-db migrate
uv run streamlit run optev/app/main.py
```

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). No Docker needed — both
databases are managed.

---

## SECTION 6 : PROJECT REPORT / PAPER

See `ProjectReport/`.

---

## SECTION 7 : MISCELLANEOUS

See `Miscellaneous/`.
