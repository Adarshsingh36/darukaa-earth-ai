from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class EnvironmentalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soil_ph: float | None = Field(
        default=None,
        ge=0,
        le=14
    )

    # Canonical internal unit: g/kg
    soil_organic_carbon_g_per_kg: float | None = Field(
        default=None,
        ge=0
    )

    soil_moisture: float | None = Field(
        default=None,
        ge=0,
        le=100
    )

    # Canonical internal unit: mm/day
    precipitation_mm_day: float | None = Field(
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
    conversation_id: str = "default"
    message: str
    environmental: EnvironmentalInput | None = None


class EvidenceItem(BaseModel):
    """
    A single knowledge-base record attached to a recommendation.

    `id` is addressable via GET /knowledge/{id}, so any citation shown
    in the UI can be opened and checked. Nothing here is generated.
    """

    id: str
    source: str | None = None
    title: str | None = None
    year: str | None = None
    relevance: float | None = None
    distance: float | None = None
    evidence_type: str | None = None
    intervention: str | None = None
    matched_terms: list[str] = Field(default_factory=list)


class ConfidenceFactor(BaseModel):
    """One decomposed contributor to a prototype confidence score."""

    name: str
    value: float
    weight: float
    contribution: float
    detail: str


class Recommendation(BaseModel):
    recommendation: str
    why_it_works: str
    impacted_metrics: list[str]
    time_horizon: str
    expected_change: str | None = None

    # Bounded prototype score. See services/confidence.py. Always
    # rendered together with confidence_label and confidence_caveat so
    # it is never mistaken for a calibrated probability.
    confidence: float
    confidence_label: str = "prototype confidence"
    confidence_caveat: str | None = None
    confidence_factors: list[ConfidenceFactor] = Field(
        default_factory=list
    )
    limiting_factor: str | None = None

    # "supported" | "weak" | "insufficient"
    evidence_status: str = "insufficient"
    evidence_note: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)

    # Provenance of the rule that produced this recommendation.
    rule_id: str | None = None
    rule_strength: str | None = None
    supporting_variables: list[str] = Field(default_factory=list)


class DataProvenance(BaseModel):
    """
    Separates what was MEASURED/RETRIEVED from what was REASONED.

    Required by the brief: the user must be able to tell a SoilGrids
    value apart from a derived indicator apart from a recommendation.
    """

    supplied_by_user: list[str] = Field(default_factory=list)
    retrieved_live: list[dict[str, Any]] = Field(default_factory=list)
    #: canonical field -> the live source that supplied it
    field_sources: dict[str, str] = Field(default_factory=dict)
    derived_indicators: list[str] = Field(default_factory=list)
    live_enrichment_attempted: bool = False
    live_enrichment_succeeded: bool = False
    degraded_sources: list[dict[str, Any]] = Field(
        default_factory=list
    )


class AnalysisResponse(BaseModel):
    detected_variables: dict[str, Any]
    missing_variables: list[str]

    # Derived environmental condition indicators. These are reasoning
    # features under prototype thresholds, NOT ground-truth ecological
    # labels. Previously computed but never returned, which is why the
    # frontend could not display them.
    derived_features: dict[str, Any] = Field(default_factory=dict)

    reasoning_chain: list[str]
    recommendations: list[Recommendation]

    # Union of evidence attached across recommendations, for a
    # whole-analysis bibliography panel.
    retrieved_evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    data_provenance: DataProvenance = Field(
        default_factory=DataProvenance
    )

    # Unit conversions and land-cover mappings that were assumed.
    normalization_notes: list[str] = Field(default_factory=list)

    # Biodiversity observation uncertainty, kept separate from
    # recommendation confidence.
    biodiversity_observation_note: str | None = None

    caveats: list[str] = Field(default_factory=list)