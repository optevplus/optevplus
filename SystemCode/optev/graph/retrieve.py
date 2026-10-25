"""Fixed, parameterised Cypher for the planner's questions (#26, design §4.5).

Every question type has one query written here, never one generated at run time. Values
reach Cypher only as parameters. A query that finds nothing returns [], which the
explanation layer must report as "no evidence", never fill in.

Each row names the nodes it came from (decision, rule, estimate, document, dataset or
assumption ids), so an answer can cite every number it uses.
"""

from dataclasses import dataclass
from typing import Any

from . import schema as S
from .ddl import Session

# Always passed, so templates never spell out a key format or a default themselves.
CONSTANTS = {"baseline": S.BASELINE, "island": S.ISLAND_WIDE}


@dataclass(frozen=True)
class Template:
    params: tuple[tuple[str, str | None], ...]
    """(name, default); a None default means the caller must give it."""
    cypher: str
    answers: str


# Shared fragments. Each expects the site bound as `s` (and the decision as `d`).
_SITE = """s.site_id AS site_id, s.kind AS kind, s.total_lots AS total_lots,
  s.existing_connectors AS existing_connectors,
  head(COLLECT { MATCH (s)-[:IN_AREA]->(a:PlanningArea) RETURN a.code }) AS planning_area"""

_DECISION = """OPTIONAL MATCH (d:Decision)-[:ABOUT]->(s)
WHERE coalesce(d.scenario_id, $baseline) = $scenario_id"""


def _rules(verdicts: str) -> str:
    return f"""COLLECT {{
    MATCH (d)-[e:EVALUATED]->(r:Rule)-[:FROM_SOURCE]->(c:SourceClass)
    WHERE e.verdict IN {verdicts}
    OPTIONAL MATCH (r)-[:CITES|READS|ASSUMES]->(src)
    RETURN {{rule_id: r.rule_id, condition: r.condition, verdict: e.verdict,
            detail: e.detail, on_fail: r.on_fail, source_class: c.code,
            evidence_id: coalesce(src.doc_id, src.dataset_id, src.assumption_id),
            evidence: coalesce(src.title, src.name), url: src.url}}
    ORDER BY r.rule_id }}"""


_DEMAND = """COLLECT {
    MATCH (s)-[:HAS_DEMAND]->(est:DemandEstimate)
    RETURN {estimate_id: est.estimate_id, time_bin: est.time_bin,
            arrivals_per_hour: est.arrivals_per_hour, kind: est.kind, note: est.note,
            based_on: COLLECT { MATCH (est)-[:BASED_ON]->(i:Indicator) RETURN i.indicator_id },
            assumptions: COLLECT { MATCH (est)-[:ASSUMES]->(asm:Assumption)
                                   RETURN {assumption_id: asm.assumption_id, name: asm.name,
                                           value: asm.value, unit: asm.unit} }} }"""

_INDICATORS = """COLLECT {
    MATCH (s)-[:HAS_INDICATOR]->(i:Indicator)
    OPTIONAL MATCH (i)-[:DERIVED_FROM]->(ds:Dataset)
    RETURN {indicator_id: i.indicator_id, window_start: i.window_start,
            window_end: i.window_end, supply_state: i.supply_state,
            active_connectors: i.active_connectors, utilisation: i.utilisation,
            saturated_fraction: i.saturated_fraction,
            observation_coverage: i.observation_coverage,
            dataset_id: ds.dataset_id, dataset: ds.name} }"""

_ALLOCATED = """COLLECT {
    MATCH (al:Allocation)-[x:ALLOCATES]->(s)
    OPTIONAL MATCH (al)-[:UNDER]->(sc:Scenario)
    RETURN {allocation_id: al.allocation_id, scenario_id: sc.scenario_id,
            connectors: x.connectors, cost: x.cost, marginal_relief: x.marginal_relief} }"""

_PLANNED = """COLLECT {
    MATCH (sc:Scenario)-[p:PLANS]->(s)
    RETURN {scenario_id: sc.scenario_id, connectors: p.connectors,
            selected_by: p.selected_by} }"""

