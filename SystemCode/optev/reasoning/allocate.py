"""Where the new charging points go, and how many at each site. SYSTEM_DESIGN.md §4.4
(#20 cost model and constraints, #21 allocator), spec 015.

Pure: decisions, sites, demand and the scenario come in as contracts, an `Allocation` or an
`InfeasibilityReport` goes out. Nothing here touches the database or another workstream's
code. The plan is unchecked (`checked = False`): only the independent checker (#22) approves it.
"""

import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
from ortools.sat.python import cp_model

from optev.assumptions import COST_PER_POINT_SGD, MAX_SHARE_OF_LOTS, MEAN_SESSION_HOURS
from optev.contracts import (
    Allocation,
    AllocationItem,
    CandidateSite,
    Decision,
    DemandEstimate,
    InfeasibilityReport,
    Outcome,
    Scenario,
)

log = logging.getLogger(__name__)

ELIGIBLE = frozenset({Outcome.ACCEPT, Outcome.CONDITIONAL})
BASELINE = frozenset({None, "observed"})  # decisions that belong to no scenario (§3.2)
WEIGHT = {"wd": 5 / 7 / 24, "we": 2 / 7 / 24}  # share of an average hour; 48 bins sum to 1
SCALE = 1000  # objective coefficients to integers (§4.4)
TIME_LIMIT_S = 30.0  # §4.4
_BIN = re.compile(r"^(wd|we)-([01][0-9]|2[0-3])$")

Profile = list[tuple[float, float]]  # (weight, arrivals per hour) per time bin


# Cost model and constraints (#20) ------------------------------------------------------


def erlang_b(c: int, a: float) -> float:
    """Erlang B: the share of drivers turned away at `c` connectors under offered load `a`.
    A private copy of §4.2's, because packages do not import each other (§2.3 rule 4)."""
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b


def effective_connectors(sites: Iterable[CandidateSite], scenario: Scenario) -> dict[str, int]:
    """Existing plus this scenario's planned connectors per site (§4.3), from the contract."""
    planned: dict[str, int] = defaultdict(int)
    for p in scenario.planned:
        planned[p.site_id] += p.connectors
    return {s.site_id: s.existing_connectors + planned[s.site_id] for s in sites}


def room(total_lots: int | None, connectors: int) -> int:
    """`floor(MAX_SHARE_OF_LOTS × total_lots) − connectors`, floored at 0. Without a lot count
    no limit can be stated, so there is no room."""
    if total_lots is None:
        return 0
    # round first so 0.15 x 60 = 9.000000000000002 or 8.999999999999998 floors to 9
    cap = math.floor(round(MAX_SHARE_OF_LOTS.value * total_lots, 9))
    return max(0, cap - connectors)


def demand_profile(demand: Iterable[DemandEstimate]) -> dict[str, Profile]:
    """Per site, the weighted weekday and weekend bins (§3.4). A site with only an `all` rate
    gets it with weight 1, the same as a flat profile (spec 015, raised for review)."""
    bins: dict[str, Profile] = defaultdict(list)
    overall: dict[str, float] = {}
    for e in demand:
        found = _BIN.match(e.time_bin)
        if found:
            bins[e.site_id].append((WEIGHT[found.group(1)], e.arrivals_per_hour))
        elif e.time_bin == "all":
            overall[e.site_id] = e.arrivals_per_hour
    return {s: bins.get(s) or [(1.0, overall[s])] for s in set(bins) | set(overall)}


def marginal_gains(c: int, profile: Profile, n: int) -> list[float]:
    """Drivers per hour rescued by the 1st…nth new point at a site with `c` connectors:
    `Σ_bin w × λ × (B(c+k−1, a) − B(c+k, a))`, `a = λ × MEAN_SESSION_HOURS`. Erlang B is
    convex in servers, so the gains never increase with k."""
    if n <= 0:
        return []
    if not profile:
        return [0.0] * n
    w = np.array([p[0] for p in profile])
    lam = np.array([p[1] for p in profile])
    a = lam * MEAN_SESSION_HOURS.value
    blocking = [np.ones_like(a)]  # B(0, a) = 1
    for servers in range(1, c + n + 1):
        b = blocking[-1]
        blocking.append(a * b / (servers + a * b))
    return [float(np.sum(w * lam * (blocking[c + k] - blocking[c + k + 1]))) for k in range(n)]


def eligible_sites(
    decisions: Iterable[Decision], sites: Iterable[CandidateSite], scenario_id: str,
    planning_area: str | None,
) -> list[CandidateSite]:
    """Sites whose decision is accept or conditional, inside `planning_area` when given. A
    site's own decision for this scenario wins over the baseline one (spec 015)."""
    own: dict[str, Decision] = {}
    base: dict[str, Decision] = {}
    for d in decisions:
        if d.scenario_id == scenario_id:
            own[d.site_id] = d
        elif d.scenario_id in BASELINE:
            base[d.site_id] = d
    out = []
    for s in sites:
        chosen = own.get(s.site_id) or base.get(s.site_id)
        if chosen and chosen.outcome in ELIGIBLE and planning_area in (None, s.planning_area):
            out.append(s)
    return sorted(out, key=lambda s: s.site_id)


