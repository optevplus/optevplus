"""The knowledge-graph slice and answer card on Ask Why (optev.app.evidence_graph)."""

import re

from optev.app import evidence_graph as EG
from optev.app.data import from_sample

DATA = from_sample()
ID = re.compile(r"\b(SYN-S-\d+|hdb:\w+|R0[1-6]|doc-|ds-|asm-)")
ROW = {
    "site_id": "SYN-S-04", "kind": "hdb_car_park", "total_lots": 210, "existing_connectors": 2,
    "planning_area": "TM", "decision_id": "observed:SYN-S-04", "outcome": "accept",
    "rules": [{"rule_id": "R03", "verdict": "passed", "condition": "within MAX_SHARE_OF_LOTS",
               "evidence_id": "doc-lta-ev-factsheet-2021", "evidence": "LTA factsheet",
               "detail": "room 29"}],
    "indicators": [{"indicator_id": "i1", "utilisation": 0.87, "dataset_id": "ds-lta-evcbatch",
                    "dataset": "EV Charging Points Batch"}],
    "demand": [{"estimate_id": "SYN-S-04@all", "arrivals_per_hour": 3.22, "kind": "point",
                "based_on": ["i1"], "assumptions": [{"assumption_id": "asm-session-hours",
                                                     "name": "Mean charging session",
                                                     "value": 3.0, "unit": "hours"}]}],
    "allocated": [{"allocation_id": "base:all:points=12:budget=-", "connectors": 5}],
}


def test_the_graph_holds_what_the_query_returned_and_only_that():
    g = EG.build("why_site", [ROW], DATA)
    groups = sorted({n["group"] for n in g.nodes.values()})
    assert groups == ["accept", "area", "assumption", "demand", "measure", "plan", "site",
                      "source"]
    ends = {(e["from"], e["to"]) for e in g.edges}
    assert all(a in g.nodes and b in g.nodes for a, b in ends)  # no dangling links
    assert ("dem:SYN-S-04@all", "ind:i1") in ends  # the estimate rests on the measured week


def test_the_graph_shows_words_not_ids():
    g = EG.build("why_site", [ROW], DATA)
    for n in g.nodes.values():
        assert not ID.search(n["label"]), n["label"]
        assert "MAX_SHARE_OF_LOTS" not in n["title"]


def test_the_answer_card_states_the_verdict_and_splits_the_reasoning():
    place, outcome, what = EG.headline("why_site", [ROW], DATA)[0]
    assert outcome == "accept" and what == "5 new points recommended"
    assert not ID.search(place)
    assert EG.points("It passed. Demand is 3.22 an hour. Room is 29.") == [
        "It passed.", "Demand is 3.22 an hour.", "Room is 29."]


def test_saturation_and_rule_questions_draw_too():
    sat = EG.build("area_saturation", [{"planning_area": "TM", "max_saturated_fraction": 0.9,
                                        "sites_with_chargers": 4}], DATA)
    assert len(sat.nodes) == 2 and len(sat.edges) == 1
    rule = EG.build("rule_sources", [{"rule_id": "R03", "condition": "c", "source_ref": "doc-x",
                                      "evidence": "Doc", "sites_passed": 3, "sites_failed": 1,
                                      "sites_unevaluated": 0}], DATA)
    assert len(rule.nodes) == 5


def test_two_sites_in_one_plan_share_the_plan_node_with_their_own_counts():
    other = {**ROW, "site_id": "SYN-S-05", "allocated": [
        {"allocation_id": "base:all:points=12:budget=-", "connectors": 3}]}
    g = EG.build("compare_sites", [ROW, other], DATA)
    plans = [n for n in g.nodes.values() if n["group"] == "plan"]
    assert len(plans) == 1 and "12-point plan" in plans[0]["label"]
    counts = sorted(e["label"] for e in g.edges if e["to"] == plans[0]["id"])
    assert counts == ["3 new points", "5 new points"]
