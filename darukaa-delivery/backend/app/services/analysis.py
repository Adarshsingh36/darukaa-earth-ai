"""
Analysis orchestration.

    EnvironmentalInput
        -> ReasoningEngine (derived features + candidate rules)
        -> per-recommendation EvidenceRetriever
        -> per-recommendation confidence estimate
        -> AnalysisResponse

This lives in a service rather than inline in `main.py` so that /chat
and /analyze share exactly one code path, and so the whole pipeline is
testable without an HTTP client.

Degradation policy: a failure in evidence retrieval or live enrichment
never fails the analysis. It is recorded in `data_provenance` and in
the affected recommendation's `evidence_status`, and the deterministic
reasoning result is still returned.
"""

from __future__ import annotations

from app.models.schemas import (
    AnalysisResponse,
    DataProvenance,
    EnvironmentalInput,
    EvidenceItem,
    Recommendation,
)
from app.services.confidence import (
    CONFIDENCE_CAVEAT,
    estimate_confidence,
    observation_confidence_note,
)
from app.services.enrichment import (
    LocationEnrichmentService,
    merge_user_and_live,
)
from app.services.reasoning import ReasoningEngine
from app.services.reference_stats import (
    SUPPORTED_FIELDS,
    reference_dataset,
)
from app.services.retrieval import EvidenceRetriever

#: Variables the assessment needs before it can say anything useful.
REQUIRED_FOR_ANALYSIS = (
    "soil_organic_carbon_g_per_kg",
    "precipitation_mm_day",
    "land_use",
)

#: Additionally requested in conversation before a full assessment.
REQUIRED_FOR_CHAT = REQUIRED_FOR_ANALYSIS + ("region",)

BASE_CAVEATS = [
    "Derived indicators (water stress, soil carbon condition, pH "
    "condition, habitat condition) are prototype reasoning features "
    "computed from fixed thresholds. They are not validated "
    "ecological classifications.",
    "Recommendations describe expected DIRECTION of change. No "
    "quantitative improvement is claimed unless a retrieved source "
    "supports it.",
]


