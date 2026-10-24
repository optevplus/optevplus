"""Site Map (#30). Sites coloured by their rules outcome and sized by the
recommended points, inferred demand as H3 hexagons, the ranked sites, and the planner's
controls. Deliberately thin: data comes from optev.app.data, joins from optev.app.shell, and
every decision from the other packages (SYSTEM_DESIGN.md §4.6).
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from optev.app import labels as L
from optev.app.data import AppData, load
from optev.app.shell import (
    OUTCOME_COLOURS,
    demand_hexes,
    funnel,
    plan,
    ranking,
    site_rows,
)
from optev.app.ui import is_dark, page_header, request_controls, section, source_note
from optev.contracts import Allocation, InfeasibilityReport


@st.cache_data(ttl=300, show_spinner="Loading sites, decisions and demand…")
def _data() -> AppData:
    return load()


data = _data()

# The planner's request (§1), shared with the Allocation page ---------------------------------
request = request_controls(data)
area, scenario = request.planning_area, request.scenario_id

page_header("Site", "Map", "Every candidate site, coloured by its eligibility and sized by the "
            "new points the optimiser recommends. Change the request on the left and the plan "
            "re-solves.", kicker="Plan")
source_note(data)

allocation, origin = plan(data, request)
rows = site_rows(data, allocation if isinstance(allocation, Allocation) else None, area)
counts = funnel(data, {r["site_id"] for r in rows})

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Candidate Sites", f"{len(rows):,}")
c2.metric("Accept", f"{counts['accept']:,}")
c3.metric("Conditional", f"{counts['conditional']:,}")
c4.metric("Defer", f"{counts['defer']:,}")
c5.metric("Reject", f"{counts['reject']:,}")

if isinstance(allocation, InfeasibilityReport):
    limit = ", ".join(allocation.binding_constraints) or "room and budget together"
    st.error(f"**This request can't be met.** At most {allocation.max_feasible} points fit; "
             f"the limit is {limit}.")
elif allocation is None:
    st.warning(origin)
else:
    cost = allocation.total_cost
    st.success(f"**Recommended: {allocation.total_connectors} new points across "
               f"{len(allocation.items)} sites**, estimated S${cost:,.0f}. Solved by {origin}; "
               + ("an independent checker found no broken limit." if allocation.checked
                  else "not yet checked."))

# Map ------------------------------------------------------------------------------------------
hexes = demand_hexes(rows)
for r in rows:  # what the tooltip shows: words, not ids
    r["place"] = L.site(data, r["site_id"])
    r["type"] = L.KINDS.get(r["kind"], r["kind"])
    r["verdict"] = (r["outcome"] or "unscreened").title()
    r["why"] = f"({L.rules(r['failing_rules'])})" if r["failing_rules"] else ""
centre = (sum(r["lat"] for r in rows) / len(rows), sum(r["lon"] for r in rows) / len(rows)) \
    if rows else (1.3521, 103.8198)
st.pydeck_chart(pdk.Deck(
    map_style="dark" if is_dark() else "light",
    initial_view_state=pdk.ViewState(latitude=centre[0], longitude=centre[1],
                                     zoom=12.5 if area else 10.8),
    layers=[
        pdk.Layer("H3HexagonLayer", data=hexes, get_hexagon="hex", get_fill_color="shade",
                  extruded=False, pickable=True, opacity=0.5),
        pdk.Layer("ScatterplotLayer", data=rows, get_position="[lon, lat]",
                  get_radius="radius", get_fill_color="colour", pickable=True,
                  stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1),
    ],
    tooltip={"html": "<b>{place}</b><br/>{type} · {verdict} {why}<br/>"
                     "New points (recommended): {new_points (recommended)}<br/>"
                     "Existing points (observed): {existing_points (observed)}<br/>"
                     "Demand per hour (inferred): {demand_per_h (inferred)}"},
))
st.caption("Dot colour shows the eligibility outcome: " + " · ".join(
    f"<span style='color:rgb({c[0]},{c[1]},{c[2]})'>●</span> {name}"
    for name, c in OUTCOME_COLOURS.items() if name != "unscreened")
    + ". Dot size shows the recommended new points. Blue hexagons show inferred demand "
    "(arrivals per hour).",
    unsafe_allow_html=True)

# Ranking ------------------------------------------------------------------------------------
section("Ranked Candidate Sites")
st.caption("Eligible sites (accept, conditional) first, then by recommended points and inferred "
           "demand. Rejected and deferred sites stay listed with the rules they failed.")
st.dataframe(pd.DataFrame(L.table(ranking(rows), data)), hide_index=True, width="stretch")

# Selection: planned capacity (#29), never written into observed tables ----------------------
section("Plan a Site Yourself")
st.caption("A selection is recorded as PLANNED capacity for this scenario only. Observed data "
           "never changes, so it can be undone.")
eligible_ids = [r["site_id"] for r in rows if r["outcome"] in ("accept", "conditional")]
pick = st.selectbox("Site", eligible_ids, format_func=lambda i: L.site(data, i))
n = st.number_input("Points to Plan There", min_value=1, value=2, step=1)
left, right = st.columns(2)
if data.source != "postgres":
    st.caption("Selections need the database (set `DATABASE_URL`); the sample is read-only.")
elif left.button("Select Site", type="primary", disabled=pick is None):
    from optev.scenario.planned import select_site

    select_site(scenario, pick, int(n), selected_by="app")
    st.cache_data.clear()
    st.rerun()
elif right.button("Clear Selection", disabled=pick is None):
    from optev.scenario.planned import clear_selection

    clear_selection(scenario, pick)
    st.cache_data.clear()
    st.rerun()

picked = next((s.planned for s in data.scenarios if s.scenario_id == scenario), [])
if picked:
    st.dataframe(pd.DataFrame(L.table(
        [{"site_id": p.site_id, "points (planned)": p.connectors} for p in picked], data)),
        hide_index=True)
