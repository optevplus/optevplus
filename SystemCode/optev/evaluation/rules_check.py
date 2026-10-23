"""Rules check (SYSTEM_DESIGN.md §6, Stage 4 rules): two people judge 30 sites blind, and their
verdicts are compared with each other and with the rules engine.

    uv run python -m optev.evaluation.rules_check pick  [--sample] [--seed 25]
    uv run python -m optev.evaluation.rules_check score

`pick` draws 30 sites stratified by the system's outcome (8 accept, 8 conditional, 7 defer,
7 reject), in shuffled order, and writes one rating sheet per rater with the site's evidence
only: no outcome and no rule results, so the raters can't see the verdict. The system's verdicts
go to a separate key file that the raters must not open. `score` reads the filled sheets and the
key, then writes Cohen's kappa, each rater's agreement with the system and the disagreements.
"""

import argparse
import csv
import os
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from optev.contracts import Decision, Outcome

OUT = Path(__file__).resolve().parents[3] / "specs" / "031-rules-check"
QUOTA = {Outcome.ACCEPT: 8, Outcome.CONDITIONAL: 8, Outcome.DEFER: 7, Outcome.REJECT: 7}
RATERS = ("gurneet", "shrey")
VERDICTS = tuple(o.value for o in Outcome)
EVIDENCE = (
    "site_id", "kind", "planning_area", "land_use", "car_park_type", "total_lots",
    "existing_connectors", "supply_state", "utilisation", "observation_coverage",
    "nearest_charger_m", "amenities_nearby", "residents_in_area", "demand_per_h",
    "demand_kind", "missing",
)


# Picking --------------------------------------------------------------------------------------

def pick(decisions: Sequence[Decision], seed: int = 25,
         quota: Mapping[Outcome, int] = QUOTA) -> tuple[list[str], dict[Outcome, int]]:
    """Site ids stratified by outcome, then shuffled so the order says nothing about the
    verdict. Returns the ids and any shortfall per outcome (fewer sites than the quota)."""
    rng = random.Random(seed)
    by_outcome: dict[Outcome, list[str]] = {o: [] for o in quota}
    for d in sorted(decisions, key=lambda d: d.site_id):
        if d.outcome in by_outcome:
            by_outcome[d.outcome].append(d.site_id)
    chosen, short = [], {}
    for o, n in quota.items():
        pool = by_outcome[o]
        chosen += rng.sample(pool, min(n, len(pool)))
        if len(pool) < n:
            short[o] = n - len(pool)
    rng.shuffle(chosen)
    return chosen, short


def evidence(site_ids: Sequence[str],
             facts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One blind row per site: the evidence a planner would look at, nothing the engine
    concluded. A missing value is left empty and named in `missing`."""
    rows = []
    for sid in site_ids:
        f = facts.get(sid, {})
        row = {k: f.get(k) for k in EVIDENCE}
        row["site_id"] = sid
        row["missing"] = ", ".join(k for k in EVIDENCE[1:-1] if f.get(k) is None)
        rows.append(row)
    return rows


# Reading facts ------------------------------------------------------------------------------

def sample_facts() -> tuple[list[Decision], dict[str, dict[str, Any]]]:
    """The sample, screened by the current register. The sample has no site_context."""
    from optev.reasoning.rules import load_register, screen
    from optev.sample import load

    s = load()
    rules, on_fail = load_register()
    decisions, _ = screen(s.sites, s.car_parks, s.indicators, {}, rules, on_fail)
    cps = {c.car_park_id: c for c in s.car_parks}
    ind = {i.site_id: i for i in s.indicators}
    dem = {e.site_id: e for e in s.estimates if e.time_bin == "all"}
    facts = {}
    for site in s.sites:
        cp, i, e = cps.get(site.car_park_id or ""), ind.get(site.site_id), dem.get(site.site_id)
        facts[site.site_id] = {
            "kind": site.kind.value, "planning_area": site.planning_area,
            "car_park_type": cp.car_park_type if cp else None, "total_lots": site.total_lots,
            "existing_connectors": site.existing_connectors,
            "supply_state": i.supply_state.value if i else None,
            "utilisation": i.utilisation if i else None,
            "observation_coverage": i.observation_coverage if i else None,
            "demand_per_h": round(e.arrivals_per_hour, 3) if e else None,
            "demand_kind": e.kind.value if e else None,
        }
    return decisions, facts


FACTS_SQL = """
SELECT s.site_id, s.kind, s.planning_area, s.total_lots, s.existing_connectors,
       cp.car_park_type, sc.land_use, sc.nearest_point_m AS nearest_charger_m,
       sc.amenities_nearby, sc.residents_in_area,
       i.supply_state, i.utilisation, i.observation_coverage,
       round(e.arrivals_per_hour::numeric, 3) AS demand_per_h, e.kind AS demand_kind
FROM candidate_site s
LEFT JOIN car_park cp ON cp.car_park_id = s.car_park_id
LEFT JOIN site_context sc ON sc.site_id = s.site_id
LEFT JOIN LATERAL (SELECT * FROM site_indicators x WHERE x.site_id = s.site_id
                   ORDER BY window_end DESC LIMIT 1) i ON true
LEFT JOIN demand_estimate e ON e.site_id = s.site_id AND e.time_bin = 'all'"""
DECISIONS_SQL = "SELECT site_id, outcome FROM decision WHERE scenario_id = 'observed'"
RESULTS_SQL = """SELECT site_id, rule_id, passed, detail FROM rule_result
    WHERE scenario_id = 'observed' ORDER BY site_id, rule_id"""


def database_facts(url: str) -> tuple[list[Decision], dict[str, dict[str, Any]]]:
    """Baseline decisions and every site's evidence from the pipeline's tables."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        results: dict[str, list[dict[str, Any]]] = {}
        for r in cur.execute(RESULTS_SQL):
            results.setdefault(r.pop("site_id"), []).append(r)
        decisions = [Decision(site_id=d["site_id"], outcome=d["outcome"],
                              results=results.get(d["site_id"], []))
                     for d in cur.execute(DECISIONS_SQL)]
        facts = {}
        for row in cur.execute(FACTS_SQL):
            sid = row.pop("site_id")
            facts[sid] = {k: (float(v) if k == "demand_per_h" and v is not None else v)
                          for k, v in row.items()}
    return decisions, facts


# Scoring --------------------------------------------------------------------------------------

def kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over the same items (unweighted)."""
    if len(a) != len(b) or not a:
        raise ValueError("two non-empty rating lists of the same length are needed")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(a: Sequence[str], b: Sequence[str]) -> float:
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def score(ratings: Mapping[str, Mapping[str, dict[str, str]]], system: Mapping[str, dict[str, str]]
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Summary rows, per-site rows and disagreements. `ratings` maps rater -> site -> row with
    `verdict` and `reason`; `system` maps site -> row with `verdict` and `why`."""
    first, second = RATERS
    sites = [s for s in system if all(ratings[r].get(s, {}).get("verdict") for r in RATERS)]
    if len(sites) < len(system):
        missing = sorted(set(system) - set(sites))
        raise ValueError(f"{len(missing)} sites have no verdict from both raters: {missing}")
    for r in RATERS:
        bad = {ratings[r][s]["verdict"] for s in sites} - set(VERDICTS)
        if bad:
            raise ValueError(f"{r}: verdicts must be one of {VERDICTS}, not {sorted(bad)}")
    v = {r: [ratings[r][s]["verdict"] for s in sites] for r in RATERS}
    sysv = [system[s]["verdict"] for s in sites]
    summary = [
        {"comparison": f"{first} vs {second}", "agreement": agreement(v[first], v[second]),
         "kappa": kappa(v[first], v[second])},
        *({"comparison": f"{r} vs system", "agreement": agreement(v[r], sysv),
           "kappa": kappa(v[r], sysv)} for r in RATERS),
    ]
    per_site, disagreements = [], []
    for i, s in enumerate(sites):
        row = {"site_id": s, f"{first}": v[first][i], f"{second}": v[second][i],
               "system": sysv[i], "system_why": system[s].get("why", ""),
               f"{first}_reason": ratings[first][s].get("reason", ""),
               f"{second}_reason": ratings[second][s].get("reason", "")}
        per_site.append(row)
        if len({v[first][i], v[second][i], sysv[i]}) > 1:
            disagreements.append(row)
    return summary, per_site, disagreements


# Files --------------------------------------------------------------------------------------

def _write(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields))
        w.writeheader()
        w.writerows(rows)


