"""Stage 3 robustness (design §4.3 "Checked by", §6): does the plan's top 10 survive changes
in the declared growth and in measured demand?

    uv run python -m optev.evaluation.stability --scenario base --points 30

For each perturbation the optimiser re-plans the same request on scaled demand, and the
result is the share of the baseline plan's top sites (most points, then most drivers
rescued) still in the perturbed plan's top. Target: at least 7 of 10 stay (§6).
- growth ±20%: every rate × 0.8 or × 1.2, the uncertainty in the 2030 multiplier;
- demand ±10%: each site's rate × a factor drawn in [0.9, 1.1] (fixed seeds), the
  measurement noise.
"""

import argparse
import os
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from optev.contracts import Allocation, DemandEstimate

from .harness import Inputs, Request

TOP = 10
TARGET = 7
SEEDS = 5


@dataclass
class Result:
    perturbation: str
    kept: int
    of: int

    @property
    def share(self) -> float:
        return self.kept / self.of if self.of else 1.0


def top(plan: Allocation, k: int = TOP) -> list[str]:
    ranked = sorted(plan.items, key=lambda i: (-i.connectors, -(i.marginal_relief or 0.0),
                                               i.site_id))
    return [i.site_id for i in ranked[:k]]


def scaled(demand: list[DemandEstimate], factor: Callable[[str], float]) -> list[DemandEstimate]:
    return [e.model_copy(update={"arrivals_per_hour": e.arrivals_per_hour * factor(e.site_id)})
            for e in demand]


def plan_for(inputs: Inputs, request: Request, demand: list[DemandEstimate]) -> Allocation:
    from optev.reasoning.allocate import allocate

    result = allocate(inputs.decisions, inputs.sites, demand, inputs.scenario,
                      planning_area=request.planning_area, requested_connectors=request.points)
    if not isinstance(result, Allocation):
        raise RuntimeError(f"request infeasible: {result}")
    return result


def stability(inputs: Inputs, request: Request) -> list[Result]:
    base = top(plan_for(inputs, request, inputs.demand))
    out = []
    for label, g in (("growth -20%", 0.8), ("growth +20%", 1.2)):
        uniform: dict[str, float] = {e.site_id: g for e in inputs.demand}
        moved = top(plan_for(inputs, request, scaled(inputs.demand, uniform.__getitem__)))
        out.append(Result(label, len(set(base) & set(moved)), len(base)))
    sites = sorted({e.site_id for e in inputs.demand})
    for seed in range(SEEDS):
        rng = random.Random(seed)
        noise = {s: rng.uniform(0.9, 1.1) for s in sites}
        moved = top(plan_for(inputs, request, scaled(inputs.demand, noise.__getitem__)))
        out.append(Result(f"demand ±10% (seed {seed})", len(set(base) & set(moved)),
                          len(base)))
    return out


def markdown(results: list[Result]) -> str:
    rows = ["| Perturbation | Top sites kept | Share | Meets ≥ 7 of 10 |", "|---|---|---|---|"]
    for r in results:
        ok = r.kept >= min(TARGET, r.of)
        rows.append(f"| {r.perturbation} | {r.kept} of {r.of} | {r.share:.0%} | "
                    f"{'yes' if ok else 'no'} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    from .real import read_inputs

    parser = argparse.ArgumentParser(prog="python -m optev.evaluation.stability")
    parser.add_argument("--scenario", default="base")
    parser.add_argument("--area", default=None)
    parser.add_argument("--points", type=int, default=30)
    args = parser.parse_args(argv)
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    inputs = read_inputs(url, args.scenario)
    print(f"Top-{TOP} stability, {args.points} points, scenario {args.scenario}, "
          f"{args.area or 'island-wide'}\n")
    print(markdown(stability(inputs, Request(args.scenario, args.points, args.area))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
