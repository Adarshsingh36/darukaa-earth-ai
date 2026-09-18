"""
Multi-metric environmental reasoning engine.

Converts canonical environmental inputs into derived condition
indicators and interpretable candidate recommendations.

WHAT CHANGED AND WHY
--------------------
1. Land use is normalized to a canonical land-cover class before
   feature engineering. Previously free text such as "wheat
   monoculture" never matched the cover vocabulary, so habitat
   condition stayed "unknown" and the habitat rules silently never
   fired for exactly the demo scenario they were written for.

2. Each candidate now carries retrieval metadata
   (`retrieval_terms`, `rule_id`, `rule_strength`,
   `supporting_variables`). Evidence retrieval is recommendation-
   specific, so each recommendation must state what it is about rather
   than inheriting one generic query for the whole analysis.

3. Each rule declares an explicit causal chain so the reasoning output
   describes interactions between variables, not a list of variables.

None of the existing recommendation text was rewritten.
"""

from __future__ import annotations

from app.models.schemas import EnvironmentalInput
from app.services.feature_engineering import EnvironmentalFeatureEngineer
from app.services.land_cover import normalize_land_use

#: Rule strength reflects how many independent measured variables the
#: rule depends on and how well-established the mechanism is. It is an
#: input to prototype confidence, not a probability.
STRENGTH_STRONG = "strong"
STRENGTH_MODERATE = "moderate"
STRENGTH_WEAK = "weak"


