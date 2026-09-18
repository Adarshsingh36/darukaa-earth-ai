"""
API-level and end-to-end integration tests.

The live `KnowledgeService` needs ChromaDB and a sentence-transformer
download, so these tests swap in `StubKnowledgeService`, which honours
the same contract. The pipeline under test is otherwise the real one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as app_module
from app.services.analysis import AnalysisService
from tests.conftest import StubKnowledgeService


@pytest.fixture
def client(monkeypatch):
    stub = StubKnowledgeService()

    monkeypatch.setattr(app_module, "knowledge", stub)
    monkeypatch.setattr(
        app_module,
        "analysis",
        AnalysisService(stub, app_module.reasoning),
    )

    app_module.memory.sessions.clear()

    return TestClient(app_module.app)


# =====================================================================
class TestHealth:
    def test_health(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["knowledge_documents"] > 0


# =====================================================================
class TestKnowledgeEndpoints:
    def test_search(self, client):
        response = client.post(
            "/knowledge/search",
            json={"query": "soil organic carbon cover crops"},
        )

        assert response.status_code == 200
        assert response.json()["results"]

    def test_empty_query_rejected(self, client):
        assert (
            client.post("/knowledge/search", json={}).status_code
            == 422
        )

    def test_get_by_id(self, client):
        """
        Regression: main.py called knowledge.get_by_id(), which did not
        exist on KnowledgeService, so this endpoint returned 500 for
        every request and no citation could be checked.
        """
        response = client.get("/knowledge/KB-001")

        assert response.status_code == 200
        assert response.json()["id"] == "KB-001"
        assert response.json()["source"]

    def test_unknown_id_is_404_not_500(self, client):
        assert client.get("/knowledge/KB-999").status_code == 404


# =====================================================================
class TestNormalize:
    def test_legacy_payload_normalized(self, client):
        response = client.post(
            "/normalize",
            json={"soil_organic_carbon": 5.8, "rainfall_mm": 600},
        )

        body = response.json()

        assert response.status_code == 200
        assert body["canonical"]["soil_organic_carbon_g_per_kg"] == 5.8
        assert (
            round(body["canonical"]["precipitation_mm_day"], 4)
            == 1.6438
        )
        assert body["conversion_notes"]


# =====================================================================
class TestAnalyze:
    DEMO = {
        "soil_organic_carbon_g_per_kg": 5.8,
        "precipitation_mm_day": 1.6438,
        "soil_ph": 5.4,
        "temperature_c": 26.0,
        "land_use": "wheat monoculture",
        "crop": "wheat",
        "region": "semi-arid",
    }

    def test_demo_scenario(self, client):
        response = client.post("/analyze", json=self.DEMO)

        assert response.status_code == 200
        body = response.json()

        assert len(body["recommendations"]) >= 4
        assert body["reasoning_chain"]
        assert body["missing_variables"] == []

    def test_derived_features_are_returned(self, client):
        """
        Regression: derived features were computed but absent from
        AnalysisResponse, so the frontend could not display water
        stress, soil carbon condition, pH condition or habitat
        condition at all.
        """
        body = client.post("/analyze", json=self.DEMO).json()
        derived = body["derived_features"]

        for key in (
            "water_stress",
            "thermal_stress",
            "soil_carbon_condition",
            "soil_ph_condition",
            "land_cover_pressure",
            "habitat_condition",
            "biodiversity_evidence_confidence",
        ):
            assert key in derived

    def test_every_recommendation_is_fully_specified(self, client):
        body = client.post("/analyze", json=self.DEMO).json()

        for rec in body["recommendations"]:
            assert rec["recommendation"]
            assert rec["why_it_works"]
            assert rec["impacted_metrics"]
            assert rec["time_horizon"]
            assert rec["expected_change"]
            assert 0 < rec["confidence"] <= 0.80
            assert rec["confidence_label"] == "prototype confidence"
            assert rec["confidence_caveat"]
            assert rec["confidence_factors"]
            assert rec["evidence_status"] in {
                "supported",
                "weak",
                "insufficient",
            }
            assert rec["rule_id"]

    def test_evidence_is_attached_and_resolvable(self, client):
        body = client.post("/analyze", json=self.DEMO).json()

        attached = [
            item
            for rec in body["recommendations"]
            for item in rec["evidence"]
        ]

        assert attached, "expected at least one evidence item"

        for item in attached:
            assert item["source"]
            assert item["title"]
            assert item["relevance"] is not None
            # No fabricated citations: each id must resolve.
            assert (
                client.get(f"/knowledge/{item['id']}").status_code
                == 200
            )

    def test_recommendations_without_evidence_say_so(self, client):
        body = client.post("/analyze", json=self.DEMO).json()

        for rec in body["recommendations"]:
            if rec["evidence_status"] == "insufficient":
                assert rec["evidence"] == []
                assert rec["evidence_note"]

    def test_uncertainty_is_represented(self, client):
        body = client.post("/analyze", json=self.DEMO).json()

        assert body["caveats"]
        assert body["biodiversity_observation_note"]
        assert any(
            "prototype" in caveat.lower() for caveat in body["caveats"]
        )

    def test_second_ecosystem_scenario(self, client):
        """Grassland / tropical, per brief section 18."""
        response = client.post(
            "/analyze",
            json={
                "soil_organic_carbon_g_per_kg": 12.0,
                "precipitation_mm_day": 0.8,
                "soil_ph": 8.4,
                "temperature_c": 36.0,
                "land_use": "degraded rangeland",
                "region": "tropical",
            },
        )

        assert response.status_code == 200
        body = response.json()

        assert body["derived_features"]["water_stress"] == "high"
        assert body["derived_features"]["thermal_stress"] == "high"
        assert body["derived_features"]["soil_ph_condition"] == (
            "high_stress"
        )
        assert body["recommendations"]

    def test_unknown_field_rejected(self, client):
        response = client.post(
            "/analyze", json={"soil_organic_carbon": 5.8}
        )
        assert response.status_code == 422

    def test_invalid_range_rejected(self, client):
        response = client.post("/analyze", json={"soil_ph": 99})
        assert response.status_code == 422

    def test_partial_input_still_works(self, client):
        response = client.post(
            "/analyze",
            json={
                "soil_organic_carbon_g_per_kg": 4.0,
                "precipitation_mm_day": 0.9,
            },
        )

        assert response.status_code == 200
        body = response.json()

        assert "land_use" in body["missing_variables"]
        assert body["recommendations"]
        assert any(
            "missing variables" in caveat
            for caveat in body["caveats"]
        )

    def test_empty_input_does_not_crash(self, client):
        response = client.post("/analyze", json={})

        assert response.status_code == 200
        assert response.json()["recommendations"] == []


# =====================================================================
class TestChat:
    def test_multi_turn_conversation(self, client):
        """
        Full integration path, per brief section 16:
        natural language -> parser -> memory -> reasoning -> RAG
        -> recommendation.
        """
        first = client.post(
            "/chat",
            json={
                "conversation_id": "t1",
                "message": (
                    "My SOC is 0.58%, annual rainfall is 600 mm, "
                    "pH is 5.4 and this is wheat monoculture."
                ),
            },
        ).json()

        # Region is still missing, so it must ask rather than guess.
        assert first["type"] == "clarification"
        assert first["missing_variables"] == ["region"]
        assert "region" in first["message"]

        # The units were normalized, and it said so.
        assert first["environment"][
            "soil_organic_carbon_g_per_kg"
        ] == 5.8
        assert round(
            first["environment"]["precipitation_mm_day"], 4
        ) == 1.6438

        second = client.post(
            "/chat",
            json={"conversation_id": "t1", "message": "It is semi-arid."},
        ).json()

        # It must remember turn one rather than asking again.
        assert second["type"] == "analysis"
        assert second["environment"]["soil_ph"] == 5.4
        assert second["environment"]["land_use"] == "wheat monoculture"

        analysis = second["analysis"]
        assert analysis["recommendations"]
        assert analysis["derived_features"]["water_stress"] == (
            "moderate"
        )
        assert analysis["derived_features"]["soil_ph_condition"] == (
            "high_stress"
        )

        # Evidence retrieved per recommendation.
        assert any(rec["evidence"] for rec in analysis["recommendations"])

    def test_follow_up_reuses_context(self, client):
        client.post(
            "/chat",
            json={
                "conversation_id": "t2",
                "message": (
                    "SOC 0.58%, annual rainfall 600 mm, pH 5.4, "
                    "wheat monoculture, semi-arid"
                ),
            },
        )

        follow_up = client.post(
            "/chat",
            json={
                "conversation_id": "t2",
                "message": (
                    "What should I change without replacing wheat?"
                ),
            },
        ).json()

        # No variables were restated, yet the analysis still runs.
        assert follow_up["type"] == "analysis"
        assert follow_up["environment"]["soil_ph"] == 5.4

        actions = " ".join(
            rec["recommendation"]
            for rec in follow_up["analysis"]["recommendations"]
        )

        # The monoculture rule offers an in-system option rather than
        # telling the user to abandon their crop.
        assert "wheat" in actions.lower()

    def test_conversations_are_isolated(self, client):
        client.post(
            "/chat",
            json={"conversation_id": "a", "message": "pH is 5.4"},
        )
        second = client.post(
            "/chat",
            json={"conversation_id": "b", "message": "pH is 7.1"},
        ).json()

        assert second["environment"]["soil_ph"] == 7.1

    def test_reset(self, client):
        client.post(
            "/chat",
            json={"conversation_id": "r", "message": "pH is 5.4"},
        )
        client.post("/chat/reset", json={"conversation_id": "r"})

        after = client.post(
            "/chat",
            json={"conversation_id": "r", "message": "hello"},
        ).json()

        assert "soil_ph" not in after["environment"]

    def test_message_with_no_data_asks_for_everything(self, client):
        response = client.post(
            "/chat",
            json={"conversation_id": "x", "message": "hello there"},
        ).json()

        assert response["type"] == "clarification"
        assert len(response["missing_variables"]) == 4

    def test_structured_input_merges_with_text(self, client):
        response = client.post(
            "/chat",
            json={
                "conversation_id": "m",
                "message": "the site is semi-arid cropland",
                "environmental": {
                    "soil_organic_carbon_g_per_kg": 5.8,
                    "precipitation_mm_day": 1.2,
                },
            },
        ).json()

        assert response["type"] == "analysis"
        assert response["environment"]["region"] == "semi-arid"
        assert response["environment"][
            "soil_organic_carbon_g_per_kg"
        ] == 5.8


# =====================================================================
class TestDegradedOperation:
    def test_analysis_survives_knowledge_base_failure(
        self, monkeypatch
    ):
        """
        Brief section 15: if the vector store fails, the environmental
        analysis must still work.
        """
        broken = StubKnowledgeService(fail=True)

        monkeypatch.setattr(app_module, "knowledge", broken)
        monkeypatch.setattr(
            app_module,
            "analysis",
            AnalysisService(broken, app_module.reasoning),
        )

        client = TestClient(app_module.app)

        response = client.post(
            "/analyze",
            json={
                "soil_organic_carbon_g_per_kg": 5.8,
                "precipitation_mm_day": 1.6438,
                "soil_ph": 5.4,
                "land_use": "wheat monoculture",
            },
        )

        assert response.status_code == 200
        body = response.json()

        # Reasoning intact, evidence honestly absent.
        assert body["recommendations"]
        assert body["reasoning_chain"]

        for rec in body["recommendations"]:
            assert rec["evidence_status"] == "insufficient"
            assert "unavailable" in rec["evidence_note"]

        assert any(
            "backed by strongly matching" in caveat
            for caveat in body["caveats"]
        )

    def test_malformed_json_rejected(self, client):
        response = client.post(
            "/analyze",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


# =====================================================================
class TestClientContract:
    """
    Fields the frontend reads must be present on BOTH chat branches.
    A key that appears only on clarification responses forces the
    client to guess whether an absent key means "nothing missing" or
    "not sent".
    """

    def test_missing_variables_present_on_analysis_branch(
        self, client
    ):
        body = client.post(
            "/chat",
            json={
                "conversation_id": "contract",
                "message": (
                    "SOC 0.58%, annual rainfall 600 mm, pH 5.4, "
                    "wheat monoculture, semi-arid"
                ),
            },
        ).json()

        assert body["type"] == "analysis"
        assert body["missing_variables"] == []

        for key in (
            "message",
            "environment",
            "normalization_notes",
            "degraded_sources",
            "analysis",
        ):
            assert key in body

    def test_condition_scale_keys_exist_in_derived_features(
        self, client
    ):
        """
        The UI plots these seven indicators on ordinal scales. If the
        feature engineer stops emitting one, the panel silently shows
        "not measured" instead of failing, so assert them here.
        """
        body = client.post(
            "/chat",
            json={
                "conversation_id": "scales",
                "message": (
                    "SOC 0.58%, annual rainfall 600 mm, pH 5.4, "
                    "temperature 26 C, wheat monoculture, semi-arid"
                ),
            },
        ).json()

        derived = body["analysis"]["derived_features"]

        for key in (
            "water_stress",
            "thermal_stress",
            "soil_carbon_condition",
            "soil_ph_condition",
            "habitat_condition",
            "land_cover_pressure",
            "biodiversity_evidence_confidence",
        ):
            assert key in derived
