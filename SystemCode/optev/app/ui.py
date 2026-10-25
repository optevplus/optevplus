"""Look and feel shared by every page: the proposal deck's palette and type, the page header,
the data-source note and the planner's request controls. Presentation only; no logic.

Casing: navigation, page titles, section headings, metric labels and buttons use Title Case;
body text and captions use sentence case.
"""

import logging
import os
from pathlib import Path
from typing import Any

import streamlit as st

from optev.app.data import AppData, from_postgres, from_sample
from optev.app.shell import Request

log = logging.getLogger(__name__)

TEAL = "#0097B2"
GREEN = "#7ED957"
INK = "#202020"
MUTED = "#4A5560"
SURFACE = "#F4F7F8"
LINE = "#E2E8EB"
GRADIENT = f"linear-gradient(110deg, {TEAL} 0%, {GREEN} 100%)"

CSS = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")


@st.cache_resource(ttl=900, show_spinner="Loading sites, decisions and demand…")
def _bundle(database_url: str) -> AppData:
    # keyed on the database, so the sample and the real data are never mixed up
    return from_postgres(database_url) if database_url else from_sample()


def app_data() -> AppData:
    """The data bundle, loaded once and shared by every page and visitor. A resource cache, not
    st.cache_data: the bundle is read-only, and a copy per page view made first visits take
    18–20 s and ran the 1 GB Community Cloud container out of memory on 24 Oct (Shrey's
    diagnosis in #101). Call clear_data() after a write."""
    from dotenv import load_dotenv

    from optev.app import data

    load_dotenv(data.ENV_FILE)  # as data.load(): never overrides a variable already set
    try:
        return _bundle(os.environ.get("DATABASE_URL") or "")
    except Exception as e:  # the database is down or unreachable: say so, never a traceback
        log.warning("data unavailable: %s: %s", type(e).__name__, e)
        st.error("**The planning data is unavailable right now.** OptEV+ could not reach its "
                 "database. Please try again in a minute; if it persists, the database may be "
                 "paused or the network may block it.")
        st.stop()


def clear_data() -> None:
    _bundle.clear()


def read_only() -> bool:
    """True on a public deployment (OPTEV_READ_ONLY=1 in its secrets): nothing on the page may
    write to the shared database."""
    return os.environ.get("OPTEV_READ_ONLY", "").strip().lower() in ("1", "true", "yes")


# On the dark background the brand's bright green reads best (10.6:1); on white it would not
# (1.8:1), so the stylesheet's default is the darker green and dark mode lifts it.
DARK_CSS = (".ox-grad { background: linear-gradient(110deg, #1FB5CC 0%, #7ED957 100%);"
            " -webkit-background-clip: text; background-clip: text; }")


def apply_theme() -> None:
    st.markdown(f"<style>{CSS}{DARK_CSS if is_dark() else ''}</style>", unsafe_allow_html=True)


def page_header(lead: str, highlight: str, subtitle: str, kicker: str | None = None) -> None:
    """The deck's two-tone title: a dark word and a gradient word, then one line of context."""
    k = f'<div class="ox-kicker">{kicker}</div>' if kicker else ""
    st.markdown(f'{k}<div class="ox-title">{lead} <span class="ox-grad">{highlight}</span></div>'
                f'<div class="ox-sub">{subtitle}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="ox-section">{title}</div>', unsafe_allow_html=True)


def source_note(data: AppData) -> None:
    if data.source == "sample":
        st.info("Showing a **demo dataset** of Tampines and Pasir Ris. Connect the database "
                "(`DATABASE_URL`) to plan with live data.")
    else:
        st.caption("Live data: Singapore's charger and car park feeds, 7–14 Oct 2026.")


def request_controls(data: AppData) -> Request:
    """The planner's request in the sidebar, with the same keys on Site Map and Allocation and
    kept for the whole session, so a choice made on one page is still there on the next."""
    areas = {a.code: a.name.title() for a in data.planning_areas}
    scenario_ids = [s.scenario_id for s in data.scenarios]
    keep: dict[str, Any] = {"persist_state": "session"}
    with st.sidebar:
        st.markdown("### Your Request")
        st.caption("Where, how many, and under which growth scenario.")
        area = st.selectbox("Planning Area", [None, *sorted(areas)], key="req_area",
                            format_func=lambda c: "Island-Wide" if c is None
                            else f"{areas.get(c, c)} ({c})", **keep)
        points = st.number_input("New Charging Points", min_value=0, value=12, step=1,
                                 key="req_points", **keep,
                                 help="0 places as many points as the budget pays for.")
        use_budget = st.checkbox("Cap by Budget", key="req_use_budget", **keep)
        budget = st.number_input("Budget (SGD)", min_value=0, value=150_000, step=10_000,
                                 key="req_budget", disabled=not use_budget, **keep)
        scenario = st.selectbox("Growth Scenario", scenario_ids, key="req_scenario",
                                index=scenario_ids.index("base") if "base" in scenario_ids else 0,
                                format_func=lambda s: s.title(), **keep)
    return Request(scenario, area, int(points) or None, float(budget) if use_budget else None)


