"""Streamlit entrypoint. Deliberately thin — logic lives in the other packages.

Runs with no database configured so that day-one verification works before Neon and
Aura are provisioned. It says so on screen rather than pretending the data is real.
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from optev import __version__

st.set_page_config(page_title="OptEV+", page_icon="⚡", layout="wide")

st.title("OptEV+")
st.caption("Intelligent EV charging infrastructure planner · Group 25")

st.warning(
    "Skeleton. The points below are placeholders, not observed data. "
    "Provision Neon and Aura, run `optev-db migrate`, then wire the ingest package.",
    icon="⚠️",
)

# Placeholder geometry so the map component is proven to render on day one.
placeholder = pd.DataFrame(
    [
        {"name": "Ang Mo Kio", "lat": 1.3691, "lon": 103.8454},
        {"name": "Tampines", "lat": 1.3496, "lon": 103.9568},
        {"name": "Jurong West", "lat": 1.3404, "lon": 103.7090},
    ]
)

st.pydeck_chart(
    pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=10.5),
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                data=placeholder,
                get_position="[lon, lat]",
                get_radius=600,
                get_fill_color=[0, 151, 178, 160],
                pickable=True,
            )
        ],
        tooltip={"text": "{name}"},
    )
)

st.caption(f"optev {__version__}")
