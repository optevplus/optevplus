"""Graph schema: node labels, keys and relationships, declared once for every loader.

Postgres is the source of truth for numbers; the graph holds what relates to what, so an
explanation is walked, not generated. Each node mirrors a frozen contract and is keyed on
that contract's identifier, so a load MERGEs on the key and can be re-run without
duplicating anything.

Two rules carried over from the contracts:
- Planned capacity is a relationship from a Scenario, never a property of a site. A
  planner's selection must not look like something that was observed.
- A missing value is an absent property, never 0. Neo4j cannot store null, and writing 0
  for an undefined utilisation would rank the site as if nobody wanted to charge there.
"""

from dataclasses import dataclass

from optev.contracts import RuleResult, RuleSource

BASELINE = "observed"
"""Scenario id used in keys for records that belong to no scenario."""


@dataclass(frozen=True)
class NodeSpec:
    label: str
    key: str
    contract: str
    """The contract model this node mirrors; empty when the node exists only in the graph."""
    properties: tuple[str, ...] = ()
    meaning: str = ""
    table_only: tuple[str, ...] = ()
    """Properties the Postgres table holds but the contract does not (design §3.2)."""


@dataclass(frozen=True)
class RelSpec:
    type: str
    start: str
    end: str
    properties: tuple[str, ...] = ()
    meaning: str = ""


NODES: tuple[NodeSpec, ...] = (
    NodeSpec("PlanningArea", "code", "PlanningArea", ("name", "region"),
             "One of the 55 URA Master Plan 2025 planning areas."),
    NodeSpec("CarPark", "car_park_id", "CarPark",
             ("name", "lat", "lon", "total_lots", "car_park_type", "has_live_feed"),
             "A car park from the HDB or URA registry."),
    NodeSpec("Station", "station_id", "Station",
             ("lat", "lon", "operator", "address", "provenance"),
             "A charging location. Holds one or more connectors."),
    NodeSpec("Connector", "connector_id", "Connector",
             ("plug_type", "power_kw", "ever_active"),
             "One plug. Capacity is counted here, never at station level."),
    NodeSpec("CandidateSite", "site_id", "CandidateSite",
             ("kind", "lat", "lon", "total_lots", "existing_connectors", "provenance"),
             "Somewhere chargers could go. The unit every decision is about."),
    NodeSpec("Indicator", "indicator_id", "SiteIndicators",
             ("window_start", "window_end", "supply_state", "active_connectors",
              "utilisation", "saturated_fraction", "observation_coverage"),
             "Utilisation and saturation for one site over one time window."),
    NodeSpec("DemandEstimate", "estimate_id", "DemandEstimate",
             ("time_bin", "arrivals_per_hour", "kind", "note"),
             "Arrivals per hour. kind=lower_bound when the site is saturated."),
    NodeSpec("Dataset", "dataset_id", "",
             ("name", "publisher", "url"),
             "A published government dataset that observations come from."),
    NodeSpec("Document", "doc_id", "",
             ("title", "publisher", "url"),
             "A published policy document that a rule cites."),
    NodeSpec("SourceClass", "code", "",
             ("meaning",),
             "Why a rule exists: dataset, policy, arithmetic or our own assumption."),
    NodeSpec("Rule", "rule_id", "Rule",
             ("condition", "source", "source_ref", "required_facts", "explanation_template",
              "on_fail"),
             "One entry in the rule register. on_fail says whether failing it rejects a site "
             "or only makes it conditional.",
             table_only=("on_fail",)),
    NodeSpec("Assumption", "assumption_id", "",
             ("name", "value", "unit", "source_ref"),
             "A declared value, e.g. mean session length or growth rate."),
    NodeSpec("Scenario", "scenario_id", "Scenario",
             ("seed", "growth_multiplier", "horizon_months", "baseline_window", "provenance"),
             "A simulated future under declared assumptions."),
    NodeSpec("Decision", "decision_id", "Decision",
             ("site_id", "outcome", "scenario_id"),
             "The verdict for one site, with every rule that was evaluated."),
    NodeSpec("Allocation", "allocation_id", "Allocation",
             ("planning_area", "requested_connectors", "budget", "checked", "violations"),
             "The allocator's answer to one request (area, points, optional budget), after "
             "the independent check."),
    NodeSpec("Infeasibility", "report_id", "InfeasibilityReport",
             ("planning_area", "requested_connectors", "max_feasible", "binding_constraints"),
             "Why a request could not be met, and how far it could go."),
)