class AnalysisService:
    def __init__(
        self,
        knowledge,
        reasoning: ReasoningEngine | None = None,
        enrichment: LocationEnrichmentService | None = None,
    ):
        self.knowledge = knowledge
        self.reasoning = reasoning or ReasoningEngine()
        self.retriever = EvidenceRetriever(knowledge)
        self.enrichment = enrichment or LocationEnrichmentService()

    # ----------------------------------------------------------------
    async def analyze_location(
        self,
        env: EnvironmentalInput,
        radius_km: float = 10.0,
    ) -> AnalysisResponse:
        """Enrich from coordinates when present, then analyze."""
        enriched, live_context = await self.prepare(env, radius_km)
        return self.analyze(enriched, live_context)

    # ----------------------------------------------------------------
    async def prepare(
        self,
        env: EnvironmentalInput,
        radius_km: float = 10.0,
    ) -> tuple[EnvironmentalInput, dict]:
        """
        Resolve the environmental state a caller should reason over.

        Split out from `analyze_location` so that /chat can decide what
        is still MISSING after live enrichment rather than before it.
        Asking a user for soil carbon that SoilGrids already answered,
        purely because the check ran too early, is a bad conversation.

        If no coordinates were supplied this is a no-op. If enrichment
        fails wholesale, the user's own values are returned unchanged
        and the failure is recorded for `data_provenance`.
        """
        if env.latitude is None or env.longitude is None:
            return env, {}

        try:
            live_context = await self.enrichment.enrich(
                env.latitude, env.longitude, radius_km
            )
        except Exception as exc:  # noqa: BLE001 - never fail analysis
            return env, {
                "succeeded": False,
                "failures": [
                    {
                        "source": "live enrichment",
                        "status": "unavailable",
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }

        merged, merge_notes, effective_sources = merge_user_and_live(
            env.model_dump(exclude_none=True), live_context
        )

        # A live value that the strict schema rejects is a bug in the
        # upstream source, not a reason to lose the assessment.
        try:
            enriched_env = EnvironmentalInput(**merged)
        except Exception as exc:  # noqa: BLE001
            enriched_env = env
            live_context.setdefault("failures", []).append(
                {
                    "source": "live enrichment merge",
                    "status": "rejected",
                    "reason": (
                        "live values failed schema validation: "
                        f"{exc}"
                    ),
                }
            )
            merge_notes = []
            effective_sources = {}

        live_context["merge_notes"] = merge_notes
        live_context["effective_sources"] = effective_sources

        return enriched_env, live_context

    # ----------------------------------------------------------------
    def analyze(
        self,
        env: EnvironmentalInput,
        live_context: dict | None = None,
    ) -> AnalysisResponse:
        live_context = live_context or {}

        observation_effort = live_context.get("observation_effort")
        observed_species = live_context.get("species_observed")
        live_requested = bool(
            env.latitude is not None and env.longitude is not None
        )
        live_succeeded = bool(live_context.get("succeeded"))

        result = self.reasoning.analyze(
            env,
            observation_effort=observation_effort,
            observed_species=observed_species,
        )

        derived = result["derived_features"]
        environment = result["detected_variables"]

        derived["reference_dataset_context"] = (
            self._reference_context(environment)
        )

        recommendations: list[Recommendation] = []
        bibliography: dict[str, EvidenceItem] = {}

        for candidate in result["recommendations"]:
            bundle = self.retriever.retrieve(candidate)

            confidence = estimate_confidence(
                candidate=candidate,
                environment=environment,
                evidence_status=bundle.status,
                top_relevance=bundle.top_relevance,
                independent_sources=bundle.independent_sources,
                live_data_used=live_succeeded,
                live_data_requested=live_requested,
            )

            evidence_items = [
                EvidenceItem(**item) for item in bundle.items
            ]

            for item in evidence_items:
                bibliography.setdefault(item.id, item)

            recommendations.append(
                Recommendation(
                    recommendation=candidate["recommendation"],
                    why_it_works=candidate["why_it_works"],
                    impacted_metrics=candidate["impacted_metrics"],
                    time_horizon=candidate["time_horizon"],
                    expected_change=candidate.get("expected_change"),
                    confidence=confidence.score,
                    confidence_label=confidence.label,
                    confidence_caveat=CONFIDENCE_CAVEAT,
                    confidence_factors=confidence.factors,
                    limiting_factor=confidence.limiting_factor,
                    evidence_status=bundle.status,
                    evidence_note=bundle.message,
                    evidence=evidence_items,
                    rule_id=candidate.get("rule_id"),
                    rule_strength=candidate.get("rule_strength"),
                    supporting_variables=candidate.get(
                        "supporting_variables", []
                    ),
                )
            )

        # Highest-confidence first, so the UI leads with the
        # best-supported action.
        recommendations.sort(
            key=lambda rec: rec.confidence, reverse=True
        )

        missing = [
            field
            for field in REQUIRED_FOR_ANALYSIS
            if getattr(env, field) is None
        ]

        # Effective sources only: a field the user supplied stays
        # attributed to the user even when a live source also offered
        # a value for it.
        field_sources = live_context.get("effective_sources", {})

        provenance = DataProvenance(
            supplied_by_user=sorted(
                key
                for key in environment
                if key not in field_sources
            ),
            retrieved_live=live_context.get("sources", []),
            field_sources=field_sources,
            derived_indicators=sorted(derived.keys()),
            live_enrichment_attempted=live_requested,
            live_enrichment_succeeded=live_succeeded,
            degraded_sources=live_context.get("failures", []),
        )

        caveats = list(BASE_CAVEATS)
        caveats.extend(live_context.get("caveats", []))

        if missing:
            caveats.append(
                "Assessment ran with missing variables ("
                + ", ".join(missing)
                + "), so some reasoning rules could not be evaluated."
            )

        if live_requested and not live_succeeded:
            caveats.append(
                "Coordinates were supplied but live environmental "
                "enrichment was unavailable. The result uses the "
                "supplied values only."
            )

        for failure in live_context.get("failures", []):
            caveats.append(
                f"{failure.get('source')} was unavailable "
                f"({failure.get('reason')}); its variables were not "
                "included."
            )

        if not any(
            rec.evidence_status == "supported"
            for rec in recommendations
        ):
            caveats.append(
                "No recommendation in this assessment is backed by "
                "strongly matching knowledge-base evidence."
            )

        if derived["reference_dataset_context"].get("fields"):
            caveats.append(
                "Percentile positions shown against the reference "
                "dataset describe relative standing among 43 "
                "convenience-sampled locations, not a validated "
                "ecological baseline."
            )

        return AnalysisResponse(
            detected_variables=environment,
            missing_variables=missing,
            derived_features=derived,
            reasoning_chain=result["reasoning_chain"],
            recommendations=recommendations,
            retrieved_evidence=list(bibliography.values()),
            data_provenance=provenance,
            normalization_notes=(
                result.get("normalization_notes", [])
                + live_context.get("merge_notes", [])
            ),
            biodiversity_observation_note=(
                observation_confidence_note(derived)
            ),
            caveats=caveats,
        )

    # ----------------------------------------------------------------
    @staticmethod
    def _reference_context(environment: dict) -> dict:
        """
        Percentile context against the 43-location training dataset,
        for whichever supported fields are present.

        Additive only: this NEVER changes soil_carbon_condition,
        water_stress, etc. Those stay governed by the fixed prototype
        thresholds in feature_engineering.py. See reference_stats.py
        and scripts/threshold_audit.py for why recalibrating the
        thresholds to this sample would be a scientific overreach
        rather than an improvement.
        """
        if not reference_dataset.available:
            return {
                "available": False,
                "reason": (
                    "Reference dataset "
                    f"({reference_dataset.path.name}) could not be "
                    "loaded."
                ),
            }

        context = {"available": True, "fields": {}}

        for field in SUPPORTED_FIELDS:
            value = environment.get(field)
            if value is None:
                continue

            result = reference_dataset.percentile_rank(field, value)
            if result:
                context["fields"][field] = result

        return context
