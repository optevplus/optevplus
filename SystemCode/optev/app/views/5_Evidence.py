"""Evidence (#34): ask why, see the answer and every piece of evidence behind it.

No logic here: questions go to optev.graph (explain / retrieve), and optev.app.evidence only
arranges what comes back. Works without a language model: the evidence is still shown.
"""

import html
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from neo4j.exceptions import DriverError, Neo4jError

from optev.app import evidence_graph as EG
from optev.app import labels as L
from optev.app.evidence import (
    LAYER_HELP,
    QUESTION_LIMIT,
    QUESTIONS,
    examples,
    missing_graph_settings,
    sections,
    spend_question,
)
from optev.app.ui import app_data, graph_view, page_header, section
from optev.graph.explain import classify, explain
from optev.graph.llm import LLMNotConfigured
from optev.graph.retrieve import retrieve

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

page_header("Ask", "Why", "Ask why a site was chosen or not. Every answer shows the evidence it "
            "rests on from the knowledge graph; with no evidence, the system says so instead "
            "of guessing.", kicker="Explain")

missing = missing_graph_settings()
if missing:
    st.warning("The knowledge graph is not configured on this deployment, so questions cannot "
               "be answered here. Missing settings: " + ", ".join(missing) + ". Every other page "
               "works without it; see the README, section 5, to add them.")
    st.stop()




data = app_data()
ids, defaults = examples(real=bool(os.environ.get("DATABASE_URL")))
shown = [L.text(q, data) for q in ids]  # the same questions, asked by place name
mode = st.radio("Ask", ["In My Own Words", "Pick a Question"], horizontal=True)

question_type: str | None = None
params: dict[str, str] = {}
question = ""
if mode == "In My Own Words":
    question = st.text_input("Question", value=shown[0])  # a real example, ready to ask
    st.caption("Try: " + " · ".join(shown))
else:
    question_type = st.selectbox("Question", list(QUESTIONS),
                                 format_func=lambda k: QUESTIONS[k][0])
    site_ids = sorted(data.site_names, key=lambda i: data.site_names[i])
    areas = sorted({s.planning_area for s in data.sites if s.planning_area})
    choices = {"site_id": site_ids, "site_a": site_ids, "site_b": site_ids,
               "rule_id": sorted(L.RULE_NAMES), "planning_area": areas,
               "scenario_id": [s.scenario_id for s in data.scenarios]}
    shows = {"rule_id": L.rule, "planning_area": lambda a: L.area(data, a),
             "scenario_id": str.title}
    names = {"site_id": "Site", "site_a": "First Site", "site_b": "Second Site",
             "rule_id": "Rule", "planning_area": "Planning Area", "scenario_id": "Scenario"}
    for name in QUESTIONS[question_type][1]:
        options = choices.get(name, [])
        default = {"scenario_id": "base", "rule_id": "R03", **defaults}.get(name)
        params[name] = st.selectbox(
            names.get(name, L.title(name)), options,
            index=options.index(default) if default in options else 0,
            format_func=shows.get(name, lambda i: L.site(data, i)))

if not st.button("Show Evidence", type="primary"):
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
if mode == "In My Own Words":
    if not question.strip():
        st.warning("Type a question first.")
        st.stop()
    limit = int(os.environ.get("OPTEV_QUESTION_LIMIT", QUESTION_LIMIT))
    if not spend_question(st.session_state, limit):
        st.warning(f"You've used the {limit} written answers this demo allows per visit. "
                   "**Pick a Question** still shows the evidence for any site.")
        st.stop()
    try:
        answer = from_graph(explain, L.resolve_names(question, data))
        question_type, params, rows = answer.question_type, answer.params, answer.evidence
    except LLMNotConfigured:
        found = classify(L.resolve_names(question, data))
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

if not rows:
    st.error("**No evidence** in the knowledge graph for this question. Nothing is recorded, "
             "so nothing is claimed.")
    st.stop()

# The answer: a verdict per site, the reasoning as points, the sources as tags ------------
OUTCOME_ICON = {"accept": "✓", "conditional": "◐", "defer": "…", "reject": "✕"}
verdicts = "".join(
    f'<div class="ox-verdict ox-{outcome}"><span class="ox-verdict-mark">'
    f'{OUTCOME_ICON.get(outcome, "•")}</span><div>'
    f'<div class="ox-verdict-place">{html.escape(place)}'
    f'</div><div class="ox-verdict-what">{outcome.title()} · {html.escape(what)}</div></div></div>'
    for place, outcome, what in EG.headline(question_type, rows, data))
if answer is not None and answer.refused:
    st.markdown(f'<div class="ox-answer">{verdicts}<div class="ox-refused"><b>No written answer.'
                '</b> The model\'s draft cited something the evidence does not hold, so OptEV+ '
                'shows the evidence itself instead.</div></div>', unsafe_allow_html=True)
    if answer.problems:
        st.caption("Checks that failed: " + "; ".join(answer.problems))
elif answer is not None:
    text, sources = L.readable_answer(answer.text, data)
    bullets = "".join(f"<li>{html.escape(p)}</li>" for p in EG.points(text))
    chips = "".join(f'<span class="ox-chip">{html.escape(s)}</span>' for s in sources)
    st.markdown(f'<div class="ox-answer">{verdicts}<div class="ox-answer-h">Why</div>'
                f'<ul class="ox-points">{bullets}</ul>'
                + (f'<div class="ox-answer-h">Sources</div><div>{chips}</div>' if chips else "")
                + "</div>", unsafe_allow_html=True)
elif verdicts:
    st.markdown(f'<div class="ox-answer">{verdicts}</div>', unsafe_allow_html=True)

# The part of the knowledge graph the answer used -----------------------------------------
graph = EG.build(question_type, rows, data)
if graph.nodes:
    section("How OptEV+ Got This Answer")
    st.markdown(f'<div class="ox-lead">The part of the knowledge graph this answer used: '
                f'{len(graph.nodes)} facts and {len(graph.edges)} links, retrieved by a fixed '
                'query. Drag a node; hover for detail.</div>', unsafe_allow_html=True)
    graph_view(list(graph.nodes.values()), graph.edges,  # taller as the slice grows
               height=min(680, 380 + 16 * len(graph.nodes)))
    used = {n["group"] for n in graph.nodes.values()}
    st.markdown("".join(
        f'<span class="ox-key"><i style="background:{EG.COLOURS[g][0]}"></i>{label}</span>'
        for g, label in EG.LEGEND if g in used), unsafe_allow_html=True)

with st.expander("See the Evidence as Tables", expanded=answer is None):
    for sec in sections(question_type, rows):
        st.subheader(L.text(sec.title, data))
        st.caption(f"**{sec.layer.upper()}**: {LAYER_HELP[sec.layer]}" +
                   (f" {sec.note}" if sec.note else ""))
        if sec.rows:
            st.dataframe(pd.DataFrame(L.table(sec.rows, data)), hide_index=True,
                         width="stretch",
                         column_config={"Link": st.column_config.LinkColumn("Link")})
