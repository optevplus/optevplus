"""Experiment harness (#39, SYSTEM_DESIGN.md §6): one command, one comparison table.

Every method answers the same request (scenario, area, points) with the same eligible sites
and room, and every plan is scored by the same objective as the optimiser (§4.4): drivers per
hour rescued, `Σ_site Σ_bin w × λ × (B(c, a) − B(c + x, a))`. Scoring and the constraint
checks are written here from the design, not imported from `reasoning/`, so the yardstick
cannot share a bug with what it measures.

Baselines built here (§6): `random` (averaged over 100 seeds) and `population share`.
Other methods (the optimiser, #36–#38 baselines) plug in as functions returning an Allocation.

    uv run python -m optev.evaluation.harness          # on optev.sample
"""

import math
import random
import re
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from optev.assumptions import COST_PER_POINT_SGD, MAX_SHARE_OF_LOTS, MEAN_SESSION_HOURS
from optev.contracts import (
    Allocation,
    AllocationItem,
    CandidateSite,
    Decision,
    DemandEstimate,
    Outcome,
    Scenario,
    SiteIndicators,
)

WEIGHT = {"wd": 5 / 7 / 24, "we": 2 / 7 / 24}  # §4.4: 48 bins weighted to an average hour
_BIN = re.compile(r"^(wd|we)-\d{2}$")
SEEDS = 100


@dataclass(frozen=True)
class Request:
    scenario_id: str
    points: int
    planning_area: str | None = None


@dataclass
class Inputs:
    """What every method sees. Effective connectors include the scenario's planned picks."""

    decisions: list[Decision]
    sites: list[CandidateSite]
    demand: list[DemandEstimate]
    scenario: Scenario
    residents: dict[str, int] = field(default_factory=dict)
    indicators: list[SiteIndicators] = field(default_factory=list)  # observed, for #36


Method = Callable[[Request, Inputs], Allocation]


# The yardstick ------------------------------------------------------------------------------

def erlang_b(servers: int, load: float) -> float:
    b = 1.0
    for k in range(1, servers + 1):
        b = load * b / (k + load * b)
    return b


def profiles(demand: list[DemandEstimate]) -> dict[str, list[tuple[float, float]]]:
    """(weight, arrivals per hour) per site; an `all`-only site counts once at weight 1."""
    bins: dict[str, list[tuple[float, float]]] = {}
    overall: dict[str, float] = {}
    for e in demand:
        found = _BIN.match(e.time_bin)
        if found:
            bins.setdefault(e.site_id, []).append((WEIGHT[found.group(1)], e.arrivals_per_hour))
        elif e.time_bin == "all":
            overall[e.site_id] = e.arrivals_per_hour
    return {s: bins.get(s) or [(1.0, overall[s])] for s in set(bins) | set(overall)}


def effective(inputs: Inputs) -> dict[str, int]:
    planned: dict[str, int] = {}
    for pick in inputs.scenario.planned:
        planned[pick.site_id] = planned.get(pick.site_id, 0) + pick.connectors
    return {s.site_id: s.existing_connectors + planned.get(s.site_id, 0) for s in inputs.sites}


def room(site: CandidateSite, connectors: int) -> int:
    if site.total_lots is None:
        return 0
    return max(0, math.floor(round(MAX_SHARE_OF_LOTS.value * site.total_lots, 9)) - connectors)


def rescued(plan: Allocation, inputs: Inputs) -> float:
    """Drivers per hour rescued by the plan's new points (§4.4 objective)."""
    prof, c = profiles(inputs.demand), effective(inputs)
    total = 0.0
    for item in plan.items:
        for w, lam in prof.get(item.site_id, []):
            a = lam * MEAN_SESSION_HOURS.value
            base = c.get(item.site_id, 0)
            total += w * lam * (erlang_b(base, a) - erlang_b(base + item.connectors, a))
    return total


def eligible(request: Request, inputs: Inputs) -> list[CandidateSite]:
    ok = {d.site_id for d in inputs.decisions
          if d.outcome in (Outcome.ACCEPT, Outcome.CONDITIONAL)
          and (d.scenario_id or "observed") in ("observed", request.scenario_id)}
    return [s for s in inputs.sites if s.site_id in ok
            and (request.planning_area is None or s.planning_area == request.planning_area)]


def violations(plan: Allocation, request: Request, inputs: Inputs) -> list[str]:
    allowed = {s.site_id: s for s in eligible(request, inputs)}
    c = effective(inputs)
    out = []
    for item in plan.items:
        site = allowed.get(item.site_id)
        if site is None:
            out.append(f"{item.site_id}: not eligible for this request")
        elif item.connectors > room(site, c[site.site_id]):
            out.append(f"{item.site_id}: {item.connectors} points, room for "
                       f"{room(site, c[site.site_id])}")
    if plan.total_connectors > request.points:
        out.append(f"places {plan.total_connectors} points, {request.points} requested")
    return out


# Baselines built here -------------------------------------------------------------------

def _plan(request: Request, counts: dict[str, int]) -> Allocation:
    return Allocation(
        scenario_id=request.scenario_id, planning_area=request.planning_area,
        requested_connectors=request.points,
        items=[AllocationItem(site_id=s, connectors=n, cost=n * COST_PER_POINT_SGD.value)
               for s, n in sorted(counts.items()) if n])


def random_plan(request: Request, inputs: Inputs, seed: int) -> Allocation:
    """Each point goes to a uniformly random eligible site that still has room."""
    rng = random.Random(seed)
    c = effective(inputs)
    space = {s.site_id: room(s, c[s.site_id]) for s in eligible(request, inputs)}
    counts: dict[str, int] = {}
    for _ in range(request.points):
        open_sites = sorted(s for s, r in space.items() if counts.get(s, 0) < r)
        if not open_sites:
            break
        pick = rng.choice(open_sites)
        counts[pick] = counts.get(pick, 0) + 1
    return _plan(request, counts)


