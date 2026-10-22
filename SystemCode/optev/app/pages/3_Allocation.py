"""Allocation (#32): the plan, its estimated cost (against the budget if given), the
independent checker's verdict, and why a request cannot be met when it can't.

No logic here: the plan comes from optev.app.shell.plan (the allocator, #21), the verdict from
optev.reasoning.checker (#22); optev.app.allocation_view only arranges them.
"""

import pandas as pd
import streamlit as st

from optev.app.allocation_view import assumption_rows, infeasible, plan_rows, summary
from optev.app.data import AppData, load
from optev.app.shell import Request, plan
from optev.contracts import Allocation, InfeasibilityReport

st.set_page_config(page_title="OptEV+ · Allocation", page_icon="📍", layout="wide")


@st.cache_data(ttl=300, show_spinner="Loading sites, decisions and demand…")
def _data() -> AppData:
    return load()


data = _data()
st.title("Allocation")
st.caption("How many new charging points go to each site, what they cost, and whether an "
           "independent checker agrees every limit holds. "
           f"Data: **{data.source}**.")

# The request (§1): area, points, optional budget, scenario -------------------------------
with st.sidebar:
    st.header("Request")
    areas = {a.code: a.name.title() for a in data.planning_areas}
    area = st.selectbox("Planning area", [None, *sorted(areas)], key="alloc_area",
                        format_func=lambda c: "Island-wide" if c is None
                        else f"{areas[c]} ({c})")
    points = int(st.number_input("New charging points", min_value=1, value=12, step=1,
                                 key="alloc_points"))
    budget = (float(st.number_input("Budget (SGD)", min_value=0, value=150_000, step=10_000,
                                    key="alloc_budget"))
              if st.checkbox("Cap by budget", key="alloc_use_budget") else None)
    scenario_ids = [s.scenario_id for s in data.scenarios]
    scenario_id = st.selectbox("Scenario", scenario_ids, key="alloc_scenario",
                               index=scenario_ids.index("base") if "base" in scenario_ids else 0)

result, source = plan(data, Request(scenario_id, area, points, budget))
st.caption(f"Plan from: {source}.")

if isinstance(result, InfeasibilityReport):
    why = infeasible(result)
    st.error(f"**This request cannot be met.** {why['requested']} points were asked for; at "
             f"most **{why['max_feasible']}** fit (short by {why['short_by']}).")
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
c1.metric("Points placed", f"{s.placed}" + (f" of {s.requested}" if s.requested else ""))
c2.metric("Sites", s.sites)
c3.metric("Estimated cost (SGD)", f"{s.cost_sgd:,.0f}",
          delta=(f"{s.budget_sgd - s.cost_sgd:,.0f} under budget" if s.budget_sgd is not None
                 else None))
c4.metric("Checker", s.verdict)
st.caption(f"Drivers rescued per hour by this plan: **{s.rescued_per_h}** "
           "(drivers who would otherwise find every charger full). RECOMMENDED: a plan, "
           "not built.")

if s.violations:
    st.error("The checker found broken limits:")
    for v in s.violations:
        st.markdown(f"- `{v}`")
else:
    st.success("The independent checker re-tested every limit (eligibility, area, room per "
               "site, cost, points requested, budget) and found none broken.")

st.subheader("The plan")
st.caption("Most points first. **To confirm first** lists the rules a conditional site must "
           "still satisfy (e.g. electrical capacity, fire safety) before building.")
st.dataframe(pd.DataFrame(plan_rows(data, result)), hide_index=True, width="stretch")

st.subheader("Declared values behind these numbers")
st.caption("DECLARED: values we chose and cite; change one and every plan follows.")
st.dataframe(pd.DataFrame(assumption_rows()), hide_index=True, width="stretch")
