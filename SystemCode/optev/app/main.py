"""OptEV+ app entry point: the brand, the theme and the top navigation (SYSTEM_DESIGN.md §4.6).

    uv run streamlit run optev/app/main.py

Each page lives in views/ and only arranges what optev.app.data and the other packages give it.
"""

from pathlib import Path

import streamlit as st

from optev.app.auth import require_login
from optev.app.ui import apply_theme, is_dark, theme_toggle

# Not "pages/": Streamlit auto-registers a folder of that name at startup, and its registry
# answered the first deep link after a cold start (e.g. /ask-why) with "Page not found".
PAGES = Path(__file__).with_name("views")

st.set_page_config(page_title="OptEV+", page_icon=":material/ev_station:", layout="wide",
                   initial_sidebar_state="expanded")
apply_theme()
st.logo(str(Path(__file__).with_name("logo-dark.svg" if is_dark() else "logo.svg")), size="large")
theme_toggle()
require_login()  # before navigation, so no page (or deep link) renders signed out

nav = st.navigation([
    st.Page(PAGES / "0_Overview.py", title="Overview", icon=":material/home:", default=True),
    st.Page(PAGES / "1_Map.py", title="Site Map", icon=":material/map:", url_path="site-map"),
    st.Page(PAGES / "2_Rules.py", title="Eligibility", icon=":material/rule:",
            url_path="eligibility"),
    st.Page(PAGES / "3_Allocation.py", title="Allocation", icon=":material/ev_station:",
            url_path="allocation"),
    st.Page(PAGES / "4_Demand.py", title="Demand", icon=":material/insights:", url_path="demand"),
    st.Page(PAGES / "5_Evidence.py", title="Ask Why", icon=":material/forum:", url_path="ask-why"),
], position="top")
nav.run()
