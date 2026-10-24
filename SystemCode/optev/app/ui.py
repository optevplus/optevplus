"""Look and feel shared by every page: the proposal deck's palette and type, the page header,
the data-source note and the planner's request controls. Presentation only; no logic.

Casing: navigation, page titles, section headings, metric labels and buttons use Title Case;
body text and captions use sentence case.
"""

from pathlib import Path
from typing import Any

import streamlit as st

from optev.app.data import AppData
from optev.app.shell import Request

TEAL = "#0097B2"
GREEN = "#7ED957"
INK = "#202020"
MUTED = "#4A5560"
SURFACE = "#F4F7F8"
LINE = "#E2E8EB"
GRADIENT = f"linear-gradient(110deg, {TEAL} 0%, {GREEN} 100%)"

CSS = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")


def apply_theme() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def page_header(lead: str, highlight: str, subtitle: str, kicker: str | None = None) -> None:
    """The deck's two-tone title: a dark word and a gradient word, then one line of context."""
    k = f'<div class="ox-kicker">{kicker}</div>' if kicker else ""
    st.markdown(f'{k}<div class="ox-title">{lead} <span class="ox-grad">{highlight}</span></div>'
                f'<div class="ox-sub">{subtitle}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="ox-section">{title}</div>', unsafe_allow_html=True)


def source_note(data: AppData) -> None:
    if data.source == "sample":
        st.info("Showing the **synthetic sample** (Tampines and Pasir Ris, ids `SYN-…`). Set "
                "`DATABASE_URL` to show the real data.")
    else:
        st.caption("Data: the collected week, 7–14 Oct 2026, with every pipeline output, "
                   "from PostgreSQL.")


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
