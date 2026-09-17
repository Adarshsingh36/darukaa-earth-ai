from __future__ import annotations

from app.models.schemas import EnvironmentalInput
from app.services.feature_engineering import EnvironmentalFeatureEngineer


class ReasoningEngine:
    """
    Multi-metric environmental reasoning engine.

    Converts API environmental inputs into derived environmental
    condition indicators and produces interpretable recommendations.

    Scientific evidence retrieval is handled by KnowledgeService
    in the API layer.
    """

    def __init__(self):
        self.features = EnvironmentalFeatureEngineer()

    def _feature_input(self, e: EnvironmentalInput):
        return {
        "temperature_c": e.temperature_c,
        "precipitation_mm_day": e.precipitation_mm_day,
        "soil_organic_carbon_g_per_kg": (
            e.soil_organic_carbon_g_per_kg
        ),
        "soil_ph": e.soil_ph,
        "land_cover_label": e.land_use,
        "gbif_species_observed": e.species_richness,
        "gbif_observation_effort": None,
    }

    def analyze(self, e: EnvironmentalInput):

        detected = e.model_dump(exclude_none=True)

        feature_input = self._feature_input(e)

        derived = self.features.transform(
            feature_input
        )

        chain: list[str] = []
        recommendations: list[dict] = []

        # ---------------------------------------------------------
        # SOIL CARBON + WATER
        # ---------------------------------------------------------
        if (
            derived["soil_carbon_condition"]
            in {"moderate_stress", "high_stress"}
            and derived["water_stress"]
            in {"moderate", "high"}
        ):
            chain.extend([
                (
                    "Soil organic carbon is "
                    f"{derived['soil_carbon_condition'].replace('_', ' ')}."
                ),
                (
                    "Rainfall indicates "
                    f"{derived['water_stress']} water stress."
                ),
                (
                    "The combination indicates that limited water "
                    "availability may interact with reduced soil "
                    "carbon and soil water-retention capacity."
                ),
            ])

            recommendations.append({
                "recommendation": (
                    "Increase soil organic inputs through cover crops, "
                    "retained residues, or soil-test-guided organic amendments."
                ),
                "why_it_works": (
                    "Increasing organic inputs can improve soil carbon "
                    "and soil structure and can support water-retention "
                    "processes. The intervention therefore targets "
                    "both soil condition and water stress."
                ),
                "impacted_metrics": [
                    "soil organic carbon",
                    "soil structure",
                    "soil moisture retention",
                    "soil biological activity",
                ],
                "time_horizon": "medium term",
                "expected_change": (
                    "Expected direction: increased soil organic carbon "
                    "and improved soil water-retention-related properties."
                ),
            })

        # ---------------------------------------------------------
        # SOIL CARBON + AGRICULTURAL LAND
        # ---------------------------------------------------------
        if (
            derived["soil_carbon_condition"]
            in {"moderate_stress", "high_stress"}
            and e.land_use
            and any(
                word in e.land_use.lower()
                for word in [
                    "crop",
                    "cropland",
                    "agriculture",
                    "agricultural",
                    "monoculture",
                    "plantation",
                ]
            )
        ):
            chain.extend([
                (
                    "The location combines agricultural land use "
                    "with reduced soil-carbon condition."
                ),
                (
                    "This creates an opportunity to improve soil "
                    "condition without requiring complete land-use conversion."
                ),
            ])

            recommendations.append({
                "recommendation": (
                    "Introduce diverse cover crops or retain crop "
                    "residues between production cycles."
                ),
                "why_it_works": (
                    "Additional plant biomass supplies carbon inputs "
                    "and maintains soil cover, supporting soil structure "
                    "and biological activity."
                ),
                "impacted_metrics": [
                    "soil organic carbon",
                    "soil biological activity",
                    "soil structure",
                    "habitat diversity",
                ],
                "time_horizon": "medium term",
                "expected_change": (
                    "Expected direction: increasing soil carbon and "
                    "soil biological activity over repeated management cycles."
                ),
            })

        # ---------------------------------------------------------
        # LAND COVER / HABITAT
        # ---------------------------------------------------------
        if derived["habitat_condition"] == "reduced":

            chain.extend([
                (
                    "The current land-cover context indicates "
                    "reduced habitat condition relative to natural vegetation."
                ),
                (
                    "Land-use pressure is therefore considered separately "
                    "from measured soil and climate stress."
                ),
            ])

            recommendations.append({
                "recommendation": (
                    "Add locally appropriate native vegetation along "
                    "field margins, watercourses, or suitable boundaries."
                ),
                "why_it_works": (
                    "Native vegetation can increase structural habitat, "
                    "forage resources, litter inputs, and movement pathways "
                    "while retaining the primary land use."
                ),
                "impacted_metrics": [
                    "habitat diversity",
                    "habitat connectivity",
                    "species richness",
                    "soil organic carbon",
                    "microclimate",
                ],
                "time_horizon": "medium to long term",
                "expected_change": (
                    "Expected direction: increased habitat structural "
                    "diversity and additional resources for wildlife."
                ),
            })

        # ---------------------------------------------------------
        # SOIL pH
        # ---------------------------------------------------------
        if derived["soil_ph_condition"] in {
            "moderate_stress",
            "high_stress",
        }:

            chain.append(
                (
                    "Soil pH is classified as "
                    f"{derived['soil_ph_condition'].replace('_', ' ')} "
                    "under the prototype assessment thresholds."
                )
            )

            recommendations.append({
                "recommendation": (
                    "Use a soil-test-guided pH management strategy "
                    "rather than applying amendments at a fixed rate."
                ),
                "why_it_works": (
                    "Managing pH toward a soil- and crop-appropriate "
                    "range can improve nutrient availability and reduce "
                    "chemical constraints on soil biological processes."
                ),
                "impacted_metrics": [
                    "soil pH",
                    "nutrient availability",
                    "soil biological activity",
                ],
                "time_horizon": "short to medium term",
                "expected_change": (
                    "Expected direction: movement toward a more suitable "
                    "soil-pH range when amendments are selected using "
                    "soil-test results."
                ),
            })

        # ---------------------------------------------------------
        # WATER + HABITAT
        # ---------------------------------------------------------
        if (
            derived["water_stress"]
            in {"moderate", "high"}
            and derived["habitat_condition"] == "reduced"
        ):
            chain.extend([
                (
                    "Water stress occurs alongside reduced habitat condition."
                ),
                (
                    "Vegetation and soil-cover interventions can therefore "
                    "target both water-retention processes and habitat resources."
                ),
            ])

            recommendations.append({
                "recommendation": (
                    "Use native vegetated buffers and persistent ground "
                    "cover where locally appropriate."
                ),
                "why_it_works": (
                    "Vegetative cover protects exposed soil, contributes "
                    "organic inputs, and can create shaded and refuge areas "
                    "while supporting soil water-retention processes."
                ),
                "impacted_metrics": [
                    "soil moisture retention",
                    "soil organic carbon",
                    "habitat diversity",
                    "species richness",
                ],
                "time_horizon": "medium term",
                "expected_change": (
                    "Expected direction: improved soil-cover continuity, "
                    "water-retention conditions, and habitat resources."
                ),
            })

        # ---------------------------------------------------------
        # THERMAL STRESS
        # ---------------------------------------------------------
        if derived["thermal_stress"] == "high":

            chain.extend([
                (
                    "Temperature is classified as high thermal stress "
                    "relative to the prototype thresholds."
                ),
                (
                    "Vegetation structure may provide thermal refuge, "
                    "although the appropriate intervention depends on "
                    "the local ecosystem."
                ),
            ])

            recommendations.append({
                "recommendation": (
                    "Preserve or establish locally appropriate native "
                    "vegetation structures where feasible."
                ),
                "why_it_works": (
                    "Vegetation can provide shade, surface cover, and "
                    "microhabitat variation that may reduce exposure "
                    "to thermal extremes."
                ),
                "impacted_metrics": [
                    "microclimate",
                    "habitat diversity",
                    "species survival",
                ],
                "time_horizon": "medium to long term",
                "expected_change": (
                    "Expected direction: greater microhabitat and "
                    "thermal-refuge availability."
                ),
            })

        # ---------------------------------------------------------
        # FALLBACK
        # ---------------------------------------------------------
        if not chain:
            chain.append(
                "No high-priority multi-metric stress combination "
                "was detected from the supplied environmental variables."
            )

        return {
            "detected_variables": detected,
            "derived_features": derived,
            "reasoning_chain": chain,
            "recommendations": recommendations,
        }
