from typing import Any, Literal
from pydantic import BaseModel, Field

from pydantic import BaseModel, Field, ConfigDict


class EnvironmentalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soil_ph: float | None = Field(
        default=None,
        ge=0,
        le=14
    )

    soil_organic_carbon: float | None = Field(
        default=None,
        ge=0
    )

    soil_moisture: float | None = Field(
        default=None,
        ge=0,
        le=100
    )

    rainfall_mm: float | None = Field(
        default=None,
        ge=0
    )

    temperature_c: float | None = None

    land_use: str | None = None
    crop: str | None = None

    species_richness: int | None = Field(
        default=None,
        ge=0
    )

    habitat_diversity: float | None = Field(
        default=None,
        ge=0
    )

    pollution_level: str | None = None
    deforestation_level: str | None = None

    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90
    )

    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180
    )

    region: str | None = None

    
class ChatRequest(BaseModel):
    conversation_id: str = 'default'
    message: str
    environmental: EnvironmentalInput | None = None

class Recommendation(BaseModel):
    recommendation: str
    why_it_works: str
    impacted_metrics: list[str]
    time_horizon: str
    expected_change: str | None = None
    confidence: float
    evidence: list[dict[str, Any]]

class AnalysisResponse(BaseModel):
    detected_variables: dict[str, Any]
    missing_variables: list[str]
    reasoning_chain: list[str]
    recommendations: list[Recommendation]
    retrieved_evidence: list[dict[str, Any]]
