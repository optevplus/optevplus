"""Rules (#31): each site's decision and every rule result with its source class.

No logic here: decisions come from the rules engine through optev.app.data, and
optev.app.rules_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app import labels as L
from optev.app.rules_view import (
    decision_table,
    register_rows,
    rule_results,
    waivers,
)
from optev.app.shell import funnel
from optev.app.ui import app_data, page_header, section
from optev.contracts import Outcome

data = app_data()
page_header("Eligibility", "Rules", "Every candidate site is screened by six cited rules. A rule "
            "that fails gives its outcome; a rule that can't be judged for missing data defers "
            "the site, never rejects it.", kicker="Decide")
if data.source == "sample":
    st.info("Showing a **demo dataset** of Tampines and Pasir Ris.")

# The register -------------------------------------------------------------------------------
with st.expander(f"The Rule Register ({len(data.rules)} Rules)", expanded=False):
    st.caption("RULE layer: each rule cites the dataset, policy or declared assumption behind it.")
    st.dataframe(pd.DataFrame(L.table(register_rows(data), data)), hide_index=True,
                 width="stretch", column_config={"Link": st.column_config.LinkColumn("Link")})

# The funnel ---------------------------------------------------------------------------------
counts = funnel(data)
cols = st.columns(4)
for col, o in zip(cols, (Outcome.ACCEPT, Outcome.CONDITIONAL, Outcome.DEFER, Outcome.REJECT),
                  strict=True):
    col.metric(o.value.title(), f"{counts[o.value]:,}")

# All decisions ------------------------------------------------------------------------------
left, right = st.columns(2)
choice = left.selectbox("Outcome", [None, *(o.value for o in Outcome)],
                        format_func=lambda o: "All Outcomes" if o is None else o.title())
areas = sorted({s.planning_area for s in data.sites if s.planning_area})
area = right.selectbox("Planning Area", [None, *areas],
                       format_func=lambda a: "Island-Wide" if a is None else L.area(data, a))
table = decision_table(data, choice, area)
st.dataframe(pd.DataFrame(L.table(table, data)), hide_index=True, width="stretch")

# One site -----------------------------------------------------------------------------------
section("Why This Outcome?")
ids = [r["site_id"] for r in table]
# open on a car park, not the community clubs that sort first and mostly lack lot counts
first_car_park = next(
    (i for i, r in enumerate(table) if str(r.get("kind")).endswith("car_park")), 0)
site_id = st.selectbox("Site", ids, index=first_car_park if ids else None,
                       format_func=lambda i: L.site(data, i))
decision = next((d for d in data.decisions if d.site_id == site_id), None)
if decision is None:
    st.stop()
st.markdown(f"**{L.site(data, site_id)}** → **{decision.outcome.value.title()}**")
st.dataframe(pd.DataFrame(L.table(rule_results(data, decision), data)), hide_index=True,
             width="stretch", column_config={"Link": st.column_config.LinkColumn("Link")})
alternatives = waivers(data, decision)
if alternatives:
    st.caption("If one failed rule were waived: " + "; ".join(
        f"waive {L.rule(rule)} → {result.value}" for rule, result in alternatives.items()))
elif decision.unevaluated_rules:
    st.caption("Deferred for missing data: " + L.rules(decision.unevaluated_rules)
               + ". Filling the data, not a waiver, would settle it.")
