"""Rules, decisions and allocations. Everything a planner is shown must be traceable
to objects in this module."""

from pydantic import BaseModel, Field

from .enums import Outcome, RuleSource


class Rule(BaseModel):
    """One entry in the rule register.

    `required_facts` is what separates "this site failed the rule" from "this rule could
    not be evaluated". Those must never produce the same outcome.
    """

    rule_id: str
    condition: str
    source: RuleSource
    source_ref: str | None = None
    required_facts: list[str] = Field(default_factory=list)
    explanation_template: str


class RuleResult(BaseModel):
    rule_id: str
    passed: bool | None  # None when a required fact was missing
    detail: str | None = None


class Decision(BaseModel):
    """The verdict for one candidate. Carries every rule that fired, not the first."""

    site_id: str
    outcome: Outcome
    results: list[RuleResult] = Field(default_factory=list)
    scenario_id: str | None = None

    @property
    def failing_rules(self) -> list[str]:
        return [r.rule_id for r in self.results if r.passed is False]

    @property
    def unevaluated_rules(self) -> list[str]:
        return [r.rule_id for r in self.results if r.passed is None]


class AllocationItem(BaseModel):
    site_id: str
    connectors: int = Field(ge=1)
    cost: float = Field(ge=0)
    marginal_relief: float | None = None


class Allocation(BaseModel):
    """The output. Produced by the allocator, re-checked before anyone sees it."""

    scenario_id: str
    budget: float = Field(ge=0)
    requested_connectors: int | None = Field(default=None, ge=0)
    items: list[AllocationItem] = Field(default_factory=list)
    checked: bool = False
    violations: list[str] = Field(default_factory=list)

    @property
    def total_connectors(self) -> int:
        return sum(i.connectors for i in self.items)

    @property
    def total_cost(self) -> float:
        return sum(i.cost for i in self.items)


class InfeasibilityReport(BaseModel):
    """What to return when the request cannot be met. "Infeasible" on its own is useless."""

    scenario_id: str
    requested_connectors: int
    max_feasible: int
    binding_constraints: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
