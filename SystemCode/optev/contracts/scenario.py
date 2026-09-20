"""Scenarios. Planned capacity enters here, never into the observed layer."""

from pydantic import BaseModel, Field

from .enums import Provenance


class PlannedCapacity(BaseModel):
    """A planner's selection. Reversible, because nothing observed is overwritten."""

    site_id: str
    connectors: int = Field(ge=1)
    selected_by: str | None = None
    provenance: Provenance = Provenance.PLANNED


class Scenario(BaseModel):
    scenario_id: str
    seed: int = 0
    growth_multiplier: float = Field(default=1.0, gt=0)
    horizon_months: int = Field(default=18, ge=1)
    baseline_window: str | None = None
    planned: list[PlannedCapacity] = Field(default_factory=list)
    provenance: Provenance = Provenance.SIMULATED
