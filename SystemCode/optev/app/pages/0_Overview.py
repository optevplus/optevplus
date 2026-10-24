"""Overview: what OptEV+ is, for someone who has never seen it, and a way into every page.

Live figures come from optev.app.data; the evaluation figures are the results on the collected
week reported in ProjectReport (design §6), labelled as such.
"""

import streamlit as st

from optev.app.data import AppData, load
from optev.app.shell import funnel
from optev.app.ui import section, source_note


@st.cache_data(ttl=300, show_spinner="Loading sites, decisions and demand…")
def _data() -> AppData:
    return load()


data = _data()
counts = funnel(data, {s.site_id for s in data.sites})
existing = sum(s.existing_connectors for s in data.sites)
areas = len({s.planning_area for s in data.sites if s.planning_area})

st.markdown(
    '<div class="ox-hero">'
    '<div class="ox-kicker">NUS-ISS · Intelligent Reasoning Systems · Group 25</div>'
    '<div class="ox-title">Where Singapore\'s Next<br><span class="ox-grad">Charging Points</span>'
    ' Go</div>'
    '<div class="ox-sub">OptEV+ turns live government feeds into a plan for public EV charging: '
    'which car parks get new charging points, how many each one gets, and the evidence behind '
    'every site it accepts, rejects or defers.</div>'
    '<span class="ox-pill">Knowledge Discovery</span><span class="ox-pill">Decision Automation'
    '</span><span class="ox-pill">Resource Optimisation</span><span class="ox-pill">Knowledge '
    'Graph</span></div>', unsafe_allow_html=True)

left, right, _ = st.columns([1, 1, 2])
left.page_link("pages/1_Map.py", label="Open the Site Map", icon=":material/map:")
right.page_link("pages/5_Evidence.py", label="Ask Why a Site Was Chosen",
                icon=":material/forum:")
source_note(data)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sites Screened", f"{len(data.sites):,}")
c2.metric("Eligible Sites", f"{counts['accept'] + counts['conditional']:,}")
c3.metric("Points Observed", f"{existing:,}")
c4.metric("Planning Areas", f"{areas}")

section("The Problem")
st.caption("Singapore plans 60,000 charging points by 2030 and most HDB towns already have some. "
           "The question now is which sites get the next ones, how many, and why.")
PROBLEMS = [
    ("Occupancy Hides Demand", "A charger that is busy 95% of the time hides the drivers who "
     "arrived, found it full and left."),
    ("No Charger, No Signal", "A car park with no charger reports no charging data, yet it may "
     "be the best place for the next points."),
    ("Busy Isn't Eligible", "A busy site may have no room, need fire-safety checks, or lack "
     "confirmed electrical capacity."),
]
for col, (title, text) in zip(st.columns(3), PROBLEMS, strict=True):
    col.markdown(f'<div class="ox-card"><h4>{title}</h4><p>{text}</p></div>',
                 unsafe_allow_html=True)

section("How It Works")
st.caption("Five stages. Each reads only what the one before it wrote, and observed, simulated "
           "and planned data never mix.")
STAGES = [
    ("Collect", "One week of 5-minute polls of the LTA charger feed and HDB car parks, joined "
     "to 14 government datasets.", "Data Foundation"),
    ("Infer Demand", "Erlang B turns occupancy into arrivals per hour, counting drivers turned "
     "away; a regression covers sites with no charger.", "Knowledge Discovery"),
    ("Project to 2030", "Growth fitted from new car registrations: ×3.26, 3.65 and 3.99 for low, "
     "base and high.", "Scenarios"),
    ("Decide and Allocate", "Six cited rules screen every site; CP-SAT places points where they "
     "rescue the most drivers; a separate checker re-tests the plan.", "Rules · Optimisation"),
    ("Explain", "A knowledge graph links every decision to its evidence; answers cite only "
     "what the graph holds.", "Knowledge Graph"),
]
for i, (col, (title, text, tag)) in enumerate(zip(st.columns(5), STAGES, strict=True), 1):
    col.markdown(f'<div class="ox-card"><span class="ox-num">{i:02d}</span><h4>{title}</h4>'
                 f'<p>{text}</p><span class="ox-tag">{tag}</span></div>', unsafe_allow_html=True)

section("Explore the System")
SCREENS = [
    ("pages/1_Map.py", "Site Map", ":material/map:",
     "Every site on the map, the recommended plan, and your own selections."),
    ("pages/2_Rules.py", "Eligibility", ":material/rule:",
     "Why each site was accepted, made conditional, deferred or rejected."),
    ("pages/3_Allocation.py", "Allocation", ":material/ev_station:",
     "Points per site, cost, drivers rescued and the checker's verdict."),
    ("pages/4_Demand.py", "Demand", ":material/insights:",
     "Hourly demand per site, usage patterns, and where it is a lower bound."),
    ("pages/5_Evidence.py", "Ask Why", ":material/forum:",
     "Ask in plain words; the answer cites the evidence it rests on."),
]
for col, (page, label, icon, text) in zip(st.columns(5), SCREENS, strict=True):
    with col.container(border=True):
        st.page_link(page, label=label, icon=icon)
        st.caption(text)

section("Results on the Collected Week")
st.caption("Measured on the real data, 7–14 Oct 2026, against targets fixed before the results "
           "were seen.")
RESULTS = [
    ("1.12×", "drivers rescued per hour against the best of five baselines, at 100 points"),
    ("0", "constraint violations in any plan, re-tested by an independent checker"),
    ("95%", "of 20 planner questions answered correctly, with 0 unsupported claims"),
    ("κ 1.00", "agreement between two independent raters and the rules on 30 sites"),
]
for col, (value, label) in zip(st.columns(4), RESULTS, strict=True):
    col.markdown(f'<div class="ox-card"><div class="ox-stat ox-grad">{value}</div>'
                 f'<div class="ox-stat-label">{label}</div></div>', unsafe_allow_html=True)

st.markdown(
    '<div class="ox-foot">Team OptEV, Group 25: Ghanashyam Ramia Kasthurirangan Pandurengan '
    '(lead) · Gurneet Kaur Bhuller · Shrey Yadav · Sushant Maramkulam Shiji. Data: LTA DataMall, '
    'data.gov.sg, URA Master Plan 2025, NEA, People\'s Association, SingStat. Recommended sites '
    'are planning candidates; electrical capacity and land access need separate checks.</div>',
    unsafe_allow_html=True)
