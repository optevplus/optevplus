"""OptEV+ Map (#30): the app shell. Sites coloured by their rules outcome and sized by the
recommended points, inferred demand as H3 hexagons, the ranked sites, and the planner's
controls. Deliberately thin: data comes from optev.app.data, joins from optev.app.shell, and
every decision from the other packages (SYSTEM_DESIGN.md §4.6).
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from optev.app.data import shared
from optev.app.shell import (
    OUTCOME_COLOURS,
    Request,
    demand_hexes,
    funnel,
    plan,
    ranking,
    site_rows,
)
from optev.contracts import Allocation, InfeasibilityReport

st.set_page_config(page_title="OptEV+ · Map", page_icon="⚡", layout="wide")


data = shared()  # one copy for every page and visitor (data.shared)

# Sidebar: the planner's request (§1) -------------------------------------------------------
st.sidebar.header("Request")
areas = {a.code: a.name.title() for a in data.planning_areas}
area = st.sidebar.selectbox("Planning area", [None, *sorted(areas)],
                            format_func=lambda c: "Island-wide" if c is None
                            else f"{areas[c]} ({c})")
points = st.sidebar.number_input("New charging points", min_value=0, value=12, step=1)
use_budget = st.sidebar.checkbox("Cap by budget (SGD)")
budget = st.sidebar.number_input("Budget", min_value=0.0, value=150_000.0, step=10_000.0,
                                 disabled=not use_budget)
scenario_ids = [s.scenario_id for s in data.scenarios]
scenario = st.sidebar.selectbox("Scenario", scenario_ids,
                                index=scenario_ids.index("base") if "base" in scenario_ids else 0)
request = Request(scenario, area, int(points) or None, float(budget) if use_budget else None)

# Header -------------------------------------------------------------------------------------
st.title("OptEV+ · Where should the next charging points go?")
if data.source == "sample":
    st.info("Showing the **synthetic sample** (Tampines and Pasir Ris, ids `SYN-…`). Set "
            "`DATABASE_URL` to show the real data.", icon="🧪")
else:
    st.caption("Data: Postgres (observed week 7–14 Oct 2026, static loads, pipeline outputs).")

allocation, origin = plan(data, request)
rows = site_rows(data, allocation if isinstance(allocation, Allocation) else None, area)
counts = funnel(data, {r["site_id"] for r in rows})

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Candidate sites", len(rows))
c2.metric("Accept", counts["accept"])
c3.metric("Conditional", counts["conditional"])
c4.metric("Defer", counts["defer"])
c5.metric("Reject", counts["reject"])

if isinstance(allocation, InfeasibilityReport):
    st.error(f"**Request can't be met.** At most {allocation.max_feasible} points fit. "
             f"Binding: {', '.join(allocation.binding_constraints) or '—'}.")
elif allocation is None:
    st.warning(origin)
else:
    cost = allocation.total_cost
    st.success(f"**{allocation.total_connectors} new points** across "
               f"{len(allocation.items)} sites · estimated cost S${cost:,.0f} "
               f"(RECOMMENDED, {origin}"
               + (", checked" if allocation.checked else ", not yet checked") + ")")

# Map ------------------------------------------------------------------------------------------
hexes = demand_hexes(rows)
centre = (sum(r["lat"] for r in rows) / len(rows), sum(r["lon"] for r in rows) / len(rows)) \
    if rows else (1.3521, 103.8198)
st.pydeck_chart(pdk.Deck(
    map_style=None,
    initial_view_state=pdk.ViewState(latitude=centre[0], longitude=centre[1],
                                     zoom=12.5 if area else 10.8),
    layers=[
        pdk.Layer("H3HexagonLayer", data=hexes, get_hexagon="hex", get_fill_color="shade",
                  extruded=False, pickable=True, opacity=0.5),
        pdk.Layer("ScatterplotLayer", data=rows, get_position="[lon, lat]",
                  get_radius="radius", get_fill_color="colour", pickable=True,
                  stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1),
    ],
    tooltip={"html": "<b>{site_id}</b> · {kind}<br/>Outcome: {outcome} {failing_rules}<br/>"
                     "New points (recommended): {new_points (recommended)}<br/>"
                     "Existing points (observed): {existing_points (observed)}<br/>"
                     "Demand /h (inferred): {demand_per_h (inferred)}"},
))
st.caption("Dot colour = rules outcome: " + " · ".join(
    f"<span style='color:rgb({c[0]},{c[1]},{c[2]})'>●</span> {name}"
    for name, c in OUTCOME_COLOURS.items() if name != "unscreened")
    + ". Dot size = recommended new points. Blue hexagons = inferred demand (arrivals per hour).",
    unsafe_allow_html=True)

# Ranking ------------------------------------------------------------------------------------
st.subheader("Ranked candidate sites")
st.caption("Eligible sites (accept, conditional) first, then by recommended points and inferred "
           "demand. Rejected and deferred sites stay listed with the rules they failed.")
table = pd.DataFrame(ranking(rows)).drop(columns=["lat", "lon", "colour", "radius"])
st.dataframe(table, hide_index=True, width="stretch")

# Selection: planned capacity (#29), never written into observed tables ----------------------
st.subheader("Select a site")
st.caption("A selection is recorded as PLANNED capacity for this scenario only. Observed data "
           "never changes, so it can be undone.")
eligible_ids = [r["site_id"] for r in rows if r["outcome"] in ("accept", "conditional")]
pick = st.selectbox("Site", eligible_ids)
n = st.number_input("Points to plan there", min_value=1, value=2, step=1)
left, right = st.columns(2)
if data.source != "postgres":
    st.caption("Selections need the database (set `DATABASE_URL`); the sample is read-only.")
elif left.button("Select site", type="primary", disabled=pick is None):
    from optev.scenario.planned import select_site

    select_site(scenario, pick, int(n), selected_by="app")
    shared.clear()
    st.rerun()
elif right.button("Clear selection", disabled=pick is None):
    from optev.scenario.planned import clear_selection

    clear_selection(scenario, pick)
    shared.clear()
    st.rerun()

picked = next((s.planned for s in data.scenarios if s.scenario_id == scenario), [])
if picked:
    st.dataframe(pd.DataFrame([p.model_dump(mode="json") for p in picked]), hide_index=True)
