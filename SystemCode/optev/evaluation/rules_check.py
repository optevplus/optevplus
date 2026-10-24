"""Stage 4 rules check (design §4.4 "Checked by", §6): 30 test sites labelled in advance by two
people who did not write the rules; agreement with the system and Cohen's κ between raters.

    uv run python -m optev.evaluation.rules_check sheet --out rules-check.csv   # blind sheet
    uv run python -m optev.evaluation.rules_check score rules-check.csv         # after rating

`sheet` picks 30 sites stratified by the system's outcome and writes only their facts: the
raters never see the verdict. Each rater fills `rater_a` or `rater_b` with accept,
conditional, defer or reject, reading the rule register (`reasoning/register.toml`) and
nothing else. `score` re-screens the same sites and reports agreement, κ and reason codes.
"""

import argparse
import csv
import os
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optev.contracts import CandidateSite, CarPark, Decision, Outcome, SiteIndicators

_ENV = Path(__file__).resolve().parents[2] / ".env"
QUOTA = {Outcome.ACCEPT: 8, Outcome.CONDITIONAL: 8, Outcome.DEFER: 7, Outcome.REJECT: 7}
FACT_COLUMNS = ("kind", "planning_area", "total_lots", "existing_connectors", "car_park_type",
                "supply_state", "utilisation", "land_use", "amenities_nearby",
                "nearest_point_m")
RATERS = ("rater_a", "rater_b")
LABELS = {o.value for o in Outcome}


@dataclass
class Screened:
    decisions: dict[str, Decision]
    facts: dict[str, dict[str, object]]


def pick(decisions: Mapping[str, Decision], quota: Mapping[Outcome, int] = QUOTA,
         seed: int = 0) -> list[str]:
    """Site ids stratified by outcome, so every verdict is tested. An outcome with fewer
    sites than its quota gives all it has. Shuffled, so the order gives nothing away."""
    rng = random.Random(seed)
    chosen: list[str] = []
    for out, n in quota.items():
        ids = sorted(s for s, d in decisions.items() if d.outcome is out)
        chosen += rng.sample(ids, min(n, len(ids)))
    rng.shuffle(chosen)
    return chosen


def sheet_rows(ids: Sequence[str], facts: Mapping[str, Mapping[str, object]]
               ) -> list[dict[str, object]]:
    """One row per site: its facts (blank where missing, never 0) and empty rater columns."""
    rows = []
    for sid in ids:
        f = facts[sid]
        row: dict[str, object] = {"site_id": sid}
        for col in FACT_COLUMNS:
            value = getattr(f.get(col), "value", f.get(col))
            if isinstance(value, float):
                value = round(value, 3)
            row[col] = "" if value is None else value
        row.update(dict.fromkeys(RATERS, ""))
        rows.append(row)
    return rows


def kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's κ for two equal-length label lists. None when chance agreement is 1 (both
    raters used one label only), where κ is undefined."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two non-empty lists of the same length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / n / n
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def reason_coded(d: Decision) -> bool:
    """Every verdict other than accept names the rule behind it: a failed or unevaluated
    result with its rule id."""
    if d.outcome is Outcome.ACCEPT:
        return True
    return any(r.passed is not True and r.rule_id for r in d.results)


def score(rows: Sequence[Mapping[str, str]], decisions: Mapping[str, Decision]
          ) -> dict[str, Any]:
    """Agreement of each rater with the system, κ between raters and with the system, and
    the share of the system's verdicts that carry a reason code. Rows not fully labelled are
    an error: a half-rated sheet is not a result."""
    labels: dict[str, list[str]] = {r: [] for r in (*RATERS, "system")}
    disagreements = []
    for row in rows:
        sid = row["site_id"]
        given = {r: row.get(r, "").strip().lower() for r in RATERS}
        bad = {r: v for r, v in given.items() if v not in LABELS}
        if bad:
            raise ValueError(f"{sid}: {bad} is not one of {sorted(LABELS)}")
        system = decisions[sid].outcome.value
        for r, v in given.items():
            labels[r].append(v)
        labels["system"].append(system)
        if len({*given.values(), system}) > 1:
            disagreements.append({"site_id": sid, **given, "system": system})
    a, b, s = labels["rater_a"], labels["rater_b"], labels["system"]
    n = len(s)
    agree = [x == y for x, y in zip(a, b, strict=True)]
    return {
        "sites": n,
        "kappa_raters": kappa(a, b),
        "agreement_a": sum(x == y for x, y in zip(a, s, strict=True)) / n,
        "agreement_b": sum(x == y for x, y in zip(b, s, strict=True)) / n,
        "kappa_a_system": kappa(a, s),
        "kappa_b_system": kappa(b, s),
        "agreement_consensus": (
            sum(x == y for x, y, ok in zip(a, s, agree, strict=True) if ok) / sum(agree)
            if any(agree) else None),
        "reason_codes": sum(reason_coded(decisions[r["site_id"]]) for r in rows) / n,
        "disagreements": disagreements,
    }


