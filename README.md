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
| Ghanashyam Ramia Kasthurirangan Pandurengan | A0357701E | Team lead; data foundation | A0357701E@u.nus.edu |
| Gurneet Kaur Bhuller | A0354164E | Measurement, inference and scenarios | A0354164E@u.nus.edu |
| Shrey Yadav | A0354457W | Reasoning, optimisation and evaluation | A0354457W@u.nus.edu |
| Sushant Maramkulam Shiji | A0354938M | Knowledge graph, explanation and interface | A0354938M@u.nus.edu |

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
