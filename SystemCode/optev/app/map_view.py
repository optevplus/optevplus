"""The Site Map's map, one question at a time (Site Map). Pure functions, tested without
Streamlit.

The map used to answer three questions with the same dots (colour = outcome, size = new
points, hexagons = demand), explained only by a caption. Now the planner picks one view:

- **Recommended plan** (default): each recommended site is a numbered badge ("+5"), so the
  number of new points is read, not guessed from a dot's size; every other site is a faint dot.
- **Eligibility**: every site as a same-size dot coloured by its rules outcome.
- **Demand**: inferred arrivals per hour, summed per hexagon, on a light-to-dark scale.

Each view comes with its own legend. No logic: rows come from `shell.site_rows`, hexagons from
`shell.demand_hexes`, colours from `shell.OUTCOME_COLOURS`.
"""

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

import pydeck as pdk

from optev.app.shell import OUTCOME_COLOURS

PLAN, ELIGIBILITY, DEMAND = "Recommended Plan", "Eligibility", "Demand"
VIEWS = (PLAN, ELIGIBILITY, DEMAND)

TEAL = [0, 151, 178, 235]
FAINT = [150, 160, 170, 150]
OUTCOMES = ("accept", "conditional", "defer", "reject")
LOW, HIGH = (200, 225, 245), (0, 70, 160)  # the demand scale, light to dark blue

TOOLTIP_SITE = ("<b>{place}</b><br/>{type} · {verdict} {why}<br/>"
                "New points (recommended): {new_points (recommended)}<br/>"
                "Existing points (observed): {existing_points (observed)}<br/>"
                "Demand per hour (inferred): {demand_per_h (inferred)}")
TOOLTIP_HEX = ("<b>{demand_per_h} arrivals per hour</b> (inferred)<br/>"
               "summed over {sites} site(s) in this cell")


def view_state(rows: Sequence[Mapping[str, Any]]) -> pdk.ViewState:
    """Fit the map to the sites shown: the whole island island-wide, one area when picked."""
    if not rows:
        return pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=10.8)
    view = pdk.data_utils.compute_view([[r["lon"], r["lat"]] for r in rows],
                                       view_proportion=0.95)
    view.zoom = min(view.zoom, 15)  # one site alone would zoom to the street
    return view


def recommended(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The sites the plan gives new points, each with its badge label, most points last so the
    biggest badges draw on top."""
    out = [{**r, "label": f"+{r['new_points (recommended)']}"}
           for r in rows if (r.get("new_points (recommended)") or 0) > 0]
    return sorted(out, key=lambda r: (r["new_points (recommended)"], r["site_id"]))


def shade(value: float, peak: float) -> list[int]:
    """A colour on the light-to-dark demand scale."""
    t = 0.0 if peak <= 0 else min(1.0, max(0.0, value / peak))
    rgb = [round(lo + (hi - lo) * t) for lo, hi in zip(LOW, HIGH, strict=True)]
    return [*rgb, 200]


def _dots(data: Sequence[Mapping[str, Any]], colour: Any, pixels: int) -> pdk.Layer:
    """Same-size dots at any zoom: a 1 m radius held between min and max pixels. (pydeck reads
    a string option as an expression, so `radius_units="pixels"` would not do this.)"""
    return pdk.Layer("ScatterplotLayer", data=list(data), get_position="[lon, lat]",
                     get_fill_color=colour, get_radius=1, radius_min_pixels=pixels,
                     radius_max_pixels=pixels, pickable=True, stroked=False)


def layers(view: str, rows: Sequence[Mapping[str, Any]],
           hexes: Sequence[Mapping[str, Any]]) -> tuple[list[pdk.Layer], str]:
    """The map layers and tooltip for one view."""
    if view == ELIGIBILITY:
        coloured = [{**r, "fill": OUTCOME_COLOURS.get(r["outcome"], OUTCOME_COLOURS["unscreened"])}
                    for r in rows]
        return [_dots(coloured, "fill", 5)], TOOLTIP_SITE
    if view == DEMAND:
        peak = max((h["demand_per_h"] for h in hexes), default=0.0)
        cells = [{**h, "fill": shade(h["demand_per_h"], peak)} for h in hexes]
        return [pdk.Layer("H3HexagonLayer", data=cells, get_hexagon="hex",
                          get_fill_color="fill", extruded=False, pickable=True,
                          stroked=True, get_line_color=[255, 255, 255, 60],
                          line_width_min_pixels=1)], TOOLTIP_HEX
    picks = recommended(rows)
    return [
        _dots(rows, FAINT, 3),
        pdk.Layer("ScatterplotLayer", data=picks, get_position="[lon, lat]",
                  get_fill_color=TEAL, get_radius=1, radius_min_pixels=15,
                  radius_max_pixels=15, pickable=True, stroked=True,
                  get_line_color=[255, 255, 255, 255], line_width_min_pixels=2),
        pdk.Layer("TextLayer", data=picks, get_position="[lon, lat]", get_text="label",
                  get_size=13, get_color=[255, 255, 255, 255], font_weight=800,
                  get_text_anchor="'middle'", get_alignment_baseline="'center'"),
    ], TOOLTIP_SITE


def legend(view: str, rows: Sequence[Mapping[str, Any]], hexes: Sequence[Mapping[str, Any]],
           counts: Mapping[str, int]) -> str:
    """One line under the view switch that says what the marks mean."""
    if view == ELIGIBILITY:
        items = "".join(
            f'<span class="ox-key"><i style="background:rgb({c[0]},{c[1]},{c[2]})"></i>'
            f'{escape(o.title())} <b>{counts.get(o, 0):,}</b></span>'
            for o in OUTCOMES for c in [OUTCOME_COLOURS[o]])
        note = "Every site, coloured by the rules' outcome. Hover a dot for the reason."
    elif view == DEMAND:
        peak = max((h["demand_per_h"] for h in hexes), default=0.0)
        lo, hi = (f"rgb({','.join(map(str, LOW))})", f"rgb({','.join(map(str, HIGH))})")
        items = (f'<span class="ox-key">Low <span class="ox-ramp" style="background:'
                 f'linear-gradient(90deg,{lo},{hi})"></span> High '
                 f'<b>{peak:,.1f}</b> arrivals / h</span>')
        note = ("Inferred charging demand, summed per hexagon (about 0.7 km²). "
                "Darker means more drivers arriving per hour.")
    else:
        picks = recommended(rows)
        total = sum(r["new_points (recommended)"] for r in picks)
        items = (f'<span class="ox-key"><span class="ox-badge-mark">+n</span>'
                 f'<b>{len(picks):,}</b> sites get <b>{total:,}</b> new points</span>'
                 f'<span class="ox-key"><i style="background:rgb(150,160,170)"></i>'
                 f'Other candidate sites</span>')
        note = "The number in each badge is the new charging points recommended there."
    return f'<div class="ox-legend">{items}<span class="ox-legend-note">{note}</span></div>'
