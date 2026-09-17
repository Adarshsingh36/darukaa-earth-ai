from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=10.0, gt=0, le=50)


class LocationResponse(BaseModel):
    location: dict[str, float]
    climate: dict[str, Any]
    biodiversity: dict[str, Any]
    data_sources: list[dict[str, Any]]