RELATIONSHIPS: tuple[RelSpec, ...] = (
    # Where things are
    RelSpec("IN_AREA", "CarPark", "PlanningArea"),
    RelSpec("IN_AREA", "Station", "PlanningArea"),
    RelSpec("IN_AREA", "CandidateSite", "PlanningArea"),
    RelSpec("PART_OF", "Connector", "Station"),
    RelSpec("AT", "CandidateSite", "CarPark", meaning="The car park a candidate sits in."),
    RelSpec("NEAR", "Station", "CandidateSite", ("distance_m", "threshold_m"),
            "Spatial association at 50, 100 or 200 m. Not proof of ownership."),
    # What was measured, and from where
    RelSpec("HAS_INDICATOR", "CandidateSite", "Indicator"),
    RelSpec("DERIVED_FROM", "Indicator", "Dataset"),
    RelSpec("HAS_DEMAND", "CandidateSite", "DemandEstimate"),
    RelSpec("BASED_ON", "DemandEstimate", "Indicator",
            meaning="Absent for sites with no chargers: those are estimated from comparables."),
    RelSpec("ASSUMES", "DemandEstimate", "Assumption"),
    # Why a rule exists: the provenance model
    RelSpec("FROM_SOURCE", "Rule", "SourceClass"),
    RelSpec("CITES", "Rule", "Document", meaning="The document the rule's source_ref names."),
    RelSpec("READS", "Rule", "Dataset", meaning="The dataset the rule's source_ref names."),
    RelSpec("ASSUMES", "Rule", "Assumption",
            meaning="The declared value the rule's source_ref names."),
    # What was decided
    RelSpec("ABOUT", "Decision", "CandidateSite"),
    RelSpec("EVALUATED", "Decision", "Rule", ("verdict", "detail"),
            "One per rule evaluated. verdict is passed, failed or unevaluated."),
    RelSpec("UNDER", "Decision", "Scenario"),
    RelSpec("ASSUMES", "Scenario", "Assumption"),
    RelSpec("PLANS", "Scenario", "CandidateSite", ("connectors", "selected_by"),
            "A planner's selection. Planned layer only; never written onto the site."),
    RelSpec("UNDER", "Allocation", "Scenario"),
    RelSpec("ALLOCATES", "Allocation", "CandidateSite", ("connectors", "cost", "marginal_relief")),
    RelSpec("FOR", "Infeasibility", "Scenario"),
    RelSpec("AFFECTS", "Infeasibility", "PlanningArea"),
)

# Reference ids (design §3.3). A rule's source_ref names one of these, and its prefix says
# which kind of node it is.
DATASET_PREFIX, DOCUMENT_PREFIX, ASSUMPTION_PREFIX = "ds-", "doc-", "asm-"
EV_FEED = "ds-lta-evcbatch"
"""LTA EV Charging Points Batch: every indicator is derived from it."""
SESSION_ASSUMPTION = "asm-session-hours"
"""Every demand estimate assumes the mean charging session length."""
RELIABILITY_ASSUMPTION = "asm-reliable-up-to"
"""A lower bound exists because occupancy above this limit cannot be inverted reliably."""
SAMPLE_LABEL = "Sample"
"""Extra label on everything loaded from optev.sample, so it can be removed in one query."""

SOURCE_CLASSES: dict[RuleSource, str] = {
    RuleSource.GOV_DATASET: "Reads a field from a published government dataset.",
    RuleSource.GOV_POLICY: "Cites a published government policy document.",
    RuleSource.MATH_CONSTRAINT: "An arithmetic or physical limit, not a judgement.",
    RuleSource.PROJECT_ASSUMPTION: "Our own declared value. A planner may weigh it differently.",
}


# Keys for nodes whose contract has no single identifier. Deterministic, so a re-run
# MERGEs onto the same node instead of creating a second one.

def decision_key(site_id: str, scenario_id: str | None) -> str:
    return f"{scenario_id or BASELINE}:{site_id}"


def indicator_key(site_id: str, window_start: str, window_end: str) -> str:
    return f"{site_id}@{window_start}/{window_end}"


def estimate_key(site_id: str, time_bin: str) -> str:
    return f"{site_id}@{time_bin}"


ISLAND_WIDE = "all"
"""Area part of a key when the request covers every planning area."""


def allocation_key(
    scenario_id: str, planning_area: str | None, requested_connectors: int | None,
    budget: float | None,
) -> str:
    """One allocation per request, so re-running the same request replaces it. Points and
    budget are each optional (design §1), so an absent one is written as "-". The budget is
    written in full to the cent: any rounding would give two budgets the same id. The
    allocator writes this same id to Postgres (design §3.3)."""
    points = "-" if requested_connectors is None else str(requested_connectors)
    money = "-" if budget is None else f"{budget:.2f}"
    return f"{scenario_id}:{planning_area or ISLAND_WIDE}:points={points}:budget={money}"


def infeasibility_key(
    scenario_id: str, planning_area: str | None, requested_connectors: int
) -> str:
    return f"{scenario_id}:{planning_area or ISLAND_WIDE}:requested={requested_connectors}"


DERIVED_KEYS = {"decision_id", "indicator_id", "estimate_id", "allocation_id", "report_id"}
"""Keys built by the helpers above, because the contract has no single identifier."""


def verdict(result: RuleResult) -> str:
    """Three-valued, because Neo4j cannot store null and "could not evaluate" must stay
    distinct from "failed"."""
    if result.passed is None:
        return "unevaluated"
    return "passed" if result.passed else "failed"


def node(label: str) -> NodeSpec:
    return next(n for n in NODES if n.label == label)
