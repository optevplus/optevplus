"""Demand inference (SYSTEM_DESIGN.md §4.2 step 2): from how busy a site's chargers were to
how many drivers per hour wanted one, including those turned away when every point was busy.

Each site is an Erlang loss system: `c` active connectors, arrivals that leave when all are
busy. Occupancy is inverted per time bin, never once over the whole window, because demand
peaks in the evening. Spec 012 records how far this recovers the sample's known demand.
"""

import logging

import psycopg

from optev.assumptions import MEAN_SESSION_HOURS, RELIABLE_UP_TO
from optev.contracts import DemandEstimate, SiteIndicators
from optev.contracts.enums import EstimateKind, SupplyState

log = logging.getLogger(__name__)

MEASURED = {SupplyState.SUPPLY_ACTIVE, SupplyState.SUPPLY_IDLE}
METHOD = "queueing"
_STEPS = 100  # bisection halvings; far below float resolution of the bracket

POINT_NOTE = "Erlang B inversion of observed occupancy"
BOUND_NOTE = "occupancy at or above the reliable limit; demand is at least this"


def erlang_b(c: int, a: float) -> float:
    """Share of arrivals turned away with `c` servers and offered load `a` (Erlang B)."""
    if c < 0 or a < 0:
        raise ValueError(f"need c >= 0 and a >= 0, got c={c}, a={a}")
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b


def _occupancy(c: int, a: float) -> float:
    """Mean share of the `c` connectors busy: carried load per connector."""
    return a * (1 - erlang_b(c, a)) / c


def invert_occupancy(c: int, occupancy: float) -> float:
    """Arrivals per hour that give `occupancy` on `c` connectors, by bisection on the offered
    load (occupancy rises monotonically in it), divided by MEAN_SESSION_HOURS."""
    if c < 1:
        raise ValueError(f"need at least one connector, got {c}")
    if not 0 <= occupancy < 1:
        raise ValueError(f"occupancy must be in [0, 1), got {occupancy}")
    if occupancy == 0:
        return 0.0
    lo, hi = 0.0, float(c)
    while _occupancy(c, hi) < occupancy:
        lo, hi = hi, 2 * hi
    for _ in range(_STEPS):
        mid = (lo + hi) / 2
        if _occupancy(c, mid) < occupancy:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 / MEAN_SESSION_HOURS.value


def _all(per_bin: dict[str, float]) -> float:
    """The daily average of §3.4; the mean of the bins there are if only one kind was seen."""
    wd = [v for b, v in per_bin.items() if b.startswith("wd")]
    we = [v for b, v in per_bin.items() if b.startswith("we")]
    if wd and we:
        return (5 * sum(wd) / len(wd) + 2 * sum(we) / len(we)) / 7
    return sum(wd or we) / len(wd or we)


def _estimate(site: str, time_bin: str, rate: float, bounded: bool) -> DemandEstimate:
    return DemandEstimate(site_id=site, time_bin=time_bin, arrivals_per_hour=rate,
                          kind=EstimateKind.LOWER_BOUND if bounded else EstimateKind.POINT,
                          note=BOUND_NOTE if bounded else POINT_NOTE)


def infer_demand(indicators: list[SiteIndicators],
                 occupancy: dict[str, dict[str, float]]) -> list[DemandEstimate]:
    """Per-bin estimates plus `all` for every site with measured supply. A bin at or above
    RELIABLE_UP_TO is reported at RELIABLE_UP_TO as a lower bound; `all` is a lower bound when
    the site's window utilisation is. The `all` in `occupancy` is not used."""
    cap = RELIABLE_UP_TO.value
    out: list[DemandEstimate] = []
    for ind in indicators:
        bins = {b: v for b, v in occupancy.get(ind.site_id, {}).items() if b != "all"}
        if ind.supply_state not in MEASURED or not bins:
            continue
        c = ind.active_connectors
        rates = {}
        for b, occ in sorted(bins.items()):
            rates[b] = invert_occupancy(c, min(occ, cap))
            out.append(_estimate(ind.site_id, b, rates[b], occ >= cap))
        saturated = ind.utilisation is not None and ind.utilisation >= cap
        out.append(_estimate(ind.site_id, "all", _all(rates), saturated))
    return out


_UPSERT_SQL = """
INSERT INTO demand_estimate (site_id, time_bin, arrivals_per_hour, kind, method, note)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (site_id, time_bin) DO UPDATE SET
    arrivals_per_hour = EXCLUDED.arrivals_per_hour, kind = EXCLUDED.kind,
    method = EXCLUDED.method, note = EXCLUDED.note
"""


def write_estimates(conn: psycopg.Connection, estimates: list[DemandEstimate]) -> int:
    """Upsert into `demand_estimate` with method 'queueing', without committing."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, [
            (e.site_id, e.time_bin, e.arrivals_per_hour, e.kind.value, METHOD, e.note)
            for e in estimates
        ])
    log.info("write_estimates: %d rows", len(estimates))
    return len(estimates)
