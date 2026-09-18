from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=10.0, gt=0, le=50)


class LocationResponse(BaseModel):
    """
    Live environmental context for a point.

    Every source block may be empty: a partial result is a valid
    result. `degraded_sources` says which sources did not answer and
    why, and `field_sources` records which source supplied each
    canonical value so measured data stays distinguishable from
    reasoned output.
    """

    location: dict[str, float]

    climate: dict[str, Any] = Field(default_factory=dict)
    soil: dict[str, Any] = Field(default_factory=dict)
    land_cover: dict[str, Any] = Field(default_factory=dict)
    biodiversity: dict[str, Any] = Field(default_factory=dict)

    canonical_values: dict[str, Any] = Field(default_factory=dict)
    field_sources: dict[str, str] = Field(default_factory=dict)

    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    degraded_sources: list[dict[str, Any]] = Field(
        default_factory=list
    )
    partial: bool = False