def markdown(result: Mapping[str, Any]) -> str:
    def f(x: float | None) -> str:
        return "undefined" if x is None else f"{x:.2f}"

    lines = [
        f"Rules check, {result['sites']} test sites (design §6 Stage 4)", "",
        "| Measure | Value | Target |", "|---|---|---|",
        f"| κ between raters | {f(result['kappa_raters'])} | ≥ 0.7 |",
        f"| Rater A agrees with system | {result['agreement_a']:.0%} "
        f"(κ {f(result['kappa_a_system'])}) | 100% |",
        f"| Rater B agrees with system | {result['agreement_b']:.0%} "
        f"(κ {f(result['kappa_b_system'])}) | 100% |",
        "| Where raters agree, system agrees | "
        + ("n/a" if result["agreement_consensus"] is None
           else f"{result['agreement_consensus']:.0%}") + " | 100% |",
        f"| Verdicts with a reason code | {result['reason_codes']:.0%} | 100% |",
    ]
    if result["disagreements"]:
        lines += ["", "| Site | Rater A | Rater B | System |", "|---|---|---|---|"]
        lines += [f"| {d['site_id']} | {d['rater_a']} | {d['rater_b']} | {d['system']} |"
                  for d in result["disagreements"]]
    return "\n".join(lines)


def read_screened(url: str) -> Screened:
    """Re-screen every site from Postgres with the current register (no writes), keeping the
    facts each decision was made on."""
    import psycopg
    from psycopg.rows import dict_row

    from optev.graph.read import models
    from optev.reasoning import rules as R

    register, on_fail = R.load_register()
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        sites = models(CandidateSite, cur.execute(R.READ_SITES))
        car_parks = models(CarPark, cur.execute(R.READ_CAR_PARKS))
        indicators = models(SiteIndicators, cur.execute(R.READ_INDICATORS))
        context = {r["site_id"]: dict(r) for r in cur.execute(R.READ_CONTEXT)}
    return screened(sites, car_parks, indicators, context, register, on_fail)


def screened(sites: list[CandidateSite], car_parks: list[CarPark],
             indicators: list[SiteIndicators], context: dict[str, dict[str, object]],
             register: Any, on_fail: Any) -> Screened:
    from optev.reasoning import rules as R

    decisions, _ = R.screen(sites, car_parks, indicators, context, register, on_fail)
    by_cp = {cp.car_park_id: cp for cp in car_parks}
    latest: dict[str, SiteIndicators] = {}
    for ind in indicators:
        if ind.site_id not in latest or ind.window_end > latest[ind.site_id].window_end:
            latest[ind.site_id] = ind
    facts = {
        s.site_id: R.derive(R._facts(s, by_cp.get(s.car_park_id or ""), latest.get(s.site_id),
                                     context.get(s.site_id, {})))
        for s in sites
    }
    return Screened({d.site_id: d for d in decisions}, facts)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(prog="python -m optev.evaluation.rules_check")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sheet = sub.add_parser("sheet", help="write the blind rating sheet")
    p_sheet.add_argument("--out", type=Path, required=True)
    p_sheet.add_argument("--seed", type=int, default=0)
    p_score = sub.add_parser("score", help="score a rated sheet")
    p_score.add_argument("sheet", type=Path)
    p_score.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    load_dotenv(_ENV)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    found = read_screened(url)
    if args.cmd == "sheet":
        rows = sheet_rows(pick(found.decisions, seed=args.seed), found.facts)
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} sites to {args.out}")
        return 0
    with args.sheet.open(encoding="utf-8") as fh:
        text = markdown(score(list(csv.DictReader(fh)), found.decisions))
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