def population_share(request: Request, inputs: Inputs) -> Allocation:
    """Points split across planning areas by residents (largest remainder), then within an
    area to the sites with the most car lots. Lots stand in for people when no residents are
    given (the sample has none)."""
    c = effective(inputs)
    sites = eligible(request, inputs)
    by_area: dict[str, list[CandidateSite]] = {}
    for s in sites:
        by_area.setdefault(s.planning_area or "?", []).append(s)
    use_residents = bool(inputs.residents)
    weight = {a: float(inputs.residents.get(a, 0) if use_residents
                       else sum(s.total_lots or 0 for s in ss))
              for a, ss in by_area.items()}
    total = sum(weight.values()) or 1.0
    exact = {a: request.points * w / total for a, w in weight.items()}
    share = {a: int(v) for a, v in exact.items()}
    for a in sorted(exact, key=lambda k: exact[k] - share[k], reverse=True)[
            : request.points - sum(share.values())]:
        share[a] += 1
    counts: dict[str, int] = {}
    for area, n in share.items():
        ranked = sorted(by_area[area], key=lambda s: (-(s.total_lots or 0), s.site_id))
        for s in ranked:
            take = min(n, room(s, c[s.site_id]))
            if take:
                counts[s.site_id] = take
                n -= take
            if not n:
                break
    return _plan(request, counts)


# The table ------------------------------------------------------------------------------

@dataclass
class Row:
    method: str
    points: int
    rescued: float
    rescued_sd: float
    per_point: float
    vs_best_baseline: float
    violations: int
    runtime_ms: float


def compare(request: Request, inputs: Inputs,
            methods: dict[str, Method] | None = None) -> list[Row]:
    """Score every method on the same request. `vs_best_baseline` is each method's rescued
    drivers over the best baseline's (the design's end-to-end number, per point)."""
    rows: list[Row] = []
    t0 = time.perf_counter()
    plans = [random_plan(request, inputs, seed) for seed in range(SEEDS)]
    scores = [rescued(p, inputs) for p in plans]
    rows.append(Row("random (mean of 100)", round(statistics.mean(p.total_connectors
                                                                  for p in plans)),
                    statistics.mean(scores), statistics.pstdev(scores), 0.0, 0.0,
                    sum(len(violations(p, request, inputs)) for p in plans),
                    (time.perf_counter() - t0) * 1000 / SEEDS))
    for name, method in {"population share": population_share, **(methods or {})}.items():
        t0 = time.perf_counter()
        plan = method(request, inputs)
        ms = (time.perf_counter() - t0) * 1000
        rows.append(Row(name, plan.total_connectors, rescued(plan, inputs), 0.0, 0.0, 0.0,
                        len(violations(plan, request, inputs)), ms))
    best = max(r.rescued for r in rows[:2]) or 1.0  # random and population share
    for r in rows:
        r.per_point = r.rescued / r.points if r.points else 0.0
        r.vs_best_baseline = r.rescued / best
    return rows


def markdown(rows: list[Row]) -> str:
    out = ["| Method | Points | Drivers rescued / h | Per point | vs best baseline "
           "| Violations | Runtime ms |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        sd = f" ± {r.rescued_sd:.3f}" if r.rescued_sd else ""
        out.append(f"| {r.method} | {r.points} | {r.rescued:.3f}{sd} | {r.per_point:.3f} | "
                   f"{r.vs_best_baseline:.2f}× | {r.violations} | {r.runtime_ms:.1f} |")
    return "\n".join(out)


def sample_inputs() -> tuple[Request, Inputs, dict[str, Method]]:
    """The sample's request and its reference plan, plus the optimiser once it is merged."""
    from optev.sample import load

    s = load()
    scenario = next(sc for sc in s.scenarios if sc.scenario_id == s.allocation.scenario_id)
    request = Request(scenario.scenario_id, s.allocation.requested_connectors or 0,
                      s.allocation.planning_area)
    # Stage 3 projection (§4.3): observed estimate × the scenario's growth, lower bounds kept.
    projected = [e.model_copy(update={"arrivals_per_hour":
                                      e.arrivals_per_hour * scenario.growth_multiplier})
                 for e in s.estimates]
    inputs = Inputs(s.decisions, s.sites, projected, scenario, indicators=s.indicators)
    from optev.evaluation.baselines import (  # here: baselines imports harness
        busiest_first,
        spatial_spread,
    )

    methods: dict[str, Method] = {"sample reference (greedy)": lambda r, i: s.allocation,
                                  "busiest first (#36)": busiest_first,
                                  "spatial spread (#37)": spatial_spread}
    try:
        from optev.reasoning.allocate import allocate  # type: ignore[import-not-found]

        def optimiser(r: Request, i: Inputs) -> Allocation:
            result = allocate(i.decisions, i.sites, i.demand, i.scenario,
                              planning_area=r.planning_area, requested_connectors=r.points)
            if not isinstance(result, Allocation):
                raise RuntimeError(f"optimiser found the request infeasible: {result}")
            return result

        methods["optimiser (CP-SAT)"] = optimiser
    except ImportError:
        pass
    return request, inputs, methods


if __name__ == "__main__":
    req, data, extra = sample_inputs()
    print(f"Request: {req.points} points, scenario {req.scenario_id}, "
          f"area {req.planning_area or 'island-wide'} (optev.sample)\n")
    print(markdown(compare(req, data, extra)))
