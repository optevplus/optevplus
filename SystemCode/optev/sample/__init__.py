"""Shared sample data: one synthetic slice of Tampines and Pasir Ris, typed with the contracts.

Build and test against this until real data lands, then swap it out. Every id starts with
SYN- so it can never be mistaken for observed data.

    from optev.sample import load
    s = load()
    s.sites, s.indicators, s.estimates, s.rules, s.decisions, s.allocation

Regenerate with `uv run python -m optev.sample.generate`. See README.md in this folder.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optev.contracts import (
    Allocation,
    CandidateSite,
    CarPark,
    CarParkReading,
    Connector,
    ConnectorReading,
    Decision,
    DemandEstimate,
    InfeasibilityReport,
    Outcome,
    PlanningArea,
    Rule,
    Scenario,
    SiteIndicators,
    Station,
)

DATA = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Sample:
    planning_areas: list[PlanningArea]
    car_parks: list[CarPark]
    stations: list[Station]
    connectors: list[Connector]
    sites: list[CandidateSite]
    near: list[dict[str, Any]]
    """Station-to-site spatial associations, as ingest (#10) will produce them."""
    indicators: list[SiteIndicators]
    estimates: list[DemandEstimate]
    rules: list[Rule]
    rule_on_fail: dict[str, Outcome]
    """Sample-only: the outcome each rule gives when it fails. The real register decides this."""
    decisions: list[Decision]
    scenarios: list[Scenario]
    allocation: Allocation
    infeasibility: InfeasibilityReport
    references: dict[str, list[dict[str, Any]]]
    """Datasets, policy documents and declared assumptions that rules and estimates cite."""


def load() -> Sample:
    raw = json.loads((DATA / "entities.json").read_text())
    return Sample(
        planning_areas=[PlanningArea.model_validate(x) for x in raw["planning_areas"]],
        car_parks=[CarPark.model_validate(x) for x in raw["car_parks"]],
        stations=[Station.model_validate(x) for x in raw["stations"]],
        connectors=[Connector.model_validate(x) for x in raw["connectors"]],
        sites=[CandidateSite.model_validate(x) for x in raw["sites"]],
        near=raw["near"],
        indicators=[SiteIndicators.model_validate(x) for x in raw["indicators"]],
        estimates=[DemandEstimate.model_validate(x) for x in raw["estimates"]],
        rules=[Rule.model_validate(x) for x in raw["rules"]],
        rule_on_fail={k: Outcome(v) for k, v in raw["rule_on_fail"].items()},
        decisions=[Decision.model_validate(x) for x in raw["decisions"]],
        scenarios=[Scenario.model_validate(x) for x in raw["scenarios"]],
        allocation=Allocation.model_validate(raw["allocation"]),
        infeasibility=InfeasibilityReport.model_validate(raw["infeasibility"]),
        references=raw["references"],
    )


def connector_readings() -> list[ConnectorReading]:
    """30-minute charger statuses over two days, simulated from a known demand."""
    with (DATA / "connector_readings.csv").open() as fh:
        return [ConnectorReading.model_validate(row) for row in csv.DictReader(fh)]


def car_park_readings() -> list[CarParkReading]:
    """30-minute lots-available readings for every sample car park."""
    with (DATA / "car_park_readings.csv").open() as fh:
        return [CarParkReading.model_validate(row) for row in csv.DictReader(fh)]


def truth() -> dict[str, Any]:
    """The demand the readings were simulated from. An answer key for evaluation only:
    never feed it to a model."""
    result: dict[str, Any] = json.loads((DATA / "truth.json").read_text())
    return result
