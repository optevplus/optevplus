"""Site Map (#30). Sites coloured by their rules outcome and sized by the
recommended points, inferred demand as H3 hexagons, the ranked sites, and the planner's
controls. Deliberately thin: data comes from optev.app.data, joins from optev.app.shell, and
every decision from the other packages (SYSTEM_DESIGN.md §4.6).
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from optev.app import labels as L
from optev.app import map_view as MV
from optev.app import ranking_view as RV
from optev.app.shell import (
    demand_hexes,
    funnel,
    plan,
    ranking,
    site_rows,
)
from optev.app.ui import (
    app_data,
    clear_data,
    is_dark,
    page_header,
    read_only,
    request_controls,
    section,
    source_note,
)
from optev.contracts import Allocation, InfeasibilityReport

data = app_data()

# The planner's request (§1), shared with the Allocation page ---------------------------------
request = request_controls(data)
area, scenario = request.planning_area, request.scenario_id

page_header("Site", "Map", "Where the new charging points go. Switch the map between the "
            "recommended plan, each site's eligibility and inferred demand. Change the request "
            "on the left and the plan re-solves.", kicker="Plan")
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

# Map: one question at a time (optev.app.map_view) -----------------------------------------
hexes = demand_hexes(rows)
for r in rows:  # what the tooltip shows: words, not ids
    r["place"] = L.site(data, r["site_id"])
    r["type"] = L.KINDS.get(r["kind"], r["kind"])
    r["verdict"] = (r["outcome"] or "unscreened").title()
    r["why"] = f"({L.rules(r['failing_rules'])})" if r["failing_rules"] else ""
view = st.segmented_control("Show on the Map", MV.VIEWS, default=MV.PLAN,
                            key="map_view") or MV.PLAN
st.markdown(MV.legend(view, rows, hexes, counts), unsafe_allow_html=True)
map_layers, tooltip = MV.layers(view, rows, hexes)
st.pydeck_chart(pdk.Deck(
    map_style="dark" if is_dark() else "light",
    initial_view_state=MV.view_state(rows),
    layers=map_layers,
    tooltip={"html": tooltip},
))

# Ranking ------------------------------------------------------------------------------------
section("Ranked Candidate Sites")
st.caption("Eligible sites (accept, conditional) first, then by recommended points and inferred "
           "demand. Rejected and deferred sites stay listed with the rules they failed.")
ranked = ranking(rows)
cards = [RV.card(r, data) for r in ranked]
st.markdown(RV.rows(cards[:RV.TOP], top=True, head=True), unsafe_allow_html=True)
rest = cards[RV.TOP:]
if rest:
    # A page of rows at a time: the real data has thousands of sites.
    shown = st.session_state.setdefault("rank_shown", RV.PAGE)
    # Scroll inside a fixed box only when there are enough rows to need it.
    with st.container(height=560 if min(shown, len(rest)) > 10 else "content", border=False):
        st.markdown(RV.rows(rest[:shown]), unsafe_allow_html=True)
    left_n, right_n = st.columns([3, 1])
    left_n.caption(f"Showing ranks 1–{RV.TOP + min(shown, len(rest))} of {len(cards)}. Hover "
                   "a site for the rules behind its outcome; scroll for more.")
    if shown < len(rest) and right_n.button("Show More Sites", width="stretch"):
        st.session_state["rank_shown"] = shown + RV.PAGE
        st.rerun()
with st.expander("View as a Table"):
    st.dataframe(pd.DataFrame(L.table(ranked, data)), hide_index=True, width="stretch")

# Selection: planned capacity (#29), never written into observed tables ----------------------
section("Plan a Site Yourself")
st.caption("A selection is recorded as PLANNED capacity for this scenario only. Observed data "
           "never changes, so it can be undone.")
eligible_ids = [r["site_id"] for r in rows if r["outcome"] in ("accept", "conditional")]
pick = st.selectbox("Site", eligible_ids, format_func=lambda i: L.site(data, i))
n = st.number_input("Points to Plan There", min_value=1, value=2, step=1)
if read_only():
    st.info("This public demo is read-only: selections are switched off so the shared data stays "
            "as published. Run OptEV+ with your own database to record planned capacity.")
elif data.source != "postgres":
    st.caption("Selections need the database (set `DATABASE_URL`); the sample is read-only.")
else:
    with st.container(horizontal=True, gap="small"):  # the two buttons side by side, no gap
        selected = st.button("Select Site", type="primary", disabled=pick is None)
        cleared = st.button("Clear Selection", disabled=pick is None)
    if selected:
        from optev.scenario.planned import select_site

        select_site(scenario, pick, int(n), selected_by="app")
        clear_data()
        st.rerun()
    elif cleared:
        from optev.scenario.planned import clear_selection

        clear_selection(scenario, pick)
        clear_data()
        st.rerun()

picked = next((s.planned for s in data.scenarios if s.scenario_id == scenario), [])
if picked:
    st.dataframe(pd.DataFrame(L.table(
        [{"site_id": p.site_id, "points (planned)": p.connectors} for p in picked], data)),
        hide_index=True)
