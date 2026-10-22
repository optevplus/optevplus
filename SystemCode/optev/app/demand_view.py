"""What the Demand page shows (#33). Pure functions over `AppData`, tested without Streamlit.

Indicators are measured, so they are OBSERVED; demand and patterns come from the analysis
package's models, so they are INFERRED (app/CLAUDE.md). A lower bound always reads "at least":
the site was saturated and turned drivers away, so the true demand is higher. Nothing is
computed here beyond joining rows per site.
"""

from typing import Any

from optev.app.data import AppData
from optev.contracts import DemandEstimate
from optev.contracts.enums import EstimateKind, SupplyState

DAY_TYPE = {"wd": "weekday", "we": "weekend"}


def figure(estimate: DemandEstimate | None, digits: int = 2) -> str | None:
    """Arrivals per hour as the planner should read it: "at least" for a lower bound."""
    if estimate is None:
        return None
    rate = f"{estimate.arrivals_per_hour:.{digits}f}"
    return f"at least {rate}" if estimate.kind == EstimateKind.LOWER_BOUND else rate


def supply_counts(data: AppData) -> dict[str, int]:
    """Sites per supply state (all four always present)."""
    out = {s.value: 0 for s in SupplyState}
    for i in data.indicators:
        out[i.supply_state.value] += 1
    return out


def _pattern(data: AppData, site_id: str) -> str | None:
    cluster = data.patterns.get(site_id)
    if cluster is None:
        return None
    return data.pattern_labels.get(cluster, f"cluster {cluster}")


def demand_table(data: AppData, planning_area: str | None = None) -> list[dict[str, Any]]:
    """One row per site: what was measured there, its pattern, and the demand inferred."""
    indicators = {i.site_id: i for i in data.indicators}
    estimates = {e.site_id: e for e in data.estimates}
    rows = []
    for s in sorted(data.sites, key=lambda s: s.site_id):
        if planning_area and s.planning_area != planning_area:
            continue
        i, e = indicators.get(s.site_id), estimates.get(s.site_id)
        rows.append({
            "site_id": s.site_id,
            "kind": s.kind.value,
            "planning_area": s.planning_area,
            "supply_state (observed)": i.supply_state.value if i else None,
            "active_points (observed)": i.active_connectors if i else None,
            "utilisation (observed)": i.utilisation if i else None,
            "saturated_share (observed)": i.saturated_fraction if i else None,
            "coverage (observed)": i.observation_coverage if i else None,
            "pattern (inferred)": _pattern(data, s.site_id),
            "demand_per_h (inferred)": figure(e),
            "lower_bound": bool(e and e.kind == EstimateKind.LOWER_BOUND),
            "method": e.note if e else None,
        })
    return rows


def profile(data: AppData, site_id: str) -> list[dict[str, Any]]:
    """The site's inferred arrivals per hour of the day, weekday and weekend, in bin order."""
    rows = []
    for e in sorted((e for e in data.profiles if e.site_id == site_id),
                    key=lambda e: e.time_bin):
        half, hour = e.time_bin.split("-")
        rows.append({
            "time_bin": e.time_bin,
            "day": DAY_TYPE[half],
            "hour": int(hour),
            "arrivals_per_h (inferred)": round(e.arrivals_per_hour, 2),
            "reads as": figure(e),
            "lower_bound": e.kind == EstimateKind.LOWER_BOUND,
        })
    return rows


def pattern_rows(data: AppData) -> list[dict[str, Any]]:
    """Each usage pattern found, with its sites, in cluster order."""
    members: dict[int, list[str]] = {}
    for site_id, cluster in sorted(data.patterns.items()):
        members.setdefault(cluster, []).append(site_id)
    return [{
        "cluster": c,
        "pattern (inferred)": data.pattern_labels.get(c, f"cluster {c}"),
        "sites": len(ids),
        "site_ids": ", ".join(ids),
    } for c, ids in sorted(members.items())]
