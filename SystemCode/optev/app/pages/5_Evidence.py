"""Evidence (#34): ask why, see the answer and every piece of evidence behind it.

No logic here: questions go to optev.graph (explain / retrieve), and optev.app.evidence only
arranges what comes back. Works without a language model: the evidence is still shown.
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from neo4j.exceptions import DriverError, Neo4jError

from optev.app.evidence import LAYER_HELP, QUESTIONS, examples, missing_graph_settings, sections
from optev.graph.explain import classify, explain
from optev.graph.llm import LLMNotConfigured
from optev.graph.retrieve import retrieve

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

st.set_page_config(page_title="OptEV+ · Evidence", page_icon="🔎", layout="wide")
st.title("Evidence")
st.caption("Ask why a site was chosen or not. Every answer shows the evidence it rests on; "
           "with no evidence, the system says so instead of guessing.")

missing = missing_graph_settings()
if missing:
    st.warning("The knowledge graph is not configured on this deployment, so questions cannot "
               "be answered here. Missing settings: " + ", ".join(missing) + ". Every other page "
               "works without it; see the README, section 5, to add them.")
    st.stop()

shown, defaults = examples(real=bool(os.environ.get("DATABASE_URL")))
mode = st.radio("Ask", ["In my own words", "Pick a question"], horizontal=True)

question_type: str | None = None
params: dict[str, str] = {}
question = ""
if mode == "In my own words":
    question = st.text_input("Question", placeholder=shown[0])
    st.caption("Try: " + " · ".join(shown))
else:
    question_type = st.selectbox("Question", list(QUESTIONS),
                                 format_func=lambda k: QUESTIONS[k][0])
    for name in QUESTIONS[question_type][1]:
        default = {"scenario_id": "base", "rule_id": "R03", **defaults}.get(name, "")
        params[name] = st.text_input(name.replace("_", " "), value=default).strip()

if not st.button("Show evidence", type="primary"):
    st.stop()



def from_graph(call, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Run a graph call; if the graph cannot be reached, say so instead of a traceback."""
    try:
        return call(*args, **kwargs)
    except (DriverError, Neo4jError, OSError) as e:
        st.error("Could not reach the knowledge graph (" + type(e).__name__ + "). If it is "
                 "Neo4j Aura Free, it pauses after three days without a write: resume it at "
                 "console.neo4j.io and try again.")
        st.stop()


answer = None
if mode == "In my own words":
    if not question.strip():
        st.warning("Type a question first.")
        st.stop()
    try:
        answer = from_graph(explain, question)
        question_type, params, rows = answer.question_type, answer.params, answer.evidence
    except LLMNotConfigured:
        found = classify(question)
        if found is None:
            st.error("Out of scope: I can only answer about the sites, rules, demand, plans "
                     "and assumptions in the OptEV+ knowledge graph.")
            st.stop()
        question_type, params = found
        rows = from_graph(retrieve, question_type, **params)
        st.info("No language model is configured, so here is the evidence without a "
                "written answer.")
else:
    assert question_type is not None
    rows = from_graph(retrieve, question_type, **params)

if answer is not None:
    if answer.refused:
        st.error("**Refused.** " + answer.text)
        if answer.problems:
            st.caption("Failed checks: " + "; ".join(answer.problems))
    else:
        st.success(answer.text)
        st.caption("Cites: " + ", ".join(answer.cited))

if question_type:
    st.caption(f"Question type `{question_type}` · " +
               ", ".join(f"{k} = {v}" for k, v in params.items()))
if not rows:
    st.error("**No evidence** in the knowledge graph for this question. Nothing is recorded, "
             "so nothing is claimed.")
    st.stop()

for sec in sections(question_type, rows):
    st.subheader(sec.title)
    st.caption(f"**{sec.layer.upper()}**: {LAYER_HELP[sec.layer]}" +
               (f" {sec.note}" if sec.note else ""))
    if sec.rows:
        st.dataframe(pd.DataFrame(sec.rows), hide_index=True, use_container_width=True,
                     column_config={"link": st.column_config.LinkColumn("link")})