class ReasoningEngine:
    """
    Deterministic environmental reasoning.

    Scientific evidence retrieval is handled separately by
    `EvidenceRetriever`, per recommendation.
    """

    def __init__(self):
        self.features = EnvironmentalFeatureEngineer()

    # ----------------------------------------------------------------
    def _feature_input(
        self,
        env: EnvironmentalInput,
        land_cover_class: str | None,
        observation_effort: float | None = None,
        observed_species: float | None = None,
    ) -> dict:
        return {
            "temperature_c": env.temperature_c,
            "precipitation_mm_day": env.precipitation_mm_day,
            "soil_organic_carbon_g_per_kg": (
                env.soil_organic_carbon_g_per_kg
            ),
            "soil_ph": env.soil_ph,
            # Canonical cover class, not the raw free text.
            "land_cover_label": land_cover_class,
            # A live GBIF count is used when the user supplied no
            # species figure of their own. Passing it separately (not
            # via species_richness) keeps an UNSURVEYED area - zero
            # records, zero species - distinguishable from a user
            # asserting a richness of zero.
            "gbif_species_observed": (
                env.species_richness
                if env.species_richness is not None
                else observed_species
            ),
            # Observation effort is only meaningful when it comes from
            # a GBIF query. A user-supplied species_richness carries no
            # effort information, so it stays None and the biodiversity
            # signal correctly reports "unknown" rather than implying a
            # census. Live enrichment fills this in when coordinates
            # are supplied.
            "gbif_observation_effort": observation_effort,
        }

    # ----------------------------------------------------------------
    def analyze(
        self,
        env: EnvironmentalInput,
        observation_effort: float | None = None,
        observed_species: float | None = None,
    ) -> dict:
        detected = env.model_dump(exclude_none=True)

        land_cover = normalize_land_use(env.land_use)
        land_cover_class = land_cover["land_cover_class"]

        derived = self.features.transform(
            self._feature_input(
                env,
                land_cover_class,
                observation_effort,
                observed_species,
            )
        )

        # Surface the normalization so the response can show what the
        # free text was interpreted as.
        derived["land_cover_class"] = land_cover_class
        derived["management_intensity"] = land_cover[
            "management_intensity"
        ]

        chain: list[str] = []
        recommendations: list[dict] = []

        for rule in self._rules():
            outcome = rule(env, derived)
            if not outcome:
                continue

            rule_chain, candidate = outcome
            chain.extend(rule_chain)
            recommendations.append(candidate)

        if not chain:
            chain.append(
                "No high-priority multi-metric stress combination "
                "was detected from the supplied environmental variables."
            )

        notes = []
        if land_cover["normalization_note"]:
            notes.append(land_cover["normalization_note"])

        return {
            "detected_variables": detected,
            "derived_features": derived,
            "reasoning_chain": chain,
            "recommendations": recommendations,
            "normalization_notes": notes,
        }

    # ----------------------------------------------------------------
    def _rules(self):
        return [
            self._rule_soil_carbon_water,
            self._rule_soil_carbon_agriculture,
            self._rule_monoculture_diversification,
            self._rule_habitat,
            self._rule_soil_ph,
            self._rule_water_habitat,
            self._rule_thermal,
        ]

    # ----------------------------------------------------------------
    # SOIL CARBON + WATER
    # soil carbon -> soil structure -> water retention -> vegetation
    # ----------------------------------------------------------------
    def _rule_soil_carbon_water(self, env, derived):
        if derived["soil_carbon_condition"] not in {
            "moderate_stress",
            "high_stress",
        }:
            return None

        if derived["water_stress"] not in {"moderate", "high"}:
            return None

        chain = [
            "Soil organic carbon is "
            f"{derived['soil_carbon_condition'].replace('_', ' ')}.",
            "Rainfall indicates "
            f"{derived['water_stress']} water stress.",
            "The combination indicates that limited water "
            "availability may interact with reduced soil "
            "carbon and soil water-retention capacity.",
            "Causal chain: reduced soil carbon -> weaker aggregate "
            "structure -> lower plant-available water holding "
            "capacity -> less reliable vegetation persistence "
            "through dry periods -> fewer sustained habitat "
            "resources.",
        ]

        candidate = {
            "rule_id": "R1_soil_carbon_water",
            "rule_strength": STRENGTH_STRONG,
            "supporting_variables": [
                "soil_organic_carbon_g_per_kg",
                "precipitation_mm_day",
            ],
            "recommendation": (
                "Increase soil organic inputs through cover crops, "
                "retained residues, or soil-test-guided organic "
                "amendments."
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
            "retrieval_terms": [
                "soil organic carbon",
                "organic amendments",
                "soil water retention",
                "soil structure and aggregate stability",
                "cover crops in dry conditions",
                "water holding capacity",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # SOIL CARBON + AGRICULTURAL LAND
    # ----------------------------------------------------------------
    def _rule_soil_carbon_agriculture(self, env, derived):
        if derived["soil_carbon_condition"] not in {
            "moderate_stress",
            "high_stress",
        }:
            return None

        if derived.get("land_cover_class") not in {
            "cropland",
            "agroforestry",
        }:
            return None

        chain = [
            "The location combines agricultural land use "
            "with reduced soil-carbon condition.",
            "This creates an opportunity to improve soil "
            "condition without requiring complete land-use "
            "conversion.",
        ]

        candidate = {
            "rule_id": "R2_soil_carbon_agriculture",
            "rule_strength": STRENGTH_STRONG,
            "supporting_variables": [
                "soil_organic_carbon_g_per_kg",
                "land_use",
            ],
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
                "soil biological activity over repeated management "
                "cycles."
            ),
            "retrieval_terms": [
                "cover crops",
                "crop residue retention",
                "soil organic carbon in cropland",
                "soil biological activity",
                "conservation agriculture",
                "residue management",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # MONOCULTURE DIVERSIFICATION
    # Fires when the cropping system itself is the limiting factor.
    # Deliberately framed as in-system diversification so it remains
    # actionable for a grower who cannot change their primary crop.
    # ----------------------------------------------------------------
    def _rule_monoculture_diversification(self, env, derived):
        if derived.get("management_intensity") != "monoculture":
            return None

        crop = env.crop or "the primary crop"

        chain = [
            "The cropping system is described as a monoculture, so "
            "temporal and structural plant diversity is low.",
            "Causal chain: single-species cover -> uniform rooting "
            "depth and residue chemistry -> narrower soil food web "
            "and fewer above-ground resource niches -> reduced "
            "functional biodiversity, independently of soil "
            "chemistry.",
        ]

        candidate = {
            "rule_id": "R3_monoculture_diversification",
            "rule_strength": STRENGTH_MODERATE,
            "supporting_variables": ["land_use", "crop"],
            "recommendation": (
                "Diversify within the existing rotation rather than "
                f"replacing {crop}: add a legume or multi-species "
                "break crop, intercrop, or an off-season cover "
                "sequence."
            ),
            "why_it_works": (
                "Varying root architecture, residue quality and "
                "flowering periods broadens the range of soil and "
                "above-ground niches without removing the primary "
                "production crop, so diversity gains do not require "
                "a land-use change."
            ),
            "impacted_metrics": [
                "habitat diversity",
                "soil biological activity",
                "soil organic carbon",
                "species richness",
            ],
            "time_horizon": "short to medium term",
            "expected_change": (
                "Expected direction: greater temporal plant "
                "diversity and a wider range of soil and field-scale "
                "resource niches."
            ),
            "retrieval_terms": [
                "crop diversification",
                "crop rotation",
                "intercropping",
                "legume break crop",
                "monoculture biodiversity",
                "functional diversity in farmland",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # LAND COVER / HABITAT
    # land use -> habitat structure -> connectivity -> biodiversity
    # ----------------------------------------------------------------
    def _rule_habitat(self, env, derived):
        if derived["habitat_condition"] != "reduced":
            return None

        chain = [
            "The current land-cover context indicates "
            "reduced habitat condition relative to natural "
            "vegetation.",
            "Land-use pressure is therefore considered separately "
            "from measured soil and climate stress.",
            "Causal chain: simplified land cover -> loss of "
            "structural layers and edge habitat -> reduced "
            "connectivity between remaining patches -> fewer "
            "species able to persist or move through the "
            "landscape.",
        ]

        candidate = {
            "rule_id": "R4_habitat_structure",
            "rule_strength": STRENGTH_MODERATE,
            "supporting_variables": ["land_use"],
            "recommendation": (
                "Add locally appropriate native vegetation along "
                "field margins, watercourses, or suitable boundaries."
            ),
            "why_it_works": (
                "Native vegetation can increase structural habitat, "
                "forage resources, litter inputs, and movement "
                "pathways while retaining the primary land use."
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
            "retrieval_terms": [
                "native vegetation",
                "field margins and hedgerows",
                "habitat connectivity",
                "agroforestry biodiversity",
                "species richness farmland",
                "landscape heterogeneity",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # SOIL pH
    # pH -> nutrient availability -> plant growth -> soil biology
    # ----------------------------------------------------------------
    def _rule_soil_ph(self, env, derived):
        if derived["soil_ph_condition"] not in {
            "moderate_stress",
            "high_stress",
        }:
            return None

        chain = [
            "Soil pH is classified as "
            f"{derived['soil_ph_condition'].replace('_', ' ')} "
            "under the prototype assessment thresholds.",
            "Causal chain: pH outside the favourable range -> "
            "altered nutrient solubility and potential aluminium or "
            "micronutrient constraints -> restricted root and "
            "microbial function -> lower biomass production and "
            "slower organic-matter cycling.",
        ]

        candidate = {
            "rule_id": "R5_soil_ph",
            "rule_strength": STRENGTH_MODERATE,
            "supporting_variables": ["soil_ph"],
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
            "retrieval_terms": [
                "soil pH management",
                "soil acidity and liming",
                "nutrient availability and pH",
                "soil amendment rates",
                "soil biological activity and pH",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # WATER + HABITAT
    # ----------------------------------------------------------------
    def _rule_water_habitat(self, env, derived):
        if derived["water_stress"] not in {"moderate", "high"}:
            return None

        if derived["habitat_condition"] != "reduced":
            return None

        chain = [
            "Water stress occurs alongside reduced habitat "
            "condition.",
            "Vegetation and soil-cover interventions can therefore "
            "target both water-retention processes and habitat "
            "resources.",
        ]

        candidate = {
            "rule_id": "R6_water_habitat",
            "rule_strength": STRENGTH_STRONG,
            "supporting_variables": [
                "precipitation_mm_day",
                "land_use",
            ],
            "recommendation": (
                "Use native vegetated buffers and persistent ground "
                "cover where locally appropriate."
            ),
            "why_it_works": (
                "Vegetative cover protects exposed soil, contributes "
                "organic inputs, and can create shaded and refuge "
                "areas while supporting soil water-retention "
                "processes."
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
            "retrieval_terms": [
                "vegetated buffer strips",
                "ground cover and soil protection",
                "riparian buffers",
                "soil moisture retention vegetation",
                "dryland habitat restoration",
            ],
        }

        return chain, candidate

    # ----------------------------------------------------------------
    # THERMAL STRESS
    # ----------------------------------------------------------------
    def _rule_thermal(self, env, derived):
        if derived["thermal_stress"] != "high":
            return None

        chain = [
            "Temperature is classified as high thermal stress "
            "relative to the prototype thresholds.",
            "Vegetation structure may provide thermal refuge, "
            "although the appropriate intervention depends on "
            "the local ecosystem.",
        ]

        candidate = {
            "rule_id": "R7_thermal",
            "rule_strength": STRENGTH_WEAK,
            "supporting_variables": ["temperature_c"],
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
            "retrieval_terms": [
                "shade and microclimate regulation",
                "vegetation structure thermal refuge",
                "heat stress vegetation cover",
                "canopy cover temperature buffering",
            ],
        }

        return chain, candidate
