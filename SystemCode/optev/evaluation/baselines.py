"""Baselines (#36-#38, SYSTEM_DESIGN.md §6): simple selection rules the optimiser must beat.

Each is a harness `Method`, `(Request, Inputs) -> Allocation`. It sees the same eligible sites
and the same room as every other method (`harness.eligible`, `harness.room`), so only the
selection logic differs (evaluation/CLAUDE.md). Plug one in with
`harness.compare(request, inputs, {"name": function})`.
"""

import math

from optev.contracts import Allocation, Coordinate, SiteIndicators
from optev.evaluation.harness import Inputs, Request, _plan, effective, eligible, room

EARTH_RADIUS_M = 6_371_000.0


def _metres(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance. Good to well under 1% at Singapore's scale, and enough to rank
    sites by spread; the evaluation must not import ingest's projection (§2.3 rule 4)."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.lon - a.lon) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def spatial_spread(request: Request, inputs: Inputs) -> Allocation:
    """#37: spread points as far as possible from existing charging, ignoring demand.

    Greedy max-min distance: each point goes to the eligible site with room that is farthest
    from every site already charging (existing, planned, or picked by this baseline), ties by
    site id. A site that gets a point starts charging, so the next point goes elsewhere; only
    when every eligible site has a point do sites get a second one."""
    c = effective(inputs)
    space = {s.site_id: room(s, c[s.site_id]) for s in eligible(request, inputs)}
    open_sites = {s.site_id: s for s in inputs.sites if space.get(s.site_id, 0) > 0}
    anchors = [s.coord for s in inputs.sites if c.get(s.site_id, 0) > 0]
    nearest = {sid: min((_metres(s.coord, a) for a in anchors), default=math.inf)
               for sid, s in open_sites.items()}
    counts: dict[str, int] = {}
    for _ in range(request.points):
        candidates = [sid for sid in open_sites if counts.get(sid, 0) < space[sid]]
        if not candidates:
            break
        pick = min(candidates, key=lambda sid: (-nearest[sid], sid))
        counts[pick] = counts.get(pick, 0) + 1
        where = open_sites[pick].coord
        for sid, site in open_sites.items():
            nearest[sid] = min(nearest[sid], _metres(site.coord, where))
    return _plan(request, counts)


def utilisation(indicators: list[SiteIndicators]) -> dict[str, float | None]:
    """Observed utilisation per site from its latest indicators window. None stays None:
    no supply is not "idle" (§2.3 rule 2)."""
    latest: dict[str, SiteIndicators] = {}
    for i in indicators:
        if i.site_id not in latest or i.window_end > latest[i.site_id].window_end:
            latest[i.site_id] = i
    return {sid: i.utilisation for sid, i in latest.items()}


def busiest_first(request: Request, inputs: Inputs) -> Allocation:
    """#36: put points where the existing chargers are busiest, ignoring demand.

    Eligible sites with room are ranked by observed utilisation, highest first, ties by site
    id; each is filled to its room before the next. Sites with no measured utilisation (no
    supply, or unobserved) come after every measured site, in site id order, never as 0."""
    c = effective(inputs)
    util = utilisation(inputs.indicators)
    space = {s.site_id: room(s, c[s.site_id]) for s in eligible(request, inputs)}

    def rank(sid: str) -> tuple[bool, float, str]:
        u = util.get(sid)
        return (u is None, -(u or 0.0), sid)

    counts: dict[str, int] = {}
    left = request.points
    for sid in sorted((s for s, r in space.items() if r > 0), key=rank):
        if not left:
            break
        counts[sid] = min(left, space[sid])
        left -= counts[sid]
    return _plan(request, counts)


def extend_existing(request: Request, inputs: Inputs) -> Allocation:
    """#38: add points where chargers already are, ignoring demand.

    Eligible sites with room that already charge (existing or planned connectors) are ranked
    by connectors, most first, ties by site id; points go round-robin down that ranking, so
    every charging site is extended before any gets a second. Once they are all full, the
    remaining points go to the other eligible sites in site id order."""
    c = effective(inputs)
    space = {s.site_id: room(s, c[s.site_id]) for s in eligible(request, inputs)}
    charging = sorted((sid for sid, r in space.items() if r > 0 and c[sid] > 0),
                      key=lambda sid: (-c[sid], sid))
    counts: dict[str, int] = {}
    left = request.points
    while left and charging:
        for sid in charging:
            if not left:
                break
            counts[sid] = counts.get(sid, 0) + 1
            left -= 1
        charging = [sid for sid in charging if counts[sid] < space[sid]]
    for sid in sorted(sid for sid, r in space.items() if r > 0 and c[sid] == 0):
        if not left:
            break
        counts[sid] = min(left, space[sid])
        left -= counts[sid]
    return _plan(request, counts)