PAGE_SLUGS = ("site-map", "eligibility", "allocation", "demand", "ask-why")

# Streamlit keeps the viewer's theme in localStorage["stActiveTheme-<path>-v2"] and has no Python
# API to change it, so the toggle writes that value for every page and reloads. If the browser
# blocks it (e.g. the app is embedded), the ⋮ → Settings menu still switches the theme.
SWITCH_JS = """<script>
(function () {
  try {
    const w = window.parent;
    const slugs = %(slugs)s;
    let base = w.location.pathname;
    for (const s of slugs) { if (base.endsWith("/" + s) || base.endsWith("/" + s + "/")) {
      base = base.slice(0, base.lastIndexOf("/" + s)); } }
    base = base.replace(/\\/+$/, "");
    const paths = [base + "/", base, ...slugs.map(s => base + "/" + s),
                   ...slugs.map(s => base + "/" + s + "/")];
    for (const p of paths) {
      w.localStorage.setItem("stActiveTheme-" + (p || "/") + "-v2", JSON.stringify(%(mode)s));
    }
    w.location.reload();
  } catch (e) { console.warn("theme switch unavailable", e); }
})();
</script>"""


def is_dark() -> bool:
    return getattr(st.context.theme, "type", None) == "dark"


def theme_toggle() -> None:
    """A visible Light/Dark switch at the top right of every page."""
    import json

    import streamlit.components.v1 as components

    dark = is_dark()
    _, right = st.columns([4, 1])
    if right.button("Light Mode" if dark else "Dark Mode", key="theme_toggle",
                    icon=":material/light_mode:" if dark else ":material/dark_mode:",
                    width="stretch"):
        components.html(SWITCH_JS % {"slugs": json.dumps(list(PAGE_SLUGS)),
                                     "mode": json.dumps("Light" if dark else "Dark")}, height=0)


VIS_NETWORK = "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"
GRAPH_HTML = """<div id="net" style="height:%(h)dpx;border-radius:16px;
  background:%(bg)s;border:1px solid rgba(127,127,127,.2)"></div>
<script src="%(lib)s"></script>
<script>
const nodes = new vis.DataSet(%(nodes)s), edges = new vis.DataSet(%(edges)s);
const net = new vis.Network(document.getElementById("net"), {nodes, edges}, {
  nodes: {shape: "dot", borderWidth: 2, font: {color: "%(ink)s", size: 16,
          face: "Inter, Helvetica, Arial", strokeWidth: 3, strokeColor: "%(bg)s"},
          shadow: {enabled: true, color: "rgba(0,151,178,.35)", size: 14, x: 0, y: 0}},
  edges: {arrows: {to: {enabled: true, scaleFactor: .5}}, width: 1.6,
          color: {color: "%(line)s", highlight: "#0097B2"}, smooth: {type: "dynamic"},
          font: {size: 11, color: "%(muted)s", strokeWidth: 0, align: "middle"}},
  physics: {barnesHut: {gravitationalConstant: -4200, springLength: 110, damping: .25,
                        avoidOverlap: .4},
            stabilization: {iterations: 60}},
  interaction: {hover: true, tooltipDelay: 120, zoomView: true}
});
net.once("stabilizationIterationsDone", () => {
  net.fit();  // then keep labels readable on a projector: never zoom out past 0.8
  if (net.getScale() < 0.8) net.moveTo({scale: 0.8, animation: {duration: 700}});
  else net.fit({animation: {duration: 700}});
});
</script>"""


def graph_view(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], height: int = 480
               ) -> None:
    """Draw a small knowledge-graph slice as an animated, draggable network (vis-network)."""
    import json

    import streamlit.components.v1 as components

    dark = is_dark()

    def safe(value: object) -> str:  # names come from data: never let them close the script
        return json.dumps(value).replace("</", "<\\/")

    components.html(GRAPH_HTML % {
        "h": height, "lib": VIS_NETWORK, "nodes": safe(nodes), "edges": safe(edges),
        "bg": "#0F1C21" if dark else "#FAFCFC", "ink": "#E6EEF0" if dark else "#202020",
        "muted": "#8FA3AA" if dark else "#6B7A80", "line": "#3A4E55" if dark else "#C5D0D4",
    }, height=height + 8)