_SITE_PARAMS: tuple[tuple[str, str | None], ...] = (("site_id", None), ("scenario_id", S.BASELINE))

TEMPLATES: dict[str, Template] = {
    "why_site": Template(
        _SITE_PARAMS,
        f"""MATCH (s:CandidateSite {{site_id: $site_id}})
{_DECISION}
RETURN {_SITE}, d.decision_id AS decision_id, d.outcome AS outcome,
  {_rules("['passed', 'failed', 'unevaluated']")} AS rules,
  {_DEMAND} AS demand, {_ALLOCATED} AS allocated, {_PLANNED} AS planned""",
        "The site's outcome, every rule it was checked against with the evidence behind "
        "each, its demand, and any points allocated or planned there.",
    ),
    "why_not_site": Template(
        _SITE_PARAMS,
        f"""MATCH (s:CandidateSite {{site_id: $site_id}})
{_DECISION}
RETURN {_SITE}, d.decision_id AS decision_id, d.outcome AS outcome,
  {_rules("['failed', 'unevaluated']")} AS rules""",
        "The site's outcome and only the rules it failed or could not be checked against, "
        "with whether each rejects or only makes the site conditional. An accepted site "
        "comes back with outcome 'accept' and no rules.",
    ),
    "demand_basis": Template(
        (("site_id", None),),
        f"""MATCH (s:CandidateSite {{site_id: $site_id}})
RETURN {_SITE}, {_INDICATORS} AS indicators, {_DEMAND} AS demand""",
        "Where the site's demand number comes from: the indicators and dataset behind it, "
        "whether it is a point estimate or a lower bound, and the assumptions it uses.",
    ),
    "compare_sites": Template(
        (("site_a", None), ("site_b", None), ("scenario_id", S.BASELINE)),
        f"""UNWIND [$site_a, $site_b] AS wanted
MATCH (s:CandidateSite {{site_id: wanted}})
{_DECISION}
RETURN {_SITE}, d.outcome AS outcome,
  {_rules("['failed', 'unevaluated']")} AS rules_not_passed,
  {_DEMAND} AS demand, {_ALLOCATED} AS allocated
ORDER BY CASE site_id WHEN $site_a THEN 0 ELSE 1 END""",
        "The same facts for two sites side by side: outcome, rules not passed, demand, "
        "points allocated. A site that does not exist is missing from the rows.",
    ),
    "rule_sources": Template(
        (("rule_id", None),),
        """MATCH (r:Rule {rule_id: $rule_id})-[:FROM_SOURCE]->(c:SourceClass)
OPTIONAL MATCH (r)-[:CITES|READS|ASSUMES]->(src)
RETURN r.rule_id AS rule_id, r.condition AS condition, r.on_fail AS on_fail,
  c.code AS source_class, c.meaning AS source_meaning, r.source_ref AS source_ref,
  coalesce(src.title, src.name) AS evidence, src.url AS url, src.value AS value,
  src.unit AS unit,
  COUNT { (:Decision)-[:EVALUATED {verdict: 'passed'}]->(r) } AS sites_passed,
  COUNT { (:Decision)-[:EVALUATED {verdict: 'failed'}]->(r) } AS sites_failed,
  COUNT { (:Decision)-[:EVALUATED {verdict: 'unevaluated'}]->(r) } AS sites_unevaluated""",
        "Where a rule comes from: its source class, the document, dataset or assumption "
        "it cites, and how many sites passed, failed or could not be checked.",
    ),
    "infeasible_request": Template(
        (("scenario_id", "base"), ("planning_area", S.ISLAND_WIDE)),
        """MATCH (i:Infeasibility)-[:FOR]->(:Scenario {scenario_id: $scenario_id})
WHERE coalesce(i.planning_area, $island) = $planning_area
RETURN i.report_id AS report_id, coalesce(i.planning_area, $island) AS planning_area,
  i.requested_connectors AS requested_connectors, i.max_feasible AS max_feasible,
  i.binding_constraints AS binding_constraints,
  COLLECT { MATCH (i)-[:AFFECTS]->(a:PlanningArea) RETURN a.code } AS affected_areas""",
        "Why a request could not be met: points requested, the most any feasible plan "
        "allows, and which constraints and areas stood in the way.",
    ),
    "area_saturation": Template(
        (),
        """MATCH (a:PlanningArea)<-[:IN_AREA]-(s:CandidateSite)-[:HAS_INDICATOR]->(i:Indicator)
WHERE i.saturated_fraction IS NOT NULL
WITH a, count(DISTINCT s) AS sites_with_chargers,
  round(avg(i.saturated_fraction), 3) AS mean_saturated_fraction,
  round(max(i.saturated_fraction), 3) AS max_saturated_fraction,
  collect(DISTINCT i.indicator_id) AS indicator_ids
RETURN a.code AS planning_area, a.name AS name, sites_with_chargers,
  mean_saturated_fraction, max_saturated_fraction,
  COUNT { (a)<-[:IN_AREA]-(:CandidateSite)-[:HAS_DEMAND]->(:DemandEstimate {kind: 'lower_bound'}) }
    AS lower_bound_sites,
  indicator_ids
ORDER BY mean_saturated_fraction DESC""",
        "Planning areas ranked by how often their chargers were all in use, with the "
        "number of sites whose demand is only a lower bound.",
    ),
    "assumptions_used": Template(
        _SITE_PARAMS,
        f"""MATCH (s:CandidateSite {{site_id: $site_id}})
{_DECISION}
RETURN s.site_id AS site_id, d.decision_id AS decision_id,
  COLLECT {{
    MATCH (s)-[:HAS_DEMAND]->(est:DemandEstimate)-[:ASSUMES]->(asm:Assumption)
    RETURN {{assumption_id: asm.assumption_id, name: asm.name, value: asm.value,
            unit: asm.unit, source_ref: asm.source_ref, used_by: est.estimate_id}} AS used
    UNION
    MATCH (d)-[:EVALUATED]->(r:Rule)-[:ASSUMES]->(asm:Assumption)
    RETURN {{assumption_id: asm.assumption_id, name: asm.name, value: asm.value,
            unit: asm.unit, source_ref: asm.source_ref, used_by: r.rule_id}} AS used
  }} AS assumptions""",
        "Every declared value behind a site's demand estimate and decision, and which "
        "estimate or rule used it.",
    ),
}


