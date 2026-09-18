"""
Unit and component tests: schema, units, parsing, memory, features,
reasoning, retrieval, confidence.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import EnvironmentalInput
from app.services import units as U
from app.services.chat import ChatParser, ConversationMemory
from app.services.confidence import (
    MAX_CONFIDENCE,
    MIN_CONFIDENCE,
    estimate_confidence,
    observation_confidence_note,
)
from app.services.feature_engineering import (
    EnvironmentalFeatureEngineer,
)
from app.services.land_cover import normalize_land_use
from app.services.reasoning import ReasoningEngine
from app.services.retrieval import EvidenceRetriever


# =====================================================================
# A. Schema validation
# =====================================================================
class TestSchema:
    def test_rejects_unknown_field(self):
        # extra="forbid" is what keeps ambiguous legacy names such as
        # `soil_organic_carbon` out of the internal model.
        with pytest.raises(ValidationError):
            EnvironmentalInput(soil_organic_carbon=5.8)

    def test_rejects_out_of_range_ph(self):
        with pytest.raises(ValidationError):
            EnvironmentalInput(soil_ph=15.2)

    def test_rejects_negative_precipitation(self):
        with pytest.raises(ValidationError):
            EnvironmentalInput(precipitation_mm_day=-1)

    def test_rejects_out_of_range_coordinates(self):
        with pytest.raises(ValidationError):
            EnvironmentalInput(latitude=120.0)

    def test_all_fields_optional(self):
        assert EnvironmentalInput().model_dump(exclude_none=True) == {}


# =====================================================================
# B. Unit conversion
# =====================================================================
class TestUnits:
    def test_soc_percent_to_g_per_kg(self):
        assert U.soc_to_g_per_kg(0.58, "%") == 5.8

    def test_soc_g_per_kg_passthrough(self):
        assert U.soc_to_g_per_kg(5.8, "g/kg") == 5.8

    def test_soc_percent_spelled_out(self):
        assert U.soc_to_g_per_kg(1.0, "percent") == 10.0

    def test_annual_rainfall_to_mm_day(self):
        assert round(U.rainfall_to_mm_day(600, "mm/year"), 4) == 1.6438

    def test_mm_day_passthrough(self):
        assert U.rainfall_to_mm_day(1.2, "mm/day") == 1.2

    def test_bare_mm_is_rejected_as_ambiguous(self):
        with pytest.raises(U.UnitConversionError):
            U.rainfall_to_mm_day(600, "mm")

    def test_infer_rainfall_unit_treats_large_values_as_annual(self):
        assert U.infer_rainfall_unit(600, None) == "mm/year"
        assert U.infer_rainfall_unit(1.2, None) == "mm/day"

    def test_external_aliases_normalized_immediately(self):
        canonical, notes = U.normalize_external_payload(
            {"soil_organic_carbon": 5.8, "rainfall_mm": 600}
        )

        assert canonical["soil_organic_carbon_g_per_kg"] == 5.8
        assert round(canonical["precipitation_mm_day"], 4) == 1.6438
        assert "soil_organic_carbon" not in canonical
        assert "rainfall_mm" not in canonical
        assert notes  # the conversion was reported, not silent

        # And the result is accepted by the strict schema.
        EnvironmentalInput(**canonical)


# =====================================================================
# C. Chat parsing
# =====================================================================
class TestChatParser:
    parser = ChatParser()

    def test_demo_sentence(self):
        result = self.parser.parse(
            "My SOC is 0.58%, annual rainfall is 600 mm, pH is 5.4 "
            "and this is wheat monoculture."
        )

        assert result.values["soil_organic_carbon_g_per_kg"] == 5.8
        assert round(
            result.values["precipitation_mm_day"], 4
        ) == 1.6438
        assert result.values["soil_ph"] == 5.4
        assert result.values["land_use"] == "wheat monoculture"
        assert result.values["crop"] == "wheat"

    def test_value_before_keyword_ordering(self):
        # The previous parser only matched keyword-then-value and
        # silently dropped both of these.
        result = self.parser.parse(
            "0.58% SOC and 600 mm annual rainfall"
        )

        assert result.values["soil_organic_carbon_g_per_kg"] == 5.8
        assert round(
            result.values["precipitation_mm_day"], 4
        ) == 1.6438

    def test_explicit_mm_per_day_not_treated_as_annual(self):
        result = self.parser.parse("rainfall 1.2 mm/day")
        assert result.values["precipitation_mm_day"] == 1.2

    def test_land_use_phrase_is_bounded(self):
        # Regression: the old `[a-z\s-]{1,40}?` pattern captured
        # "and this is wheat monoculture".
        result = self.parser.parse(
            "pH is 5.4 and this is wheat monoculture"
        )
        assert result.values["land_use"] == "wheat monoculture"

    def test_ph_not_matched_inside_other_words(self):
        result = self.parser.parse(
            "phosphorus is 12 and the graph is flat"
        )
        assert "soil_ph" not in result.values

    def test_region_longest_match_wins(self):
        assert (
            self.parser.parse("it is semi-arid").values["region"]
            == "semi-arid"
        )
        assert (
            self.parser.parse("subtropical zone").values["region"]
            == "subtropical"
        )

    def test_conversion_is_reported(self):
        result = self.parser.parse("SOC 0.58%, annual rainfall 600 mm")
        assert any("g/kg" in note for note in result.notes)
        assert any("mm/day" in note for note in result.notes)

    def test_empty_message(self):
        assert not self.parser.parse("")

    def test_no_environmental_content(self):
        assert not self.parser.parse("what should I change?")


# =====================================================================
# D. Conversation memory
# =====================================================================
class TestConversationMemory:
    def test_accumulates_across_turns(self):
        memory = ConversationMemory()
        parser = ChatParser()

        first = parser.parse(
            "SOC is 0.58%, annual rainfall 600 mm, pH 5.4, "
            "wheat monoculture"
        )
        memory.update("c1", first.values, first.notes)

        second = parser.parse("it is semi-arid")
        memory.update("c1", second.values, second.notes)

        environment = memory.get("c1")["environment"]

        # The second turn must not erase the first.
        assert environment["soil_organic_carbon_g_per_kg"] == 5.8
        assert environment["soil_ph"] == 5.4
        assert environment["land_use"] == "wheat monoculture"
        assert environment["region"] == "semi-arid"

    def test_sessions_are_isolated(self):
        memory = ConversationMemory()
        memory.update("a", {"soil_ph": 5.0})
        memory.update("b", {"soil_ph": 7.0})

        assert memory.get("a")["environment"]["soil_ph"] == 5.0
        assert memory.get("b")["environment"]["soil_ph"] == 7.0

    def test_reset(self):
        memory = ConversationMemory()
        memory.update("a", {"soil_ph": 5.0})
        memory.reset("a")
        assert memory.get("a")["environment"] == {}


# =====================================================================
# E. Land cover + feature engineering
# =====================================================================
class TestLandCover:
    def test_free_text_maps_to_canonical_class(self):
        assert (
            normalize_land_use("wheat monoculture")[
                "land_cover_class"
            ]
            == "cropland"
        )

    def test_agroforestry_beats_forest(self):
        assert (
            normalize_land_use("agroforestry system")[
                "land_cover_class"
            ]
            == "agroforestry"
        )

    def test_management_intensity_detected(self):
        assert (
            normalize_land_use("wheat monoculture")[
                "management_intensity"
            ]
            == "monoculture"
        )

    def test_unrecognised_stays_none(self):
        # Guessing here would drive recommendations off a wrong class.
        assert (
            normalize_land_use("something unusual")[
                "land_cover_class"
            ]
            is None
        )


class TestFeatureEngineering:
    engineer = EnvironmentalFeatureEngineer()

    def test_demo_conditions(self):
        derived = self.engineer.transform(
            {
                "soil_organic_carbon_g_per_kg": 5.8,
                "precipitation_mm_day": 1.6438,
                "soil_ph": 5.4,
                "temperature_c": 26.0,
                "land_cover_label": "cropland",
            }
        )

        assert derived["soil_carbon_condition"] == "moderate_stress"
        assert derived["water_stress"] == "moderate"
        assert derived["soil_ph_condition"] == "high_stress"
        assert derived["thermal_stress"] == "low"
        assert derived["habitat_condition"] == "reduced"
        assert derived["land_cover_pressure"] == "moderate"

    def test_missing_values_yield_unknown_not_zero(self):
        derived = self.engineer.transform({})

        assert derived["water_stress"] == "unknown"
        assert derived["soil_carbon_condition"] == "unknown"
        assert derived["habitat_condition"] == "unknown"

    def test_zero_gbif_observations_is_not_zero_biodiversity(self):
        derived = self.engineer.transform(
            {"gbif_species_observed": 0, "gbif_observation_effort": 0}
        )

        assert derived["biodiversity_observation_signal"] == (
            "no_observation"
        )
        assert derived["biodiversity_evidence_confidence"] == "none"

        note = observation_confidence_note(derived)
        assert "NOT zero biodiversity" in note


# =====================================================================
# F/G. Multi-variable reasoning and recommendation generation
# =====================================================================
class TestReasoning:
    engine = ReasoningEngine()

    def test_demo_scenario_fires_multiple_rules(self, demo_environment):
        result = self.engine.analyze(demo_environment)

        rule_ids = {
            candidate["rule_id"]
            for candidate in result["recommendations"]
        }

        # Soil carbon x water, soil carbon x agriculture, monoculture,
        # habitat, pH, and water x habitat should all be reachable.
        assert "R1_soil_carbon_water" in rule_ids
        assert "R2_soil_carbon_agriculture" in rule_ids
        assert "R4_habitat_structure" in rule_ids
        assert "R5_soil_ph" in rule_ids
        assert "R6_water_habitat" in rule_ids

    def test_free_text_land_use_reaches_habitat_rules(self):
        """
        Regression: "wheat monoculture" did not match the land-cover
        vocabulary, so habitat_condition stayed "unknown" and the
        habitat rules never fired for the headline demo scenario.
        """
        env = EnvironmentalInput(
            soil_organic_carbon_g_per_kg=5.8,
            precipitation_mm_day=1.6438,
            land_use="wheat monoculture",
        )

        result = self.engine.analyze(env)

        assert result["derived_features"]["land_cover_class"] == (
            "cropland"
        )
        assert result["derived_features"]["habitat_condition"] == (
            "reduced"
        )

    def test_reasoning_chain_describes_interactions(
        self, demo_environment
    ):
        chain = " ".join(self.engine.analyze(demo_environment)[
            "reasoning_chain"
        ])

        # Not merely a list of variables.
        assert "Causal chain" in chain
        assert "->" in chain

    def test_every_candidate_carries_retrieval_metadata(
        self, demo_environment
    ):
        for candidate in self.engine.analyze(demo_environment)[
            "recommendations"
        ]:
            assert candidate["retrieval_terms"]
            assert candidate["rule_id"]
            assert candidate["rule_strength"] in {
                "strong",
                "moderate",
                "weak",
            }

    def test_no_quantitative_effect_claims(self, demo_environment):
        """Scientific honesty: no invented improvement percentages."""
        import re

        for candidate in self.engine.analyze(demo_environment)[
            "recommendations"
        ]:
            text = (
                candidate["expected_change"] or ""
            ) + candidate["why_it_works"]

            assert not re.search(r"\d+\s*%", text)
            assert "Expected direction" in (
                candidate["expected_change"] or ""
            )

    def test_benign_conditions_produce_no_false_alarm(self):
        env = EnvironmentalInput(
            soil_organic_carbon_g_per_kg=25.0,
            precipitation_mm_day=4.5,
            soil_ph=6.8,
            temperature_c=20.0,
            land_use="tropical forest",
        )

        result = self.engine.analyze(env)

        assert result["recommendations"] == []
        assert "No high-priority" in result["reasoning_chain"][0]


# =====================================================================
# H. Recommendation-specific retrieval
# =====================================================================
class TestRetrieval:
    engine = ReasoningEngine()

    def _candidates(self, env):
        return {
            candidate["rule_id"]: candidate
            for candidate in self.engine.analyze(env)[
                "recommendations"
            ]
        }

    def test_query_is_recommendation_specific(
        self, knowledge, demo_environment
    ):
        retriever = EvidenceRetriever(knowledge)
        candidates = self._candidates(demo_environment)

        ph_query = retriever.build_query(candidates["R5_soil_ph"])
        habitat_query = retriever.build_query(
            candidates["R4_habitat_structure"]
        )

        assert ph_query != habitat_query
        assert "pH" in ph_query or "acidity" in ph_query
        assert "native vegetation" in habitat_query

    def test_different_recommendations_get_different_evidence(
        self, knowledge, demo_environment
    ):
        retriever = EvidenceRetriever(knowledge)
        candidates = self._candidates(demo_environment)

        bundles = {
            rule_id: retriever.retrieve(candidate)
            for rule_id, candidate in candidates.items()
        }

        id_sets = [
            tuple(item["id"] for item in bundle.items)
            for bundle in bundles.values()
            if bundle.items
        ]

        # The old implementation attached the same global top-5 pool to
        # every recommendation, so all of these were identical.
        assert len(set(id_sets)) > 1

    def test_irrelevant_evidence_is_not_attached(self, knowledge):
        retriever = EvidenceRetriever(knowledge)

        nonsense = {
            "rule_id": "X",
            "recommendation": "Recalibrate the orbital telescope.",
            "retrieval_terms": [
                "telescope calibration",
                "orbital optics",
            ],
            "impacted_metrics": ["focal length"],
        }

        bundle = retriever.retrieve(nonsense)

        assert bundle.status == "insufficient"
        assert bundle.items == []
        assert "threshold" in bundle.message

    def test_retrieval_failure_degrades_gracefully(
        self, broken_knowledge, demo_environment
    ):
        retriever = EvidenceRetriever(broken_knowledge)
        candidates = self._candidates(demo_environment)

        bundle = retriever.retrieve(candidates["R5_soil_ph"])

        assert bundle.status == "insufficient"
        assert "unavailable" in bundle.message

    def test_attached_evidence_ids_are_resolvable(
        self, knowledge, demo_environment
    ):
        """No fabricated citations: every id resolves to a record."""
        retriever = EvidenceRetriever(knowledge)

        for candidate in self.engine.analyze(demo_environment)[
            "recommendations"
        ]:
            for item in retriever.retrieve(candidate).items:
                assert knowledge.get_by_id(item["id"]) is not None


# =====================================================================
# I. Confidence
# =====================================================================
class TestConfidence:
    def _candidate(self, strength="strong"):
        return {
            "rule_id": "R1_soil_carbon_water",
            "rule_strength": strength,
            "supporting_variables": [
                "soil_organic_carbon_g_per_kg",
                "precipitation_mm_day",
            ],
        }

    def _environment(self):
        return {
            "soil_organic_carbon_g_per_kg": 5.8,
            "precipitation_mm_day": 1.64,
            "soil_ph": 5.4,
            "temperature_c": 26.0,
            "land_use": "wheat monoculture",
            "region": "semi-arid",
        }

    def test_bounded(self):
        best = estimate_confidence(
            self._candidate(),
            self._environment(),
            "supported",
            1.0,
            5,
            live_data_used=True,
        )

        worst = estimate_confidence(
            {"rule_id": "X", "rule_strength": "weak"},
            {},
            "insufficient",
            0.0,
            0,
        )

        assert best.score <= MAX_CONFIDENCE
        assert worst.score >= MIN_CONFIDENCE
        assert best.score > worst.score

    def test_never_claims_certainty(self):
        result = estimate_confidence(
            self._candidate(),
            self._environment(),
            "supported",
            1.0,
            5,
            live_data_used=True,
        )

        assert result.score < 0.9
        assert result.label == "prototype confidence"
        assert "not statistically calibrated" in result.caveat

    def test_factors_are_decomposed_and_weighted(self):
        result = estimate_confidence(
            self._candidate(),
            self._environment(),
            "supported",
            0.7,
            2,
        )

        names = {factor["name"] for factor in result.factors}

        assert names == {
            "input_completeness",
            "rule_strength",
            "supporting_variables",
            "evidence_relevance",
            "evidence_independence",
            "live_data",
        }

        assert round(
            sum(factor["weight"] for factor in result.factors), 6
        ) == 1.0
        assert result.limiting_factor

    def test_missing_evidence_lowers_confidence(self):
        with_evidence = estimate_confidence(
            self._candidate(),
            self._environment(),
            "supported",
            0.8,
            2,
        )
        without = estimate_confidence(
            self._candidate(),
            self._environment(),
            "insufficient",
            0.0,
            0,
        )

        assert without.score < with_evidence.score

    def test_sparse_input_lowers_confidence(self):
        full = estimate_confidence(
            self._candidate(),
            self._environment(),
            "supported",
            0.8,
            2,
        )
        sparse = estimate_confidence(
            self._candidate(),
            {"soil_organic_carbon_g_per_kg": 5.8},
            "supported",
            0.8,
            2,
        )

        assert sparse.score < full.score

    def test_observation_confidence_is_separate_from_recommendation(
        self,
    ):
        # A biodiversity-observation caveat must not be produced by the
        # recommendation confidence path, and vice versa.
        note = observation_confidence_note(
            {
                "biodiversity_observation_signal": "no_observation",
                "biodiversity_evidence_confidence": "none",
            }
        )

        assert "sampling" in note
        assert "prototype confidence" not in note


# =====================================================================
# Knowledge base attribution
# =====================================================================
class TestKnowledgeBaseAttribution:
    """
    KB-009/010/011 were added specifically to close retrieval gaps: the
    monoculture-diversification, water+habitat, and thermal-stress
    rules previously had no on-topic evidence in the corpus and
    inherited whatever the lexical/vector overlap turned up. These
    pin each one to its target rule so a later edit to knowledge.json
    can't silently drop the fix.
    """

    engine = ReasoningEngine()

    def test_monoculture_rule_is_topped_by_its_dedicated_record(
        self, knowledge
    ):
        from app.services.retrieval import EvidenceRetriever

        env = EnvironmentalInput(
            land_use="wheat monoculture", crop="wheat"
        )
        candidates = {
            c["rule_id"]: c
            for c in self.engine.analyze(env)["recommendations"]
        }

        bundle = EvidenceRetriever(knowledge).retrieve(
            candidates["R3_monoculture_diversification"]
        )

        assert bundle.items[0]["id"] == "KB-009"

    def test_thermal_rule_is_topped_by_its_dedicated_record(
        self, knowledge
    ):
        from app.services.retrieval import EvidenceRetriever

        env = EnvironmentalInput(
            temperature_c=39.0, land_use="grassland"
        )
        candidates = {
            c["rule_id"]: c
            for c in self.engine.analyze(env)["recommendations"]
        }

        bundle = EvidenceRetriever(knowledge).retrieve(
            candidates["R7_thermal"]
        )

        assert bundle.items[0]["id"] == "KB-011"

    def test_new_records_are_individually_attributed(self, knowledge):
        for kb_id in ("KB-009", "KB-010", "KB-011"):
            record = knowledge.get_by_id(kb_id)
            assert record is not None
            assert record["year"] >= 2019
            # A specific, checkable title, not a generic summary label
            # like the earlier prototype-style records.
            assert len(record["title"]) > 10


# =====================================================================
# Reference dataset context (environment_training_final.csv)
# =====================================================================
class TestReferenceDataset:
    def test_loads_real_dataset(self):
        from app.services.reference_stats import reference_dataset

        assert reference_dataset.available
        assert reference_dataset.sample_size(
            "soil_organic_carbon_g_per_kg"
        ) == 43

    def test_percentile_rank_on_known_small_sample(self):
        from app.services.reference_stats import ReferenceDataset

        dataset = ReferenceDataset.__new__(ReferenceDataset)
        dataset.path = None
        dataset._error = None
        dataset._sorted = {"soil_ph": [5.0, 6.0, 6.0, 7.0, 8.0]}

        # Exact match with ties lands at the tie range's midpoint:
        # one value (5.0) sits strictly below, two ties at 6.0 occupy
        # ranks [1, 3) of 5 -> rank 2.0 -> 40th percentile.
        result = dataset.percentile_rank("soil_ph", 6.0)
        assert result["percentile"] == 40.0
        assert result["reference_n"] == 5

        # Below the minimum sits at the 0th percentile.
        assert dataset.percentile_rank("soil_ph", 4.0)[
            "percentile"
        ] == 0.0

    def test_unsupported_field_returns_none(self):
        from app.services.reference_stats import reference_dataset

        assert (
            reference_dataset.percentile_rank(
                "not_a_real_field", 1.0
            )
            is None
        )

    def test_missing_file_degrades_not_raises(self):
        from pathlib import Path

        from app.services.reference_stats import ReferenceDataset

        dataset = ReferenceDataset(Path("/nonexistent/file.csv"))

        assert dataset.available is False
        assert dataset.describe("soil_ph") is None
        assert dataset.percentile_rank("soil_ph", 6.0) is None

    def test_note_states_the_sampling_caveat(self):
        from app.services.reference_stats import reference_dataset

        result = reference_dataset.percentile_rank(
            "soil_organic_carbon_g_per_kg", 5.8
        )

        assert "convenience sample" in result["note"]
        assert "not itself a stress classification" in result["note"]


class TestReferenceContextInAnalysis:
    def test_attached_to_derived_features_without_changing_thresholds(
        self, analysis_service, demo_environment
    ):
        result = analysis_service.analyze(demo_environment)
        context = result.derived_features[
            "reference_dataset_context"
        ]

        assert context["available"] is True
        assert "soil_organic_carbon_g_per_kg" in context["fields"]

        # The threshold-based classification is untouched by the
        # reference dataset being present.
        assert (
            result.derived_features["soil_carbon_condition"]
            == "moderate_stress"
        )

    def test_absent_fields_are_simply_omitted(self, analysis_service):
        from app.models.schemas import EnvironmentalInput

        result = analysis_service.analyze(EnvironmentalInput())
        context = result.derived_features[
            "reference_dataset_context"
        ]

        assert context["available"] is True
        assert context["fields"] == {}

    def test_caveat_present_only_when_context_was_used(
        self, analysis_service, demo_environment
    ):
        with_context = analysis_service.analyze(demo_environment)
        assert any(
            "convenience-sampled" in caveat
            for caveat in with_context.caveats
        )

        from app.models.schemas import EnvironmentalInput

        without_context = analysis_service.analyze(
            EnvironmentalInput()
        )
        assert not any(
            "convenience-sampled" in caveat
            for caveat in without_context.caveats
        )


class TestAllKnowledgeBaseCitationsAreSpecific(object):
    """
    Every record must name a specific, checkable source — not just an
    organisation and a year. This pins the citation rewrite so a future
    edit to knowledge.json can't quietly regress to placeholder
    attribution.
    """

    PLACEHOLDER_SOURCES = {"FAO 2022", "IPCC 2022", "IPBES 2019"}

    def test_no_record_has_only_org_and_year_as_title(self, knowledge):
        import json

        from tests.conftest import KNOWLEDGE_JSON

        records = json.loads(
            KNOWLEDGE_JSON.read_text(encoding="utf-8-sig")
        )

        assert len(records) >= 11

        for record in records:
            # A specific report/paper title, long enough to be more
            # than a one-line topic label, and an "evidence" field
            # that actually names the source in prose (not just
            # restating source/year).
            assert len(record["evidence"]) > 80
            assert record["source"] not in ("FAO", "IPCC", "IPBES") or (
                # FAO/IPCC/IPBES alone is fine in `source` as long as
                # the specific report is named in the evidence text.
                record["title"] and len(record["title"]) > 15
            )
