from __future__ import annotations

from typing import Any


class EnvironmentalFeatureEngineer:
    """
    Converts raw environmental observations into interpretable
    environmental condition indicators.

    These indicators are reasoning features, not ground-truth
    biodiversity labels.
    """

    NATURAL_COVER = {
        "tree_cover",
        "shrubland",
        "grassland",
        "herbaceous_wetland",
        "mangroves",
        "moss_lichen",
    }

    DISTURBED_COVER = {
        "cropland",
        "built_up",
        "bare_sparse_vegetation",
    }

    def transform(self, row: dict[str, Any]) -> dict[str, Any]:
        temperature = self._float(row.get("temperature_c"))
        rainfall = self._float(row.get("precipitation_mm_day"))
        soc = self._float(
            row.get("soil_organic_carbon_g_per_kg")
        )
        ph = self._float(row.get("soil_ph"))

        land_cover = (
            str(row.get("land_cover_label", ""))
            .strip()
            .lower()
        )

        species = self._float(
            row.get("gbif_species_observed")
        )

        observation_effort = self._float(
            row.get("gbif_observation_effort")
        )

        water_stress = self._water_stress(rainfall)
        thermal_stress = self._thermal_stress(temperature)
        soil_carbon_condition = self._soc_condition(soc)
        soil_ph_condition = self._ph_condition(ph)
        land_cover_pressure = self._land_pressure(
            land_cover
        )
        habitat_condition = self._habitat_condition(
            land_cover
        )

        biodiversity_signal = self._biodiversity_signal(
            species,
            observation_effort,
        )

        biodiversity_confidence = (
            self._observation_confidence(
                observation_effort
            )
        )

        stress_indicators = [
            water_stress,
            thermal_stress,
            soil_carbon_condition,
            soil_ph_condition,
        ]

        environmental_stress_count = sum(
            self._is_stress(value)
            for value in stress_indicators
        )

        habitat_pressure = (
            land_cover_pressure in {"moderate", "high"}
            or habitat_condition == "reduced"
        )

        # Environmental condition is based on measured
        # climate and soil stress. Land-cover pressure is
        # retained separately so that cropland does not
        # automatically become an ecosystem-stress label.
        environmental_condition = (
            self._overall_condition(
                environmental_stress_count
            )
        )

        total_environmental_pressure = (
            environmental_stress_count
            + int(habitat_pressure)
        )

        return {
            "water_stress": water_stress,
            "thermal_stress": thermal_stress,
            "soil_carbon_condition": soil_carbon_condition,
            "soil_ph_condition": soil_ph_condition,
            "land_cover_pressure": land_cover_pressure,
            "habitat_condition": habitat_condition,
            "biodiversity_observation_signal": (
                biodiversity_signal
            ),
            "biodiversity_evidence_confidence": (
                biodiversity_confidence
            ),
            "environmental_stress_count": (
                environmental_stress_count
            ),
            "habitat_pressure": habitat_pressure,
            "total_environmental_pressure": (
                total_environmental_pressure
            ),
            "environmental_condition": (
                environmental_condition
            ),
        }

    @staticmethod
    def _float(value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _water_stress(rainfall):
        if rainfall is None:
            return "unknown"

        if rainfall < 1.0:
            return "high"

        if rainfall < 2.0:
            return "moderate"

        return "low"

    @staticmethod
    def _thermal_stress(temperature):
        if temperature is None:
            return "unknown"

        if temperature < 5 or temperature > 35:
            return "high"

        if temperature < 10 or temperature > 30:
            return "moderate"

        return "low"

    @staticmethod
    def _soc_condition(soc):
        if soc is None:
            return "unknown"

        if soc < 5:
            return "high_stress"

        if soc < 10:
            return "moderate_stress"

        return "favorable"

    @staticmethod
    def _ph_condition(ph):
        if ph is None:
            return "unknown"

        if ph < 5.5 or ph > 8.0:
            return "high_stress"

        if ph < 6.0 or ph > 7.5:
            return "moderate_stress"

        return "favorable"

    def _land_pressure(self, land_cover):
        if not land_cover:
            return "unknown"

        if land_cover == "built_up":
            return "high"

        if land_cover in {
            "cropland",
            "bare_sparse_vegetation",
        }:
            return "moderate"

        return "low"

    def _habitat_condition(self, land_cover):
        if not land_cover:
            return "unknown"

        if land_cover in self.NATURAL_COVER:
            return "favorable"

        if land_cover in self.DISTURBED_COVER:
            return "reduced"

        return "unknown"

    @staticmethod
    def _biodiversity_signal(
        species,
        observation_effort,
    ):
        if species is None:
            return "unknown"

        if observation_effort is None:
            return "unknown"

        if observation_effort == 0:
            return "no_observation"

        if observation_effort < 20:
            return "low_evidence"

        if species < 20:
            return "low_observed_diversity"

        if species < 80:
            return "moderate_observed_diversity"

        return "high_observed_diversity"

    @staticmethod
    def _observation_confidence(observation_effort):
        if observation_effort is None:
            return "unknown"

        if observation_effort == 0:
            return "none"

        if observation_effort < 20:
            return "low"

        if observation_effort < 100:
            return "moderate"

        return "high"

    @staticmethod
    def _is_stress(value):
        return value in {
            "high",
            "high_stress",
        }

    @staticmethod
    def _overall_condition(total_pressure_count):
        if total_pressure_count >= 4:
            return "high_stress"

        if total_pressure_count >= 2:
            return "moderate_stress"

        if total_pressure_count == 1:
            return "mild_stress"

        return "relatively_favorable"
