"""Physical things in the world, and the candidates we might put chargers at."""

from pydantic import BaseModel, Field

from .enums import Provenance, SiteKind
from .spatial import Coordinate


class CarPark(BaseModel):
    """A car park from the static registry, joined to a live availability feed."""

    car_park_id: str
    name: str
    coord: Coordinate
    planning_area: str | None = None
    total_lots: int | None = Field(default=None, ge=0)
    car_park_type: str | None = None
    has_live_feed: bool = False  # 1 in 8 registry entries has none; report, never assume


class Station(BaseModel):
    """A charging location. May hold several connectors."""

    station_id: str
    coord: Coordinate
    operator: str | None = None
    address: str | None = None
    planning_area: str | None = None
    provenance: Provenance = Provenance.OBSERVED


class Connector(BaseModel):
    """One plug. Capacity is counted in connectors, never in stations."""

    connector_id: str
    station_id: str
    plug_type: str | None = None
    power_kw: float | None = Field(default=None, gt=0)
    ever_active: bool = False
    """True once seen AVAILABLE or OCCUPIED. Until then it may be planned or removed,
    so it must not count toward installed capacity."""


class CandidateSite(BaseModel):
    """Somewhere chargers could go. The unit the allocator reasons over."""

    site_id: str
    kind: SiteKind
    coord: Coordinate
    planning_area: str | None = None
    car_park_id: str | None = None
    total_lots: int | None = Field(default=None, ge=0)
    existing_connectors: int = Field(default=0, ge=0)
    provenance: Provenance = Provenance.OBSERVED
