"""The comparison table on the real data (#39, design §6 Stage 4).

    uv run python -m optev.evaluation.real --scenario base --points 12 50 100 [--area TM]

Same harness, same yardstick, same request for every method; the inputs come from Postgres
after a pipeline run instead of from the sample: eligible sites from the rules, the
scenario's projected demand, measured utilisation (for busiest first) and residents per
planning area (for population share).
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from optev.contracts import Allocation, SiteIndicators

from .harness import Inputs, Method, Request, compare, markdown

_ENV = Path(__file__).resolve().parents[2] / ".env"


def methods() -> dict[str, Method]:
    """The optimiser and every registered baseline (random and population share are built
    into the harness)."""
    from optev.reasoning.allocate import allocate

    from . import baselines

    def optimiser(r: Request, i: Inputs) -> Allocation:
        result = allocate(i.decisions, i.sites, i.demand, i.scenario,
                          planning_area=r.planning_area, requested_connectors=r.points)
        if not isinstance(result, Allocation):
            raise RuntimeError(f"optimiser found the request infeasible: {result}")
        return result

    found: dict[str, Method] = {"optimiser (CP-SAT)": optimiser}
    for name, label in (("busiest_first", "busiest first (#36)"),
                        ("spatial_spread", "spatial spread (#37)"),
                        ("extend_existing", "extend existing (#38)")):
        if hasattr(baselines, name):
            found[label] = getattr(baselines, name)
    return found


def real_inputs(q: Any, scenario_id: str) -> Inputs:
    """Inputs from `q(name, *params) -> rows` (the pipeline's planning query plus indicators
    and residents), so tests can pass canned rows."""
    from optev.graph.read import models
    from optev.pipeline import planning_inputs

    planning, demand = planning_inputs(q, scenario_id)
    indicators = models(SiteIndicators, q("indicators"))
    residents = {r["planning_area"]: r["residents"] for r in q("residents")}
    return Inputs(planning["decisions"], planning["sites"], demand, planning["scenario"],
                  residents=residents, indicators=indicators)


def read_inputs(url: str, scenario_id: str) -> Inputs:
    import psycopg
    from psycopg.rows import dict_row

    from optev.graph.read import SQL
    from optev.pipeline import PLANNING_SQL

    queries = {**PLANNING_SQL, "indicators": SQL["indicators"],
               "residents": "SELECT planning_area, residents FROM stg_residents"}
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        has_residents = cur.execute("SELECT to_regclass('stg_residents') IS NOT NULL AS ok"
                                    ).fetchone()

        def q(name: str, *params: Any) -> list[dict[str, Any]]:
            if name == "residents" and not (has_residents and has_residents["ok"]):
                return []
            return list(cur.execute(queries[name], params or None))

        return real_inputs(q, scenario_id)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(prog="python -m optev.evaluation.real")
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--area", default=None)
    parser.add_argument("--points", type=int, nargs="+", default=[12])
    parser.add_argument("--out", type=Path, default=None, help="also write the tables here")
    args = parser.parse_args(argv)
    load_dotenv(_ENV)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    inputs = read_inputs(url, args.scenario)
    found = methods()
    out = []
    for n in args.points:
        request = Request(args.scenario, n, args.area)
        title = (f"### {n} points, scenario {args.scenario}, "
                 f"{args.area or 'island-wide'} (from Postgres)")
        out += [title, "", markdown(compare(request, inputs, found)), ""]
        print("\n".join(out[-4:]))
    if args.out:
        args.out.write_text("\n".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
