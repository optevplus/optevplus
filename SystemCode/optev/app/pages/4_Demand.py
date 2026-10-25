"""Demand (#33): what was measured at each site, its usage pattern, and the demand inferred.

No logic here: indicators, estimates and patterns come from the analysis package through
optev.app.data, and optev.app.demand_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app import labels as L
from optev.app.demand_view import demand_table, figure, pattern_rows, profile, supply_counts
from optev.app.ui import app_data, page_header, section
from optev.assumptions import RELIABLE_UP_TO

NO_PROFILE = {
    "no_supply": "no chargers were observed here, so demand is inferred for the day as a whole.",
    "unobserved": "too few snapshots were seen here to measure it; the rules defer this site.",
    None: "this site has not been measured yet.",
}




data = app_data()
page_header("Demand", "Insights", "How busy every site is, and how many drivers arrive each "
            "hour, including the ones turned away by full chargers.", kicker="Measure")
st.caption("OBSERVED: what the charger feed showed over the collected week. INFERRED: arrivals "
           "per hour from the queueing model (sites with chargers) or the regression (sites "
           f"without). Where occupancy reached {RELIABLE_UP_TO.value:.0%} or more, drivers were "
           "turned away unseen, so the figure is a lower bound and reads **at least**.")
if data.source == "sample":
    st.info("Showing a **demo dataset** of Tampines and Pasir Ris. Its daily figures are the "
            "stand-in estimates; the hourly profiles are inferred from its two weekdays of "
            "readings.")

# Supply states (observed) -------------------------------------------------------------------
counts = supply_counts(data)
cols = st.columns(4)
for col, (state, n) in zip(cols, counts.items(), strict=True):
    col.metric(L.SUPPLY.get(state, L.title(state)), f"{n:,}")
st.caption("Utilisation is left blank, never 0, where there is no supply or too little "
           "observation: zero would read as nobody wanting to charge there.")

# Every site ---------------------------------------------------------------------------------
areas = sorted({s.planning_area for s in data.sites if s.planning_area})
area = st.selectbox("Planning Area", [None, *areas],
                    format_func=lambda a: "Island-Wide" if a is None else L.area(data, a))
table = demand_table(data, area)
share = st.column_config.NumberColumn(format="percent")
st.dataframe(pd.DataFrame(L.table(table, data)), hide_index=True, width="stretch",
             column_config={"Utilisation · Observed": share, "Time Full · Observed": share,
                            "Observation Coverage · Observed": share})

# Usage patterns (inferred) ------------------------------------------------------------------
section("Usage Patterns")
st.caption("INFERRED: k-means on each served site's 48-hour occupancy profile (weekday and "
           "weekend hours), labelled by when the cluster peaks. Sites without chargers have "
           "no profile and no pattern.")
patterns = pattern_rows(data)
if patterns:
    st.dataframe(pd.DataFrame(L.table(patterns, data)), hide_index=True, width="stretch")
else:
    st.warning("No patterns found yet.")

# One site's day -----------------------------------------------------------------------------
section("One Site Through the Day")
measured = [r for r in table if r["utilisation (observed)"] is not None]
busiest = max(measured, key=lambda r: r["utilisation (observed)"])["site_id"] if measured else None
site_ids = [r["site_id"] for r in table]
site_id = st.selectbox("Site", site_ids,  # opens on the busiest measured site
                       index=site_ids.index(busiest) if busiest in site_ids else 0,
                       format_func=lambda i: L.site(data, i))
row = next((r for r in table if r["site_id"] == site_id), None)
if row is None:
    st.stop()
estimate = next((e for e in data.estimates if e.site_id == site_id), None)
left, right = st.columns(2)
left.metric("Demand per Hour, Daily Average (Inferred)", figure(estimate) or "—")
right.metric("Utilisation (Observed)", "—" if row["utilisation (observed)"] is None
             else f"{row['utilisation (observed)']:.0%}")
if estimate and estimate.note:
    st.caption(f"Method: {L.detail(estimate.note)}")

hours = profile(data, site_id)
if not hours:
    st.caption("No hourly profile: " + NO_PROFILE.get(row["supply_state (observed)"],
                                                      "no hourly estimates are stored for it."))
    st.stop()
frame = pd.DataFrame(hours)
chart = frame.rename(columns={"hour": "Hour", "arrivals_per_h (inferred)": "Arrivals per Hour",
                              "day": "Day"}).assign(Day=lambda f: f["Day"].str.title())
st.line_chart(chart, x="Hour", y="Arrivals per Hour", color="Day")
bounded = [h for h in hours if h["lower_bound"]]
if bounded:
    st.warning(f"Occupancy was {RELIABLE_UP_TO.value:.0%} or more in "
               + ", ".join(L.time_bin(h["time_bin"]) for h in bounded)
               + ": demand in those hours is **at least** the figure shown.")
st.dataframe(pd.DataFrame(L.table(hours, data)), hide_index=True, width="stretch")
