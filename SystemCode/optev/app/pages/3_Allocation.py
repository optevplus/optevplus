"""Allocation (#32): the plan, its estimated cost (against the budget if given), the
independent checker's verdict, and why a request cannot be met when it can't.

No logic here: the plan comes from optev.app.shell.plan (the allocator, #21), the verdict from
optev.reasoning.checker (#22); optev.app.allocation_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app import labels as L
from optev.app.allocation_view import assumption_rows, infeasible, plan_rows, summary
from optev.app.data import AppData, load
from optev.app.shell import plan
from optev.app.ui import page_header, request_controls, section, source_note
from optev.contracts import Allocation, InfeasibilityReport


@st.cache_data(ttl=300, show_spinner="Loading sites, decisions and demand…")
def _data() -> AppData:
    return load()


data = _data()
page_header("Allocation", "Plan", "How many new charging points go to each site, what they "
            "cost, and whether an independent checker agrees every limit holds.",
            kicker="Optimise")
source_note(data)

# The request (§1), shared with the Site Map page -----------------------------------------
request = request_controls(data)
scenario_id = request.scenario_id

result, source = plan(data, request)
st.caption(f"Solved by {source}.")

if isinstance(result, InfeasibilityReport):
    why = infeasible(result)
    st.error(f"**This request cannot be met.** {why['requested']:,} points were asked for; at "
             f"most **{why['max_feasible']:,}** fit (short by {why['short_by']:,}).")
    for reason in why["reasons"]:
        st.markdown(f"- {reason}")
    if why["areas"]:
        st.markdown("Affected areas: " + ", ".join(why["areas"]))
    st.stop()
if not isinstance(result, Allocation):
    st.info(source)
    st.stop()

# Independent check (#22): whatever proposed the plan must not be what approves it -------
try:
    from optev.reasoning.checker import check

    result = check(result, data.decisions, data.sites)
except ImportError:
    st.warning("The checker (#22) is not installed: this plan has not been re-tested.")

s = summary(result)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Points Placed", f"{s.placed}" + (f" of {s.requested}" if s.requested else ""))
c2.metric("Sites", s.sites)
c3.metric("Estimated Cost (SGD)", f"{s.cost_sgd:,.0f}",
          delta=(f"{s.budget_sgd - s.cost_sgd:,.0f} under budget" if s.budget_sgd is not None
                 else None))
c4.metric("Checker", s.verdict)
st.caption(f"Drivers rescued per hour by this plan: **{s.rescued_per_h}**, drivers who would "
           "otherwise find every charger full. RECOMMENDED: a plan, not yet built.")

if s.violations:
    st.error("The checker found broken limits:")
    for v in s.violations:
        st.markdown(f"- `{v}`")
else:
    st.success("The independent checker re-tested every limit (eligibility, area, room per "
               "site, cost, points requested, budget) and found none broken.")

section("The Plan")
st.caption("Most points first. **To confirm first** lists the rules a conditional site must "
           "still satisfy (e.g. electrical capacity, fire safety) before building.")
scenario = next(x for x in data.scenarios if x.scenario_id == scenario_id)
st.dataframe(pd.DataFrame(L.table(plan_rows(data, result, scenario), data)), hide_index=True,
             width="stretch")

section("Declared Values Behind These Numbers")
st.caption("DECLARED: values we chose and cite; change one and every plan follows.")
st.dataframe(pd.DataFrame(L.table(assumption_rows(), data)), hide_index=True, width="stretch")
