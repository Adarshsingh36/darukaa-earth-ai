from __future__ import annotations

from datetime import date
from typing import Any

import httpx


NASA_POWER = "https://power.larc.nasa.gov/api/temporal/climatology/point"
GBIF_SEARCH = "https://api.gbif.org/v1/occurrence/search"


class EnvironmentalDataService:
    """Live environmental data acquisition.

    User-provided measurements remain authoritative. Live APIs enrich the
    assessment when coordinates are available.

    GBIF observations are treated as observation proxies rather than a
    complete census of local biodiversity.
    """

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    async def fetch_climate(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        params = {
            "parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR",
            "community": "AG",
            "latitude": latitude,
            "longitude": longitude,
            "format": "JSON",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(NASA_POWER, params=params)
            response.raise_for_status()
            payload = response.json()

        properties = payload.get("properties", {})
        parameter = properties.get("parameter", {})

        def scalar(name: str) -> float | None:
            values = parameter.get(name, {})
            if not values:
                return None

            nums = [
                float(value)
                for value in values.values()
                if isinstance(value, (int, float))
            ]

            return round(sum(nums) / len(nums), 3) if nums else None

        temperature = scalar("T2M")
        temperature_max = scalar("T2M_MAX")
        temperature_min = scalar("T2M_MIN")

        temperature_range = None
        if temperature_max is not None and temperature_min is not None:
            temperature_range = round(
                temperature_max - temperature_min,
                3,
            )

        return {
            "temperature_c": temperature,
            "temperature_max_c": temperature_max,
            "temperature_min_c": temperature_min,
            "temperature_range_c": temperature_range,
            "precipitation_mm_day": scalar("PRECTOTCORR"),
            "source": "NASA POWER",
            "retrieved_at": date.today().isoformat(),
        }

    async def fetch_biodiversity(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:
        params = {
            "geoDistance": f"{latitude},{longitude},{radius_km:g}km",
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "occurrenceStatus": "PRESENT",
            "limit": 300,
            "offset": 0,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(GBIF_SEARCH, params=params)
            response.raise_for_status()
            payload = response.json()

        results = payload.get("results", [])

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

        occurrence_records = int(payload.get("count", 0) or 0)
        observed_species = len(species_keys)

        # This is deliberately a descriptive observation-density feature.
        # It must not be interpreted as true biodiversity richness.
        species_per_1000_records = None
        if occurrence_records > 0:
            species_per_1000_records = round(
                observed_species / occurrence_records * 1000,
                6,
            )

        return {
            "occurrence_records": occurrence_records,
            "sampled_records": len(results),
            "observed_species_count_sample": observed_species,
            "observed_genera_count_sample": len(genera),
            "observed_families_count_sample": len(families),
            "observed_orders_count_sample": len(orders),
            "observed_kingdom_count_sample": len(kingdoms),
            "species_per_1000_records": species_per_1000_records,
            "radius_km": radius_km,
            "source": "GBIF",
            "retrieved_at": date.today().isoformat(),
            "interpretation": (
                "GBIF observed species and taxonomic counts describe the "
                "available occurrence observations in the selected radius. "
                "They are observation proxies and are not a complete census "
                "of local biodiversity. Observation effort can strongly "
                "affect these values."
            ),
        }

    async def enrich_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:
        """
        Standalone location report across all four sources.

        FIXED: this previously called NASA POWER and GBIF only -
        SoilGrids and WorldCover services existed but were never wired
        in - and used a bare `asyncio.gather`, so a single source
        raising took the entire enrichment down with it. Both are
        addressed by delegating to `LocationEnrichmentService`, which
        isolates every source and reports failures instead of
        propagating them.
        """
        from app.services.enrichment import LocationEnrichmentService

        context = await LocationEnrichmentService().enrich(
            latitude,
            longitude,
            radius_km,
        )

        detail = {
            source["source"]: source["detail"]
            for source in context["sources"]
        }

        return {
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
            },
            "climate": detail.get("NASA POWER", {}),
            "soil": detail.get("ISRIC SoilGrids", {}),
            "land_cover": detail.get("ESA WorldCover", {}),
            "biodiversity": detail.get("GBIF", {}),
            "canonical_values": context["values"],
            "field_sources": context["field_sources"],
            "data_sources": [
                {
                    "name": source["source"],
                    "type": source["type"],
                    "variables": source["fields"],
                    "caveat": source["caveat"],
                }
                for source in context["sources"]
            ],
            "degraded_sources": context["failures"],
            "partial": bool(context["failures"]),
        }