def points_for(requested_connectors: int | None, budget: float | None) -> int:
    """The number of points to place: the request, or as many as the budget pays for."""
    if requested_connectors is None and budget is None:
        raise ValueError("give requested_connectors, budget, or both")
    if requested_connectors is not None:
        return requested_connectors
    assert budget is not None
    return math.floor(budget / COST_PER_POINT_SGD.value + 1e-9)


def budget_cap(budget: float | None) -> int | None:
    """`COST_PER_POINT_SGD × Σx ≤ budget` as a whole number of points."""
    return None if budget is None else math.floor(budget / COST_PER_POINT_SGD.value + 1e-9)


# CP-SAT (#21) ---------------------------------------------------------------------------


def _solver() -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_S
    solver.parameters.num_workers = 1  # one worker, fixed seed: the same plan every run
    solver.parameters.random_seed = 0
    return solver


def solve(
    gains: Mapping[str, Sequence[float]], points: int, cap: int | None,
) -> dict[str, int] | None:
    """The plan maximising drivers rescued: `y[site, k]` for the k-th new point, ordered
    `y[k] ≥ y[k+1]`, `Σx = points`, `Σx ≤ cap` (budget), `x ≤ room` (the length of each
    site's gain list). No minimum per area (design 1.8). None when no plan meets them."""
    model = cp_model.CpModel()
    y = {s: [model.new_bool_var(f"y_{s}_{k}") for k in range(len(g))] for s, g in gains.items()}
    for ys in y.values():
        for k in range(len(ys) - 1):
            model.add(ys[k] >= ys[k + 1])
    x = {s: sum(ys) for s, ys in y.items()}
    model.add(sum(x.values()) == points)
    if cap is not None:
        model.add(sum(x.values()) <= cap)
    model.maximize(sum(round(SCALE * g) * v for s, gs in gains.items()
                       for g, v in zip(gs, y[s], strict=True)))
    solver = _solver()
    status = solver.solve(model)
    name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log.info("allocate: %s after %.1f s", name, solver.wall_time)
        if status == cp_model.UNKNOWN:
            raise RuntimeError(f"no plan found within {TIME_LIMIT_S:.0f} s")
        return None
    value, bound = solver.objective_value, solver.best_objective_bound
    log.info("allocate: %s, objective %.0f, gap %.4f, %.1f s", name, value,
             (bound - value) / max(1.0, abs(value)), solver.wall_time)
    return {s: n for s, ys in y.items() if (n := sum(solver.value(v) for v in ys))}


def most_points(rooms: Mapping[str, int], cap: int | None) -> int:
    """The most connectors any plan allows under room and budget."""
    model = cp_model.CpModel()
    x = {s: model.new_int_var(0, r, f"x_{s}") for s, r in rooms.items()}
    if cap is not None:
        model.add(sum(x.values()) <= cap)
    model.maximize(sum(x.values()))
    solver = _solver()
    status = solver.solve(model)
    return int(solver.objective_value) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0


def allocate(decisions: list[Decision], sites: list[CandidateSite],
             demand: list[DemandEstimate], scenario: Scenario, *,
             planning_area: str | None = None, requested_connectors: int | None = None,
             budget: float | None = None) -> Allocation | InfeasibilityReport:
    """Place the requested points (or as many as the budget pays for) to rescue the most
    drivers per hour. The request is copied onto the result; `checked` stays False."""
    points = points_for(requested_connectors, budget)
    pool = eligible_sites(decisions, sites, scenario.scenario_id, planning_area)
    c = effective_connectors(pool, scenario)
    rooms = {s.site_id: room(s.total_lots, c[s.site_id]) for s in pool}
    profile = demand_profile(demand)
    gains = {s.site_id: marginal_gains(c[s.site_id], profile.get(s.site_id, []),
                                       min(rooms[s.site_id], points)) for s in pool}
    plan = solve(gains, points, budget_cap(budget))
    if plan is None:
        return InfeasibilityReport(
            scenario_id=scenario.scenario_id, planning_area=planning_area,
            requested_connectors=points, max_feasible=most_points(rooms, budget_cap(budget)))
    cost = COST_PER_POINT_SGD.value
    return Allocation(
        scenario_id=scenario.scenario_id, planning_area=planning_area,
        requested_connectors=requested_connectors, budget=budget,
        items=[AllocationItem(site_id=s, connectors=n, cost=cost * n,
                              marginal_relief=round(sum(gains[s][:n]), 4))
               for s, n in sorted(plan.items())],
    )
