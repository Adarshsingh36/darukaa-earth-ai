from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from app.services.landcover_data import WorldCoverService
from app.services.soil_data import SoilGridsService


NASA_POWER = (
    "https://power.larc.nasa.gov/api/temporal/climatology/point"
)

GBIF_SEARCH = (
    "https://api.gbif.org/v1/occurrence/search"
)


class EnvironmentalDataService:
    """
    Live environmental data acquisition and enrichment.

    Sources:
        - NASA POWER: climate
        - GBIF: biodiversity observations
        - ISRIC SoilGrids: soil organic carbon and pH
        - ESA WorldCover: land cover

    User-provided environmental measurements remain authoritative.
    Live sources are used to fill missing variables when coordinates
    are available.

    GBIF observations are explicitly treated as observation proxies,
    not as a complete biodiversity census.
    """

    def __init__(
        self,
        timeout: float = 20.0,
    ):
        self.timeout = timeout

        self.soil = SoilGridsService(
            timeout=max(timeout, 60.0)
        )

        self.landcover = WorldCoverService(
            timeout=max(timeout, 30.0)
        )

    # ------------------------------------------------------------------
    # NASA POWER
    # ------------------------------------------------------------------

    async def fetch_climate(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        params = {
            "parameters": (
                "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR"
            ),
            "community": "AG",
            "latitude": latitude,
            "longitude": longitude,
            "format": "JSON",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.get(
                NASA_POWER,
                params=params,
            )

            response.raise_for_status()

            payload = response.json()

        properties = payload.get(
            "properties",
            {},
        )

        parameter = properties.get(
            "parameter",
            {},
        )

        def scalar(
            name: str,
        ) -> float | None:

            values = parameter.get(
                name,
                {},
            )

            if not values:
                return None

            numbers = [
                float(value)
                for value in values.values()
                if isinstance(
                    value,
                    (int, float),
                )
            ]

            if not numbers:
                return None

            return round(
                sum(numbers) / len(numbers),
                3,
            )

        temperature = scalar("T2M")
        temperature_max = scalar("T2M_MAX")
        temperature_min = scalar("T2M_MIN")

        temperature_range = None

        if (
            temperature_max is not None
            and temperature_min is not None
        ):
            temperature_range = round(
                temperature_max - temperature_min,
                3,
            )

        return {
            "temperature_c": temperature,
            "temperature_max_c": temperature_max,
            "temperature_min_c": temperature_min,
            "temperature_range_c": temperature_range,
            "precipitation_mm_day": scalar(
                "PRECTOTCORR"
            ),
            "source": "NASA POWER",
            "retrieved_at": date.today().isoformat(),
        }

    # ------------------------------------------------------------------
    # GBIF
    # ------------------------------------------------------------------

    async def fetch_biodiversity(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:

        params = {
            "geoDistance": (
                f"{latitude},{longitude},"
                f"{radius_km:g}km"
            ),
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "occurrenceStatus": "PRESENT",
            "limit": 300,
            "offset": 0,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.get(
                GBIF_SEARCH,
                params=params,
            )

            response.raise_for_status()

            payload = response.json()

        results = payload.get(
            "results",
            [],
        )

        species_keys = {
            item.get("speciesKey")
            for item in results
            if item.get("speciesKey") is not None
        }

        genera = {
            item.get("genus")
            for item in results
            if item.get("genus")
        }

        families = {
            item.get("family")
            for item in results
            if item.get("family")
        }

        orders = {
            item.get("order")
            for item in results
            if item.get("order")
        }

        kingdoms = {
            item.get("kingdom")
            for item in results
            if item.get("kingdom")
        }

        occurrence_records = int(
            payload.get("count", 0) or 0
        )

        observed_species = len(
            species_keys
        )

        species_per_1000_records = None

        if occurrence_records > 0:
            species_per_1000_records = round(
                (
                    observed_species
                    / occurrence_records
                    * 1000
                ),
                6,
            )

        return {
            "occurrence_records": occurrence_records,
            "sampled_records": len(results),
            "observed_species_count_sample": (
                observed_species
            ),
            "observed_genera_count_sample": (
                len(genera)
            ),
            "observed_families_count_sample": (
                len(families)
            ),
            "observed_orders_count_sample": (
                len(orders)
            ),
            "observed_kingdom_count_sample": (
                len(kingdoms)
            ),
            "species_per_1000_records": (
                species_per_1000_records
            ),
            "radius_km": radius_km,
            "source": "GBIF",
            "retrieved_at": date.today().isoformat(),
            "interpretation": (
                "GBIF observed species and taxonomic "
                "counts describe available occurrence "
                "observations within the selected radius. "
                "They are observation proxies and are not "
                "a complete census of local biodiversity. "
                "Observation effort can strongly affect "
                "these values."
            ),
        }

    # ------------------------------------------------------------------
    # Combined enrichment
    # ------------------------------------------------------------------

    async def enrich_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:

        tasks = {
            "climate": self.fetch_climate(
                latitude,
                longitude,
            ),
            "biodiversity": self.fetch_biodiversity(
                latitude,
                longitude,
                radius_km,
            ),
            "soil": self.soil.fetch_soil(
                latitude,
                longitude,
            ),
            "land_cover": self.landcover.fetch_land_cover(
                latitude,
                longitude,
            ),
        }

        results: dict[str, Any] = {}
        degraded_sources: list[dict[str, Any]] = []

        async def run_source(
            name: str,
            coroutine,
        ) -> None:

            try:
                results[name] = await coroutine

            except Exception as exc:

                results[name] = {
                    "source": self._source_name(name),
                    "status": "unavailable",
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{str(exc)}"
                    ),
                }

                degraded_sources.append(
                    {
                        "source": self._source_name(name),
                        "status": "unavailable",
                        "error": str(exc),
                    }
                )

        await asyncio.gather(
            *[
                run_source(
                    name,
                    coroutine,
                )
                for name, coroutine in tasks.items()
            ]
        )

        return {
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },

            "climate": results.get(
                "climate",
                {},
            ),

            "biodiversity": results.get(
                "biodiversity",
                {},
            ),

            "soil": results.get(
                "soil",
                {},
            ),

            "land_cover": results.get(
                "land_cover",
                {},
            ),

            "degraded_sources": degraded_sources,

            "data_sources": [
                {
                    "name": "NASA POWER",
                    "type": "live_api",
                    "variables": [
                        "temperature_c",
                        "temperature_max_c",
                        "temperature_min_c",
                        "temperature_range_c",
                        "precipitation_mm_day",
                    ],
                },
                {
                    "name": "GBIF",
                    "type": "live_api",
                    "variables": [
                        "occurrence_records",
                        "sampled_records",
                        "observed_species_count_sample",
                        "observed_genera_count_sample",
                        "observed_families_count_sample",
                        "observed_orders_count_sample",
                        "observed_kingdom_count_sample",
                        "species_per_1000_records",
                    ],
                },
                {
                    "name": "ISRIC SoilGrids",
                    "type": "live_geospatial",
                    "variables": [
                        "soil_organic_carbon_g_per_kg",
                        "soil_ph",
                    ],
                },
                {
                    "name": "ESA WorldCover 2021 v200",
                    "type": "live_geospatial",
                    "variables": [
                        "land_cover_class",
                        "land_cover_label",
                        "is_terrestrial",
                    ],
                },
            ],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _source_name(
        name: str,
    ) -> str:

        return {
            "climate": "NASA POWER",
            "biodiversity": "GBIF",
            "soil": "ISRIC SoilGrids",
            "land_cover": (
                "ESA WorldCover 2021 v200"
            ),
        }.get(
            name,
            name,
        )