"""Ranked candidate sites as tiles (Site Map). Pure functions, tested without Streamlit.

No logic: the order comes from `shell.ranking`, the words from `labels`. This module only
picks the few facts a planner reads first and lays them out as HTML tiles: the top three
large and highlighted, the rest as compact tiles. Every figure keeps its layer (observed,
inferred, recommended), and a missing value shows as a dash, never as 0.
"""

from collections.abc import Iterable, Mapping
from html import escape
from typing import Any

from optev.app import labels as L
from optev.app.data import AppData
from optev.app.shell import OUTCOME_COLOURS

TOP = 3  # the podium: large, highlighted tiles
PAGE = 60  # compact tiles shown per "Show More Sites"


def card(row: Mapping[str, Any], data: AppData) -> dict[str, Any]:
    """The facts on one tile, as display strings."""
    demand = row.get("demand_per_h (inferred)")
    use = row.get("utilisation (observed)")
    outcome = str(row.get("outcome") or "unscreened")
    r, g, b, _ = OUTCOME_COLOURS.get(outcome, OUTCOME_COLOURS["unscreened"])
    return {
        "rank": row["rank"],
        "place": L.site(data, row["site_id"], with_area=False),
        "area": L.area(data, row.get("planning_area")),
        "type": L.KINDS.get(str(row.get("kind")), L.title(str(row.get("kind") or ""))),
        "outcome": L.title(outcome),
        "colour": f"rgb({r},{g},{b})",
        "new": int(row.get("new_points (recommended)") or 0),
        "existing": row.get("existing_points (observed)"),
        "demand": "—" if demand is None else
                  ("≥ " if row.get("lower_bound") else "") + f"{demand:.2f}",
        "utilisation": "—" if use is None else f"{use:.0%}",
        "why": L.rules(row.get("failing_rules")),
    }


def _stat(value: Any, label: str) -> str:
    shown = "—" if value is None else escape(str(value))
    return (f'<div class="ox-rk-stat"><div class="ox-rk-num">{shown}</div>'
            f'<div class="ox-rk-lbl">{escape(label)}</div></div>')


def tile(c: Mapping[str, Any], top: bool = False) -> str:
    """One site as an HTML tile; `top` makes it a large, highlighted podium tile."""
    why = (f'<div class="ox-rk-why">{"To confirm" if c["outcome"] == "Conditional" else "Why"}: '
           f'{escape(c["why"])}</div>' if c["why"] else "")
    return (
        f'<div class="ox-rk{" ox-rk-top" if top else ""}">'
        f'<div class="ox-rk-head"><span class="ox-rk-rank">#{c["rank"]}</span>'
        f'<span class="ox-rk-pill" style="--c:{c["colour"]}">{escape(c["outcome"])}</span></div>'
        f'<div class="ox-rk-place">{escape(c["place"])}</div>'
        f'<div class="ox-rk-meta">{escape(c["area"])} · {escape(c["type"])}</div>'
        f'<div class="ox-rk-stats">'
        f'{_stat(c["new"], "New points (recommended)")}'
        f'{_stat(c["demand"], "Demand / h (inferred)")}'
        f'{_stat(c["existing"], "Existing points (observed)")}'
        f'{_stat(c["utilisation"], "Utilisation (observed)")}'
        f'</div>{why}</div>'
    )


def grid(cards: Iterable[Mapping[str, Any]], top: bool = False) -> str:
    """Tiles laid out in a responsive grid."""
    cls = "ox-rk-grid ox-rk-grid-top" if top else "ox-rk-grid"
    return f'<div class="{cls}">' + "".join(tile(c, top) for c in cards) + "</div>"
