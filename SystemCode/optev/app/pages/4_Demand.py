"""Demand (#33): what was measured at each site, its usage pattern, and the demand inferred.

No logic here: indicators, estimates and patterns come from the analysis package through
optev.app.data, and optev.app.demand_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app.data import shared
from optev.app.demand_view import demand_table, figure, pattern_rows, profile, supply_counts
from optev.assumptions import RELIABLE_UP_TO

NO_PROFILE = {
    "no_supply": "no chargers were observed here, so demand is inferred for the day as a whole.",
    "unobserved": "too few snapshots were seen here to measure it; the rules defer this site.",
    None: "this site has not been measured yet.",
}

st.set_page_config(page_title="OptEV+ · Demand", page_icon="📈", layout="wide")


data = shared()  # one copy for every page and visitor (data.shared)
st.title("Demand at each site")
st.caption("OBSERVED: what the charger feed showed over the collected week. INFERRED: arrivals "
           "per hour from the queueing model (sites with chargers) or the regression (sites "
           f"without). Where occupancy reached {RELIABLE_UP_TO.value:.0%} or more, drivers were "
           "turned away unseen, so the figure is a lower bound and reads **at least**.")
if data.source == "sample":
    st.info("Showing the **synthetic sample** (ids `SYN-…`). Its daily figures are the sample's "
            "stand-in estimates; the hourly profiles are inferred from its two weekdays of "
            "readings.", icon="🧪")

# Supply states (observed) -------------------------------------------------------------------
counts = supply_counts(data)
cols = st.columns(4)
for col, (state, n) in zip(cols, counts.items(), strict=True):
    col.metric(state.replace("_", " ").capitalize(), n)
st.caption("Utilisation is left blank, never 0, where there is no supply or too little "
           "observation: zero would read as nobody wanting to charge there.")

# Every site ---------------------------------------------------------------------------------
areas = sorted({s.planning_area for s in data.sites if s.planning_area})
area = st.selectbox("Planning area", [None, *areas],
                    format_func=lambda a: "Island-wide" if a is None else a)
table = demand_table(data, area)
st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch",
             column_config={
                 "utilisation (observed)": st.column_config.NumberColumn(format="%.2f"),
                 "saturated_share (observed)": st.column_config.NumberColumn(format="%.2f"),
                 "coverage (observed)": st.column_config.NumberColumn(format="%.2f"),
             })

# Usage patterns (inferred) ------------------------------------------------------------------
st.subheader("Usage patterns")
st.caption("INFERRED: k-means on each served site's 48-hour occupancy profile (weekday and "
           "weekend hours), labelled by when the cluster peaks. Sites without chargers have "
           "no profile and no pattern.")
patterns = pattern_rows(data)
if patterns:
    st.dataframe(pd.DataFrame(patterns), hide_index=True, width="stretch")
else:
    st.warning("No patterns found yet.")

# One site's day -----------------------------------------------------------------------------
st.subheader("One site through the day")
site_id = st.selectbox("Site", [r["site_id"] for r in table])
row = next((r for r in table if r["site_id"] == site_id), None)
if row is None:
    st.stop()
estimate = next((e for e in data.estimates if e.site_id == site_id), None)
left, right = st.columns(2)
left.metric("Demand per hour, daily average (inferred)", figure(estimate) or "—")
right.metric("Utilisation (observed)", "—" if row["utilisation (observed)"] is None
             else f"{row['utilisation (observed)']:.0%}")
if estimate and estimate.note:
    st.caption(f"Method: {estimate.note}")

hours = profile(data, site_id)
if not hours:
    st.caption("No hourly profile: " + NO_PROFILE.get(row["supply_state (observed)"],
                                                      "no hourly estimates are stored for it."))
    st.stop()
frame = pd.DataFrame(hours)
st.line_chart(frame, x="hour", y="arrivals_per_h (inferred)", color="day")
bounded = [h for h in hours if h["lower_bound"]]
if bounded:
    st.warning(f"Occupancy was {RELIABLE_UP_TO.value:.0%} or more in "
               + ", ".join(h["time_bin"] for h in bounded)
               + ": demand in those hours is **at least** the figure shown.")
st.dataframe(frame.drop(columns=["lower_bound"]), hide_index=True, width="stretch")
