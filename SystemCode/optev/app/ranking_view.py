"""Ranked candidate sites as a list (Site Map). Pure functions, tested without Streamlit.

No logic: the order comes from `shell.ranking`, the words from `labels`. Each site is one
line: rank, place, outcome and four figures in aligned columns. The top-ranked site is
highlighted above the rest. A row grows under the cursor (or when clicked or tapped) and
expands to the full name, every figure with its label, and the rules to confirm (or that
failed). Every figure keeps its layer (observed, inferred,
recommended) in the column header and in its tooltip, and a missing value shows as a dash,
never as 0.
"""

from collections.abc import Iterable, Mapping
from html import escape
from typing import Any

from optev.app import labels as L
from optev.app.data import AppData
from optev.app.shell import OUTCOME_COLOURS

TOP = 1  # the highlighted top pick
PAGE = 60  # rows shown per "Show More Sites"

# (card key, column header, layer): the figures on every row, in order.
FIGURES = (
    ("new", "New points", "recommended"),
    ("demand", "Demand / h", "inferred"),
    ("existing", "Existing", "observed"),
    ("utilisation", "Utilisation", "observed"),
)


def card(row: Mapping[str, Any], data: AppData) -> dict[str, Any]:
    """The facts on one row, as display strings."""
    demand = row.get("demand_per_h (inferred)")
    use = row.get("utilisation (observed)")
    existing = row.get("existing_points (observed)")
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
        "existing": "—" if existing is None else str(existing),
        "demand": "—" if demand is None else
                  ("≥ " if row.get("lower_bound") else "") + f"{demand:.2f}",
        "utilisation": "—" if use is None else f"{use:.0%}",
        "why": L.rules(row.get("failing_rules")),
    }


def header() -> str:
    """Column headers, each figure with its layer."""
    figs = "".join(f'<span class="ox-rl-num">{escape(h)}<em>{escape(layer)}</em></span>'
                   for _, h, layer in FIGURES)
    return (f'<div class="ox-rl-row ox-rl-head"><span>#</span><span>Site</span>'
            f'<span>Outcome</span>{figs}</div>')


def details(c: Mapping[str, Any]) -> str:
    """What a row shows when it expands (hover, or click / tap): the full name, area, type and
    outcome, every figure with its label and layer, and the rules behind the outcome."""
    facts = " · ".join(f"{escape(h)} <b>{escape(str(c[key]))}</b> <em>({layer})</em>"
                       for key, h, layer in FIGURES)
    label = "To confirm" if c["outcome"] == "Conditional" else "Why"
    why = (f'<div class="ox-rl-why">{label}: {escape(c["why"])}</div>' if c["why"] else "")
    return (f'<div class="ox-rl-more"><div class="ox-rl-full"><b>{escape(c["place"])}</b>'
            f'<span>{escape(c["area"])} · {escape(c["type"])} · {escape(c["outcome"])}</span>'
            f'</div><div class="ox-rl-facts">{facts}</div>{why}</div>')


def row(c: Mapping[str, Any], top: bool = False) -> str:
    """One site as one line; `top` highlights it as the top pick. It expands under the
    cursor, or when clicked or tapped (tabindex makes it focusable, so no script is needed)."""
    figs = "".join(
        f'<span class="ox-rl-num" title="{escape(h)} ({layer})">{escape(str(c[key]))}</span>'
        for key, h, layer in FIGURES)
    pick = '<span class="ox-rl-pick">Top pick</span>' if top else ""
    return (
        f'<div class="ox-rl-item{" ox-rl-top" if top else ""}" tabindex="0">'
        f'<div class="ox-rl-row">'
        f'<span class="ox-rl-rank">{c["rank"]:02d}</span>'
        f'<span class="ox-rl-site"><b>{escape(c["place"])}</b>{pick}'
        f'<span class="ox-rl-meta">{escape(c["area"])} · {escape(c["type"])}</span></span>'
        f'<span class="ox-rl-out"><i style="background:{c["colour"]}"></i>'
        f'{escape(c["outcome"])}</span>{figs}</div>{details(c)}</div>'
    )


def rows(cards: Iterable[Mapping[str, Any]], top: bool = False, head: bool = False) -> str:
    """A list of rows, optionally under the column headers."""
    body = "".join(row(c, top) for c in cards)
    return f'<div class="ox-rl">{header() if head else ""}{body}</div>'
