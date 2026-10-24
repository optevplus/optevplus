"""Rules (#31): each site's decision and every rule result with its source class.

No logic here: decisions come from the rules engine through optev.app.data, and
optev.app.rules_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app.data import shared
from optev.app.rules_view import (
    decision_table,
    register_rows,
    rule_results,
    waivers,
)
from optev.app.shell import funnel
from optev.contracts import Outcome

st.set_page_config(page_title="OptEV+ · Rules", page_icon="⚖️", layout="wide")


data = shared()  # one copy for every page and visitor (data.shared)
st.title("Rules and eligibility")
st.caption("Every candidate site is screened by every rule. A rule that fails gives its outcome; "
           "a rule that can't be evaluated for missing data defers the site, never rejects it.")
if data.source == "sample":
    st.info("Showing the **synthetic sample** (ids `SYN-…`).", icon="🧪")

# The register -------------------------------------------------------------------------------
with st.expander(f"The rule register ({len(data.rules)} rules)", expanded=False):
    st.caption("RULE layer: each rule cites the dataset, policy or declared assumption behind it.")
    st.dataframe(pd.DataFrame(register_rows(data)), hide_index=True, width="stretch",
                 column_config={"link": st.column_config.LinkColumn("link")})

# The funnel ---------------------------------------------------------------------------------
counts = funnel(data)
cols = st.columns(4)
for col, o in zip(cols, (Outcome.ACCEPT, Outcome.CONDITIONAL, Outcome.DEFER, Outcome.REJECT),
                  strict=True):
    col.metric(o.value.title(), counts[o.value])

# All decisions ------------------------------------------------------------------------------
left, right = st.columns(2)
choice = left.selectbox("Outcome", [None, *(o.value for o in Outcome)],
                        format_func=lambda o: "All outcomes" if o is None else o)
areas = sorted({s.planning_area for s in data.sites if s.planning_area})
area = right.selectbox("Planning area", [None, *areas],
                       format_func=lambda a: "Island-wide" if a is None else a)
table = decision_table(data, choice, area)
st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

# One site -----------------------------------------------------------------------------------
st.subheader("Why this outcome?")
ids = [r["site_id"] for r in table]
site_id = st.selectbox("Site", ids)
decision = next((d for d in data.decisions if d.site_id == site_id), None)
if decision is None:
    st.stop()
st.markdown(f"**{site_id}** → **{decision.outcome.value.upper()}**")
st.dataframe(pd.DataFrame(rule_results(data, decision)), hide_index=True, width="stretch",
             column_config={"link": st.column_config.LinkColumn("link")})
alternatives = waivers(data, decision)
if alternatives:
    st.caption("If one failed rule were waived: " + "; ".join(
        f"waive {rule} → {result.value}" for rule, result in alternatives.items()))
elif decision.unevaluated_rules:
    st.caption("Deferred for missing data: " + ", ".join(decision.unevaluated_rules)
               + ". Filling the data, not a waiver, would settle it.")
