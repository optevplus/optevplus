"""Geography. Stored as WGS84; PostGIS does the distance and containment work."""

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    lat: float = Field(ge=1.1, le=1.5, description="WGS84 latitude, Singapore bounds")
    lon: float = Field(ge=103.5, le=104.2, description="WGS84 longitude, Singapore bounds")

    model_config = {"frozen": True}


class PlanningArea(BaseModel):
    """One of the 55 URA Master Plan planning areas."""

    code: str
    name: str
    region: str | None = None
