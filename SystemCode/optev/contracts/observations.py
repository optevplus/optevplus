"""Raw readings. Two timestamps on every one, because staleness cannot be
reconstructed after the fact."""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import ConnectorStatus


class _Reading(BaseModel):
    provider_ts: datetime | None = Field(
        default=None, description="When the source says it was updated. May be stale or absent."
    )
    collected_ts: datetime = Field(description="When we fetched it. Always present.")

    @property
    def staleness_seconds(self) -> float | None:
        if self.provider_ts is None:
            return None
        return (self.collected_ts - self.provider_ts).total_seconds()


class CarParkReading(_Reading):
    car_park_id: str
    lots_available: int = Field(ge=0)
    total_lots: int | None = Field(default=None, ge=0)
    lot_type: str = "C"  # filter to cars; the feed also carries H, Y and undocumented values


class ConnectorReading(_Reading):
    connector_id: str
    status: ConnectorStatus
