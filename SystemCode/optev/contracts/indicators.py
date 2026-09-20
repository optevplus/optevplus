"""Derived measures and demand estimates.

`utilisation` is None whenever supply_state is NO_SUPPLY or UNOBSERVED. Storing 0
instead would sort those sites to the bottom of a ranking as though nobody wanted to
charge there, which is the failure this project exists to avoid.
"""

from pydantic import BaseModel, Field, model_validator

from .enums import EstimateKind, SupplyState


class SiteIndicators(BaseModel):
    site_id: str
    window_start: str
    window_end: str
    supply_state: SupplyState
    active_connectors: int = Field(default=0, ge=0)
    utilisation: float | None = Field(default=None, ge=0, le=1)
    saturated_fraction: float | None = Field(default=None, ge=0, le=1)
    dwell_opportunity: float | None = Field(default=None, ge=0)
    observation_coverage: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def _utilisation_undefined_without_supply(self) -> "SiteIndicators":
        undefined = {SupplyState.NO_SUPPLY, SupplyState.UNOBSERVED}
        if self.supply_state in undefined and self.utilisation is not None:
            raise ValueError(f"utilisation must be None when supply_state is {self.supply_state}")
        return self


class DemandEstimate(BaseModel):
    """Arrivals per hour. A rate, because the allocation needs a rate, not a level."""

    site_id: str
    time_bin: str
    arrivals_per_hour: float = Field(ge=0)
    kind: EstimateKind
    note: str | None = None