def _read(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["site_id"]: row for row in csv.DictReader(fh)}


def write_sheets(decisions: Sequence[Decision], facts: Mapping[str, Mapping[str, Any]],
                 out: Path = OUT, seed: int = 25) -> dict[Outcome, int]:
    ids, short = pick(decisions, seed)
    rows = evidence(ids, facts)
    for r in RATERS:
        _write(out / f"rating_{r}.csv", [row | {"verdict": "", "reason": ""} for row in rows],
               [*EVIDENCE, "verdict", "reason"])
    by_id = {d.site_id: d for d in decisions}
    key = [{"site_id": s, "verdict": by_id[s].outcome.value,
            "why": "; ".join(f"{r.rule_id} {'failed' if r.passed is False else 'unevaluated'}"
                             + (f" ({r.detail})" if r.detail else "")
                             for r in by_id[s].results if r.passed is not True)}
           for s in ids]
    _write(out / "system_key.csv", key, ["site_id", "verdict", "why"])
    return short


def write_scores(out: Path = OUT) -> list[dict[str, Any]]:
    ratings = {r: _read(out / f"rating_{r}.csv") for r in RATERS}
    summary, per_site, disagreements = score(ratings, _read(out / "system_key.csv"))
    fields = list(per_site[0]) if per_site else ["site_id"]
    _write(out / "results.csv", per_site, fields)
    _write(out / "disagreements.csv", disagreements, fields)
    lines = ["| Comparison | Agreement | Cohen's κ |", "|---|---|---|"]
    lines += [f"| {r['comparison']} | {r['agreement']:.0%} | {r['kappa']:.2f} |" for r in summary]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m optev.evaluation.rules_check")
    parser.add_argument("command", choices=["pick", "score"])
    parser.add_argument("--sample", action="store_true", help="use optev.sample, not Postgres")
    parser.add_argument("--seed", type=int, default=25)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "score":
        for row in write_scores(args.out):
            print(f"{row['comparison']:<20} agreement {row['agreement']:.0%}  "
                  f"kappa {row['kappa']:.2f}")
        return 0
    if args.sample:
        decisions, facts = sample_facts()
    else:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        url = os.environ.get("DATABASE_URL")
        if not url:
            print("DATABASE_URL is not set. Use --sample, or set it in SystemCode/.env.")
            return 1
        decisions, facts = database_facts(url)
    short = write_sheets(decisions, facts, args.out, args.seed)
    print(f"wrote {', '.join(f'rating_{r}.csv' for r in RATERS)} and system_key.csv "
          f"in {args.out}")
    for o, n in short.items():
        print(f"  short of {n} {o.value} sites: the data has fewer than the quota")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
