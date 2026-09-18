"""
Live geospatial enrichment tests.

No network. Each source fetcher is monkeypatched so the concurrency,
merge precedence and degradation behaviour can be asserted
deterministically, including the failure modes that only show up when
an upstream API is slow or down.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as app_module
from app.models.schemas import EnvironmentalInput
from app.services.analysis import AnalysisService
from app.services.enrichment import (
    LocationEnrichmentService,
    merge_user_and_live,
)
from tests.conftest import StubKnowledgeService


# =====================================================================
# Fake source payloads
# =====================================================================
CLIMATE = {
    "status": "ok",
    "fields": {"temperature_c": 26.4, "precipitation_mm_day": 1.71},
    "payload": {"source": "NASA POWER", "temperature_c": 26.4},
}

SOIL = {
    "status": "ok",
    "fields": {
        "soil_organic_carbon_g_per_kg": 7.2,
        "soil_ph": 6.1,
    },
    "payload": {"source": "ISRIC SoilGrids", "resolution_m": 250},
}

LAND_COVER = {
    "status": "ok",
    "fields": {"land_use": "cropland"},
    "payload": {"source": "ESA WorldCover", "land_cover_class": 40},
}

GBIF = {
    "status": "ok",
    "fields": {"species_richness": 63},
    "payload": {
        "source": "GBIF",
        "occurrence_records": 1840,
        "observed_species_count_sample": 63,
    },
}

GBIF_EMPTY = {
    "status": "ok",
    "fields": {},
    "payload": {
        "source": "GBIF",
        "occurrence_records": 0,
        "observed_species_count_sample": 0,
    },
}


def install_sources(
    monkeypatch,
    service,
    climate=CLIMATE,
    soil=SOIL,
    land_cover=LAND_COVER,
    gbif=GBIF,
):
    """Replace each fetcher with a coroutine returning a fixed result."""

    def make(result):
        async def fetcher(*args, **kwargs):
            if isinstance(result, BaseException):
                raise result
            return result

        return fetcher

    monkeypatch.setattr(service, "_fetch_climate", make(climate))
    monkeypatch.setattr(service, "_fetch_soil", make(soil))
    monkeypatch.setattr(
        service, "_fetch_land_cover", make(land_cover)
    )
    monkeypatch.setattr(
        service, "_fetch_biodiversity", make(gbif)
    )
    return service


# =====================================================================
class TestEnrichment:
    @pytest.mark.anyio
    async def test_all_four_sources_contribute(self, monkeypatch):
        service = install_sources(
            monkeypatch, LocationEnrichmentService()
        )

        context = await service.enrich(18.99, 73.12)

        assert context["succeeded"] is True
        assert context["failures"] == []
        assert len(context["sources"]) == 4

        assert {
            source["source"] for source in context["sources"]
        } == {
            "NASA POWER",
            "ISRIC SoilGrids",
            "ESA WorldCover",
            "GBIF",
        }

        # Provenance: each canonical field is attributed.
        assert context["field_sources"][
            "soil_organic_carbon_g_per_kg"
        ] == "ISRIC SoilGrids"
        assert context["field_sources"]["temperature_c"] == (
            "NASA POWER"
        )
        assert context["field_sources"]["land_use"] == (
            "ESA WorldCover"
        )

    @pytest.mark.anyio
    async def test_one_dead_source_does_not_kill_the_rest(
        self, monkeypatch
    ):
        """
        Regression: `enrich_location` used a bare `asyncio.gather`, so
        a single raising source discarded results that had already
        arrived from the other three.
        """
        service = install_sources(
            monkeypatch,
            LocationEnrichmentService(),
            gbif=TimeoutError("GBIF timed out"),
        )

        context = await service.enrich(18.99, 73.12)

        assert context["succeeded"] is True
        assert len(context["sources"]) == 3
        assert len(context["failures"]) == 1
        assert context["failures"][0]["source"] == "GBIF"
        assert "timed out" in context["failures"][0]["reason"]

        # The surviving sources still delivered their values.
        assert context["values"]["temperature_c"] == 26.4
        assert context["values"]["soil_ph"] == 6.1

    @pytest.mark.anyio
    async def test_missing_geospatial_dependency_is_a_failure_not_a_crash(
        self, monkeypatch
    ):
        """rasterio/pyproj absent must degrade, not break the API."""
        service = install_sources(
            monkeypatch,
            LocationEnrichmentService(),
            soil=ModuleNotFoundError("No module named 'pyproj'"),
            land_cover=ModuleNotFoundError(
                "No module named 'rasterio'"
            ),
        )

        context = await service.enrich(18.99, 73.12)

        assert context["succeeded"] is True
        assert len(context["failures"]) == 2
        assert context["values"]["temperature_c"] == 26.4

    @pytest.mark.anyio
    async def test_total_failure_is_reported_not_raised(
        self, monkeypatch
    ):
        service = install_sources(
            monkeypatch,
            LocationEnrichmentService(),
            climate=RuntimeError("down"),
            soil=RuntimeError("down"),
            land_cover=RuntimeError("down"),
            gbif=RuntimeError("down"),
        )

        context = await service.enrich(18.99, 73.12)

        assert context["succeeded"] is False
        assert context["values"] == {}
        assert len(context["failures"]) == 4

    @pytest.mark.anyio
    async def test_zero_gbif_records_is_success_not_failure(
        self, monkeypatch
    ):
        """Zero occurrences means unsurveyed, not zero biodiversity."""
        service = install_sources(
            monkeypatch,
            LocationEnrichmentService(),
            gbif=GBIF_EMPTY,
        )

        context = await service.enrich(18.99, 73.12)

        assert context["failures"] == []
        assert context["observation_effort"] == 0
        # No species_richness was asserted from an unsurveyed area.
        assert "species_richness" not in context["values"]

    @pytest.mark.anyio
    async def test_every_source_carries_a_scope_caveat(
        self, monkeypatch
    ):
        service = install_sources(
            monkeypatch, LocationEnrichmentService()
        )

        context = await service.enrich(18.99, 73.12)

        for source in context["sources"]:
            assert source["caveat"]

        joined = " ".join(context["caveats"])
        assert "not a species inventory" in joined
        assert "not a ground sample" in joined
        assert "not field-level habitat quality" in joined


# =====================================================================
class TestMergePrecedence:
    def test_user_values_win(self):
        user = {
            "soil_ph": 5.4,
            "soil_organic_carbon_g_per_kg": 5.8,
        }
        live = {
            "values": {
                "soil_ph": 6.1,
                "soil_organic_carbon_g_per_kg": 7.2,
                "temperature_c": 26.4,
            },
            "field_sources": {
                "soil_ph": "ISRIC SoilGrids",
                "soil_organic_carbon_g_per_kg": "ISRIC SoilGrids",
                "temperature_c": "NASA POWER",
            },
        }

        merged, notes, effective = merge_user_and_live(user, live)

        # A farmer's own soil test beats a 250 m raster.
        assert merged["soil_ph"] == 5.4
        assert merged["soil_organic_carbon_g_per_kg"] == 5.8

        # But gaps are filled.
        assert merged["temperature_c"] == 26.4

        # And the override is reported, not silent.
        assert any("kept your value" in note for note in notes)
        assert any("filled from" in note for note in notes)

        # Only the gap-filled field is attributed to a live source;
        # the declined offers stay the user's own values.
        assert effective == {"temperature_c": "NASA POWER"}

    def test_no_user_values_means_all_live(self):
        merged, _, effective = merge_user_and_live(
            {},
            {
                "values": {"soil_ph": 6.1},
                "field_sources": {"soil_ph": "ISRIC SoilGrids"},
            },
        )
        assert merged["soil_ph"] == 6.1
        assert effective["soil_ph"] == "ISRIC SoilGrids"


# =====================================================================
class TestAnalyzeWithCoordinates:
    @pytest.fixture
    def service(self):
        return AnalysisService(StubKnowledgeService())

    @pytest.mark.anyio
    async def test_no_coordinates_skips_enrichment(self, service):
        result = await service.analyze_location(
            EnvironmentalInput(
                soil_organic_carbon_g_per_kg=5.8,
                precipitation_mm_day=1.2,
                land_use="wheat monoculture",
            )
        )

        assert (
            result.data_provenance.live_enrichment_attempted is False
        )
        assert result.recommendations

    @pytest.mark.anyio
    async def test_coordinates_trigger_enrichment(
        self, service, monkeypatch
    ):
        install_sources(monkeypatch, service.enrichment)

        result = await service.analyze_location(
            EnvironmentalInput(
                latitude=18.99,
                longitude=73.12,
                soil_ph=5.4,
            )
        )

        provenance = result.data_provenance

        assert provenance.live_enrichment_attempted is True
        assert provenance.live_enrichment_succeeded is True
        assert len(provenance.retrieved_live) == 4

        # Measured-vs-reasoned separation.
        assert provenance.field_sources["temperature_c"] == (
            "NASA POWER"
        )
        assert "soil_ph" in provenance.supplied_by_user
        assert "soil_ph" not in provenance.field_sources

        # The user's pH survived; SoilGrids' 6.1 did not overwrite it.
        assert result.detected_variables["soil_ph"] == 5.4
        assert any(
            "kept your value" in note
            for note in result.normalization_notes
        )

    @pytest.mark.anyio
    async def test_enrichment_failure_still_produces_analysis(
        self, service, monkeypatch
    ):
        install_sources(
            monkeypatch,
            service.enrichment,
            climate=RuntimeError("NASA down"),
            soil=RuntimeError("SoilGrids down"),
            land_cover=RuntimeError("WorldCover down"),
            gbif=RuntimeError("GBIF down"),
        )

        result = await service.analyze_location(
            EnvironmentalInput(
                latitude=18.99,
                longitude=73.12,
                soil_organic_carbon_g_per_kg=5.8,
                precipitation_mm_day=1.2,
                land_use="wheat monoculture",
            )
        )

        assert result.recommendations
        assert result.data_provenance.live_enrichment_succeeded is (
            False
        )
        assert len(result.data_provenance.degraded_sources) == 4
        assert any(
            "enrichment was unavailable" in caveat
            for caveat in result.caveats
        )

    @pytest.mark.anyio
    async def test_gbif_effort_reaches_the_feature_engineer(
        self, service, monkeypatch
    ):
        """
        Observation effort was hardcoded to None, so the biodiversity
        signal was permanently "unknown" even with GBIF data present.
        """
        install_sources(monkeypatch, service.enrichment)

        result = await service.analyze_location(
            EnvironmentalInput(latitude=18.99, longitude=73.12)
        )

        assert result.derived_features[
            "biodiversity_evidence_confidence"
        ] == "high"
        assert result.derived_features[
            "biodiversity_observation_signal"
        ] == "moderate_observed_diversity"

    @pytest.mark.anyio
    async def test_unsurveyed_area_is_not_zero_biodiversity(
        self, service, monkeypatch
    ):
        install_sources(
            monkeypatch, service.enrichment, gbif=GBIF_EMPTY
        )

        result = await service.analyze_location(
            EnvironmentalInput(latitude=18.99, longitude=73.12)
        )

        assert result.derived_features[
            "biodiversity_observation_signal"
        ] == "no_observation"
        assert "NOT zero biodiversity" in (
            result.biodiversity_observation_note
        )


# =====================================================================
class TestEndpointsWithCoordinates:
    @pytest.fixture
    def client(self, monkeypatch):
        stub = StubKnowledgeService()
        service = AnalysisService(stub, app_module.reasoning)
        install_sources(monkeypatch, service.enrichment)

        monkeypatch.setattr(app_module, "knowledge", stub)
        monkeypatch.setattr(app_module, "analysis", service)
        app_module.memory.sessions.clear()

        return TestClient(app_module.app)

    def test_analyze_with_coordinates(self, client):
        body = client.post(
            "/analyze",
            json={"latitude": 18.99, "longitude": 73.12},
        ).json()

        assert body["data_provenance"]["live_enrichment_succeeded"]
        assert body["recommendations"]
        assert body["data_provenance"]["field_sources"]

    def test_chat_with_coordinates_in_text(self, client):
        body = client.post(
            "/chat",
            json={
                "conversation_id": "geo",
                "message": (
                    "coordinates latitude 18.99 longitude 73.12, "
                    "it is semi-arid"
                ),
            },
        ).json()

        # Live data filled SOC, precipitation and land use, so the
        # assessment can complete without the user supplying them.
        assert body["type"] == "analysis"
        assert body["analysis"]["data_provenance"][
            "live_enrichment_succeeded"
        ]
