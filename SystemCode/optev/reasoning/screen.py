"""Eligibility screening (SYSTEM_DESIGN.md §4.4, #19).

Runs the rules engine over every candidate site and stores one decision per site per
scenario, with every rule result, in `rule`, `decision` and `rule_result`. The allocator
reads the screened set; the outcome counts make the funnel visible.
"""

import logging
import os
from collections import Counter
from typing import Any

import psycopg
from psycopg.rows import dict_row

from optev.contracts import (
    CandidateSite,
    CarPark,
    Coordinate,
    Decision,
    Outcome,
    Rule,
    SiteIndicators,
)
from optev.reasoning.rules import evaluate, facts_without_indicators, load_register, site_facts

LOG = logging.getLogger(__name__)
OBSERVED = "observed"  # §3.2: decisions outside any scenario


def screen_sites(sites: list[CandidateSite], car_parks: list[CarPark],
                 indicators: list[SiteIndicators], contexts: dict[str, dict[str, object]],
                 rules: list[Rule], on_fail: dict[str, Outcome],
                 scenario_id: str | None = None) -> tuple[list[Decision], dict[str, int]]:
    """A decision for every site, and the funnel: sites, count per outcome, failures per rule.

    A site analysis has not measured is still screened: its supply facts are missing, so
    the rules that need them defer it rather than reject it.
    """
    parks = {p.car_park_id: p for p in car_parks}
    measured = {i.site_id: i for i in indicators}
    decisions = []
    for site in sorted(sites, key=lambda s: s.site_id):
        park = parks.get(site.car_park_id) if site.car_park_id else None
        context = contexts.get(site.site_id, {})
        ind = measured.get(site.site_id)
        facts = (site_facts(site, park, ind, context) if ind
                 else facts_without_indicators(site, park, context))
        decisions.append(evaluate(site.site_id, facts, rules, on_fail, scenario_id))
    outcomes = Counter(d.outcome.value for d in decisions)
    funnel = {"sites": len(decisions), **{o.value: outcomes[o.value] for o in Outcome}}
    for rule in rules:
        funnel[f"failed:{rule.rule_id}"] = sum(rule.rule_id in d.failing_rules for d in decisions)
        funnel[f"unevaluated:{rule.rule_id}"] = sum(
            rule.rule_id in d.unevaluated_rules for d in decisions)
    return decisions, funnel


_RULE = """
    INSERT INTO rule (rule_id, condition, source, source_ref, required_facts,
                      explanation_template, on_fail)
    VALUES (%(rule_id)s, %(condition)s, %(source)s, %(source_ref)s, %(required_facts)s,
            %(explanation_template)s, %(on_fail)s)
    ON CONFLICT (rule_id) DO UPDATE SET condition = EXCLUDED.condition,
        source = EXCLUDED.source, source_ref = EXCLUDED.source_ref,
        required_facts = EXCLUDED.required_facts,
        explanation_template = EXCLUDED.explanation_template, on_fail = EXCLUDED.on_fail"""
_DECISION = """
    INSERT INTO decision (site_id, scenario_id, outcome)
    VALUES (%(site_id)s, %(scenario_id)s, %(outcome)s)
    ON CONFLICT (site_id, scenario_id) DO UPDATE SET outcome = EXCLUDED.outcome,
        decided_at = now()"""
_CLEAR_RESULTS = """
    DELETE FROM rule_result WHERE site_id = %(site_id)s AND scenario_id = %(scenario_id)s"""
_RESULT = """
    INSERT INTO rule_result (site_id, scenario_id, rule_id, passed, detail)
    VALUES (%(site_id)s, %(scenario_id)s, %(rule_id)s, %(passed)s, %(detail)s)"""


def write_decisions(conn: psycopg.Connection[Any], rules: list[Rule],
                    on_fail: dict[str, Outcome], decisions: list[Decision]) -> dict[str, int]:
    """Upsert the register and the decisions; a site's rule results are replaced whole."""
    rule_rows = [{**r.model_dump(mode="json"), "on_fail": on_fail[r.rule_id].value}
                 for r in rules]
    decision_rows = [{"site_id": d.site_id, "scenario_id": d.scenario_id or OBSERVED,
                      "outcome": d.outcome.value} for d in decisions]
    result_rows = [{"site_id": d.site_id, "scenario_id": d.scenario_id or OBSERVED,
                    **r.model_dump(mode="json")} for d in decisions for r in d.results]
    with conn.cursor() as cur:
        for sql, rows in ((_RULE, rule_rows), (_DECISION, decision_rows),
                          (_CLEAR_RESULTS, decision_rows), (_RESULT, result_rows)):
            if rows:
                cur.executemany(sql, rows)
    return {"rule": len(rule_rows), "decision": len(decision_rows),
            "rule_result": len(result_rows)}


Inputs = tuple[list[CandidateSite], list[CarPark], list[SiteIndicators],
               dict[str, dict[str, object]]]


def _read(conn: psycopg.Connection[Any]) -> Inputs:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT site_id, kind, planning_area, car_park_id, total_lots, "
                    "existing_connectors, ST_Y(geom) AS lat, ST_X(geom) AS lon "
                    "FROM candidate_site")
        sites = [CandidateSite(coord=Coordinate(lat=r.pop("lat"), lon=r.pop("lon")), **r)
                 for r in cur.fetchall()]
        cur.execute("SELECT car_park_id, name, planning_area, total_lots, car_park_type, "
                    "has_live_feed, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM car_park")
        parks = [CarPark(coord=Coordinate(lat=r.pop("lat"), lon=r.pop("lon")), **r)
                 for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT ON (site_id) * FROM site_indicators "
                    "ORDER BY site_id, window_end DESC")
        indicators = [SiteIndicators.model_validate(
            {**r, "window_start": r["window_start"].isoformat(),
             "window_end": r["window_end"].isoformat()}) for r in cur.fetchall()]
        cur.execute("SELECT * FROM site_context")
        contexts = {r.pop("site_id"): r for r in cur.fetchall()}
    return sites, parks, indicators, contexts


def screen(scenario_id: str = OBSERVED) -> dict[str, int]:
    """Screen every candidate site in Postgres and store the decisions. Returns the funnel."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set; copy .env.example to .env and fill it in")
    rules, on_fail = load_register()
    with psycopg.connect(url) as conn:
        sites, parks, indicators, contexts = _read(conn)
        decisions, funnel = screen_sites(sites, parks, indicators, contexts, rules, on_fail,
                                         scenario_id)
        write_decisions(conn, rules, on_fail, decisions)
        conn.commit()
    LOG.info("screened %s: %s", scenario_id, funnel)
    return funnel
