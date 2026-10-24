"""Overview: what OptEV+ does, for someone who has never seen it, with a way into every page.

Live figures come from optev.app.data; the proof points are the results on the collected week
(ProjectReport, design §6), written for a planner rather than an examiner.
"""

import streamlit as st

from optev.app.data import AppData, load
from optev.app.shell import funnel
from optev.app.ui import section, source_note


@st.cache_data(ttl=300, show_spinner="Loading sites, decisions and demand…")
def _data() -> AppData:
    return load()


def cta(page: str, label: str, icon: str, primary: bool, key: str) -> None:
    with st.container(key=f"cta-{'primary' if primary else 'secondary'}-{key}"):
        st.page_link(page, label=label, icon=icon)


data = _data()
counts = funnel(data, {s.site_id for s in data.sites})
existing = sum(s.existing_connectors for s in data.sites)
areas = len({s.planning_area for s in data.sites if s.planning_area})

# Hero -------------------------------------------------------------------------------------
st.markdown(
    '<div class="ox-hero">'
    '<span class="ox-eyebrow">EV charging planning, powered by public data</span>'
    '<div class="ox-title">Put Every New Charger<br><span class="ox-grad">Where It Counts</span>'
    '</div><div class="ox-sub">OptEV+ reads Singapore\'s live charger and car park feeds, finds '
    'the drivers who are turned away today, and tells planners which sites should get the next '
    'charging points, how many each, and why.</div></div>', unsafe_allow_html=True)
a, b, _ = st.columns([1.45, 1.75, 1.3])
with a:
    cta("pages/1_Map.py", "Plan Charging Points", ":material/arrow_forward:", True, "hero")
with b:
    cta("pages/5_Evidence.py", "Ask Why a Site Was Chosen", ":material/forum:", False, "hero")
source_note(data)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sites Screened", f"{len(data.sites):,}")
c2.metric("Eligible Sites", f"{counts['accept'] + counts['conditional']:,}")
c3.metric("Charging Points Tracked", f"{existing:,}")
c4.metric("Planning Areas", f"{areas}")

# How it works -----------------------------------------------------------------------------
section("Three Steps to a Plan")
st.markdown('<div class="ox-lead">Set a target, get a checked plan, and see the reason behind '
            'every site.</div>', unsafe_allow_html=True)
STEPS = [
    ("1", "Set Your Target", "Choose an area, how many points to add, an optional budget and "
     "a growth scenario for 2030."),
    ("2", "Get a Checked Plan", "OptEV+ places each point where it rescues the most drivers, "
     "then an independent checker re-tests every limit."),
    ("3", "See Why", "Every site comes with its rules, its demand and its sources. Ask in plain "
     "words and get an answer that cites them."),
]
for col, (n, title, text) in zip(st.columns(3), STEPS, strict=True):
    col.markdown(f'<div class="ox-card"><span class="ox-icon">{n}</span><h4>{title}</h4>'
                 f'<p>{text}</p></div>', unsafe_allow_html=True)

# Features ---------------------------------------------------------------------------------
section("Built for the Next Phase of Charging")
st.markdown('<div class="ox-lead">Most towns already have chargers. The hard question now is '
            'where the next ones go.</div>', unsafe_allow_html=True)
FEATURES = [
    ("Demand You Can't See", "A full charger hides the drivers who left. A queueing model "
     "recovers them, hour by hour."),
    ("Sites With No Chargers Yet", "Car park activity, land use and nearby amenities estimate "
     "demand where nothing is measured."),
    ("Rules With Sources", "Six eligibility rules, each citing the LTA, MHA or MOT document "
     "behind it. Missing data defers a site; it never rejects it."),
    ("Optimal Placement", "An exact optimiser spreads points to rescue the most drivers within "
     "room and budget, in seconds for the whole island."),
    ("Plans You Can Trust", "A separate checker re-tests every limit before a plan is shown. "
     "Impossible requests get the largest plan that fits."),
    ("Answers With Evidence", "A knowledge graph links every decision to its data. Answers cite "
     "it, and say so when there is nothing to cite."),
]
for row in (FEATURES[:3], FEATURES[3:]):
    for col, (title, text) in zip(st.columns(3), row, strict=True):
        col.markdown(f'<div class="ox-card"><h4>{title}</h4><p>{text}</p></div>',
                     unsafe_allow_html=True)
    st.write("")

# Proof ------------------------------------------------------------------------------------
section("Proven on Real Data")
st.markdown('<div class="ox-lead">Tested on a full week of Singapore\'s charger feed, '
            '7–14 October 2026.</div>', unsafe_allow_html=True)
PROOF = [
    ("12%", "more drivers served than the best rule of thumb, at 100 new points"),
    ("0", "broken limits in any plan, re-tested independently"),
    ("95%", "of planner questions answered correctly, with nothing made up"),
    ("2 min", "to screen and plan all 2,967 sites end to end"),
]
for col, (value, label) in zip(st.columns(4), PROOF, strict=True):
    col.markdown(f'<div class="ox-card"><div class="ox-stat ox-grad">{value}</div>'
                 f'<div class="ox-stat-label">{label}</div></div>', unsafe_allow_html=True)

section("Built on Open Government Data")
st.markdown("".join(f'<span class="ox-badge">{name}</span>' for name in (
    "LTA DataMall", "data.gov.sg", "HDB Car Park Information", "URA Master Plan 2025",
    "NEA Hawker Centres", "People's Association", "SingStat")), unsafe_allow_html=True)

# Closing call to action -------------------------------------------------------------------
st.markdown('<div class="ox-band"><h3>Ready to Plan the Next 1,000 Points?</h3>'
            '<p>Open the map, set a target, and get a checked plan with the reason for every '
            'site.</p></div>', unsafe_allow_html=True)
st.write("")
a, b, _ = st.columns([1.45, 1.45, 1.6])
with a:
    cta("pages/1_Map.py", "Open the Site Map", ":material/map:", True, "band")
with b:
    cta("pages/3_Allocation.py", "See a Sample Plan", ":material/ev_station:", False, "band")

st.markdown('<div class="ox-foot">OptEV+ · Planning aid for public EV charging in Singapore. '
            'Recommended sites are candidates; electrical capacity and land access are checked '
            'separately before building.</div>', unsafe_allow_html=True)
