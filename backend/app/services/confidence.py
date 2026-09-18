"""
Prototype confidence estimation.

WHAT THIS IS NOT
----------------
This is NOT a calibrated probability. The system has never been
validated against held-out ecological outcomes, so no number it
produces may be presented as "there is an N% chance this intervention
works". Every score is emitted alongside:

    label   = "prototype confidence"
    caveat  = an explicit statement that the score is uncalibrated

WHAT IT IS
----------
A bounded, decomposed, auditable score. Each contributing factor is
returned with its own value and weight so a reviewer can see exactly
why a recommendation scored what it did. The previous implementation
was a flat 0.55 plus 0.03 per lexical keyword hit, capped at 0.95,
which implied near-certainty on keyword overlap alone.

CEILING
-------
Scores are clamped to [0.15, 0.80]. The ceiling is deliberately below
0.9: a prototype with an 8-record knowledge base and uncalibrated
thresholds has no basis for expressing high confidence in anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_CONFIDENCE = 0.15
MAX_CONFIDENCE = 0.80

CONFIDENCE_LABEL = "prototype confidence"

CONFIDENCE_CAVEAT = (
    "Prototype confidence estimate. This score is not statistically "
    "calibrated against ecological outcomes; it summarises input "
    "completeness, reasoning-rule strength and retrieved-evidence "
    "quality only."
)

#: Core variables whose presence materially improves an assessment.
CORE_VARIABLES = (
    "soil_organic_carbon_g_per_kg",
    "precipitation_mm_day",
    "soil_ph",
    "temperature_c",
    "land_use",
    "region",
)

RULE_STRENGTH_SCORE = {
    "strong": 1.0,
    "moderate": 0.65,
    "weak": 0.35,
}

#: Factor weights. Sum to 1.0.
WEIGHTS = {
    "input_completeness": 0.20,
    "rule_strength": 0.25,
    "supporting_variables": 0.10,
    "evidence_relevance": 0.25,
    "evidence_independence": 0.10,
    "live_data": 0.10,
}


@dataclass
class ConfidenceResult:
    score: float
    label: str = CONFIDENCE_LABEL
    caveat: str = CONFIDENCE_CAVEAT
    factors: list[dict] = field(default_factory=list)
    limiting_factor: str | None = None


def estimate_confidence(
    candidate: dict,
    environment: dict,
    evidence_status: str,
    top_relevance: float,
    independent_sources: int,
    live_data_used: bool = False,
    live_data_requested: bool = False,
) -> ConfidenceResult:
    """
    Compute a decomposed prototype confidence for one recommendation.

    Parameters map one-to-one onto the factors listed in the project
    brief, so each can be inspected and argued with independently.
    """
    factors: list[dict] = []

    # --- 1. quality/completeness of environmental input -------------
    present = sum(
        1
        for name in CORE_VARIABLES
        if environment.get(name) is not None
    )
    input_completeness = present / len(CORE_VARIABLES)

    factors.append(
        _factor(
            "input_completeness",
            input_completeness,
            f"{present} of {len(CORE_VARIABLES)} core environmental "
            "variables were supplied.",
        )
    )

    # --- 2. strength of the deterministic reasoning rule ------------
    rule_strength = RULE_STRENGTH_SCORE.get(
        candidate.get("rule_strength", "moderate"), 0.65
    )

    factors.append(
        _factor(
            "rule_strength",
            rule_strength,
            "Rule "
            f"{candidate.get('rule_id', 'unknown')} is classified as "
            f"{candidate.get('rule_strength', 'moderate')} strength.",
        )
    )

    # --- 3. number of independent variables behind the rule ---------
    supporting = [
        name
        for name in candidate.get("supporting_variables", [])
        if environment.get(name) is not None
    ]
    supporting_score = min(1.0, len(supporting) / 2.0)

    factors.append(
        _factor(
            "supporting_variables",
            supporting_score,
            f"{len(supporting)} measured variable(s) support this "
            "recommendation: "
            + (", ".join(supporting) or "none"),
        )
    )

    # --- 4. quality of retrieved evidence ---------------------------
    if evidence_status == "insufficient":
        evidence_relevance = 0.0
        evidence_detail = (
            "No knowledge-base record cleared the relevance "
            "threshold."
        )
    else:
        evidence_relevance = max(0.0, min(1.0, top_relevance))
        evidence_detail = (
            f"Best retrieved evidence scored {top_relevance:.2f} "
            f"relevance ({evidence_status})."
        )

    factors.append(
        _factor(
            "evidence_relevance",
            evidence_relevance,
            evidence_detail,
        )
    )

    # --- 5. independent supporting sources --------------------------
    independence = min(1.0, independent_sources / 2.0)

    factors.append(
        _factor(
            "evidence_independence",
            independence,
            f"{independent_sources} distinct source organisation(s) "
            "among the attached evidence.",
        )
    )

    # --- 6. live geospatial data ------------------------------------
    if live_data_used:
        live_score = 1.0
        live_detail = (
            "Live geospatial enrichment succeeded and informed the "
            "environmental state."
        )
    elif live_data_requested:
        live_score = 0.2
        live_detail = (
            "Coordinates were supplied but live enrichment failed or "
            "returned nothing; the assessment used the supplied "
            "values only."
        )
    else:
        # Neutral: no coordinates were offered, so absence of live
        # data is not evidence of a worse assessment.
        live_score = 0.5
        live_detail = (
            "No coordinates were supplied, so no live geospatial "
            "enrichment was attempted."
        )

    factors.append(_factor("live_data", live_score, live_detail))

    # --- blend -------------------------------------------------------
    raw = sum(
        WEIGHTS[factor["name"]] * factor["value"]
        for factor in factors
    )

    score = round(
        max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, raw)),
        2,
    )

    limiting = min(
        factors,
        key=lambda factor: factor["value"],
    )

    return ConfidenceResult(
        score=score,
        factors=factors,
        limiting_factor=limiting["detail"],
    )


def observation_confidence_note(derived: dict) -> str | None:
    """
    Describe GBIF observation confidence SEPARATELY from recommendation
    confidence.

    These are different quantities and conflating them would let
    sampling effort inflate the apparent reliability of an
    intervention, or vice versa.
    """
    signal = derived.get("biodiversity_observation_signal")
    evidence = derived.get("biodiversity_evidence_confidence")

    if signal in (None, "unknown") and evidence in (None, "unknown"):
        return (
            "No biodiversity observation records were available, so "
            "no observed-diversity signal is reported. This is an "
            "absence of sampling, not an absence of biodiversity."
        )

    if signal == "no_observation":
        return (
            "Zero occurrence records were returned for this area. "
            "GBIF records reflect where people have surveyed and "
            "uploaded data; zero records means no recorded sampling, "
            "NOT zero biodiversity."
        )

    if evidence in {"low", "none"}:
        return (
            "Observation effort in this area is low, so the observed "
            "diversity signal is weakly constrained and likely "
            "underestimates true richness."
        )

    return (
        "Observed-diversity signal is derived from occurrence records "
        "and sampling effort. It is an observation proxy, not a "
        "complete species inventory."
    )


def _factor(name: str, value: float, detail: str) -> dict:
    return {
        "name": name,
        "value": round(float(value), 3),
        "weight": WEIGHTS[name],
        "contribution": round(WEIGHTS[name] * float(value), 3),
        "detail": detail,
    }
