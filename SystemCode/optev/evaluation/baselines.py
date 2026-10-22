"""Baselines (#36-#38, SYSTEM_DESIGN.md §6): simple selection rules the optimiser must beat.

Each is a harness `Method`, `(Request, Inputs) -> Allocation`. It sees the same eligible sites
and the same room as every other method (`harness.eligible`, `harness.room`), so only the
selection logic differs (evaluation/CLAUDE.md). Plug one in with
`harness.compare(request, inputs, {"name": function})`.
"""

import math

from optev.contracts import Allocation, Coordinate
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