def bind(question_type: str, params: dict[str, str]) -> tuple[Template, dict[str, Any]]:
    """Check the question type and parameters, fill defaults, add the constants."""
    if question_type not in TEMPLATES:
        raise ValueError(f"unknown question type {question_type!r}; one of {sorted(TEMPLATES)}")
    template = TEMPLATES[question_type]
    names = {name for name, _ in template.params}
    unknown = set(params) - names
    if unknown:
        raise ValueError(f"{question_type} takes {sorted(names)}, not {sorted(unknown)}")
    bound: dict[str, Any] = dict(CONSTANTS)
    for name, default in template.params:
        value = params.get(name, default)
        if value is None:
            raise ValueError(f"{question_type} needs {name}")
        bound[name] = value
    return template, bound


def run(session: Session, question_type: str, **params: str) -> list[dict[str, Any]]:
    """Answer one question with the session given. [] means no evidence."""
    template, bound = bind(question_type, params)
    rows: list[dict[str, Any]] = session.run(template.cypher, bound).data()
    return rows


def retrieve(question_type: str, **params: str) -> list[dict[str, object]]:
    """Design §4.5 entry point: opens its own connection to the graph."""
    from .client import driver

    # A relationship type with no rows yet (e.g. AFFECTS on the sample) only raises a
    # warning; the answer is still correct, so keep the logs quiet.
    with driver() as d, d.session(notifications_min_severity="OFF") as s:
        return list(run(s, question_type, **params))
