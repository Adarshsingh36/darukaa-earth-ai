"""
Live geospatial enrichment.

Fans out to NASA POWER, ISRIC SoilGrids, ESA WorldCover and GBIF
concurrently, merges the results into canonical environmental fields,
and reports exactly which source supplied which value.

THREE RULES THIS ENFORCES
-------------------------
1. **User values are authoritative.** A live value NEVER overwrites a
   value the user supplied. Live data fills gaps only. A farmer's own
   soil test beats a 250 m interpolated raster for their field.

2. **Partial failure is normal.** Every source is awaited with
   `return_exceptions=True` and its own timeout. One dead API degrades
   that source, not the assessment. `enrich_location` in
   `environment_data.py` previously used a bare `asyncio.gather`, so a
   single GBIF timeout took the whole enrichment down.

3. **Measured is separated from reasoned.** The returned `live_context`
   carries per-field provenance so `AnalysisResponse.data_provenance`
   can state what was retrieved versus what was derived.

SCOPE CAVEATS CARRIED WITH EACH SOURCE
--------------------------------------
* SoilGrids is modelled spatial soil information at ~250 m, not a
  ground sample of this field.
* WorldCover is a 10 m land-COVER classification, not field-level
  habitat quality or management intensity.
* GBIF occurrence records reflect where people have surveyed and
  uploaded data. Zero records means no recorded sampling, not zero
  biodiversity.
* NASA POWER climatology is a long-run mean; it does not describe the
  current season.
"""

from __future__ import annotations

import asyncio
from typing import Any

#: Per-source timeout. WorldCover reads a remote COG through GDAL and
#: is reliably the slowest, so it gets the longest budget.
TIMEOUTS = {
    "NASA POWER": 20.0,
    "GBIF": 20.0,
    "ISRIC SoilGrids": 45.0,
    "ESA WorldCover": 60.0,
}

CAVEATS = {
    "NASA POWER": (
        "Long-run climatological mean at ~0.5 degree resolution. It "
        "describes typical conditions, not the current season."
    ),
    "ISRIC SoilGrids": (
        "Modelled spatial soil information at ~250 m resolution. It is "
        "not a ground sample of this specific field; a local soil test "
        "should override it."
    ),
    "ESA WorldCover": (
        "10 m land-cover classification. It identifies broad cover "
        "type, not field-level habitat quality, vegetation structure "
        "or management intensity."
    ),
    "GBIF": (
        "Occurrence records reflect recorded observations and sampling "
        "effort. They are an observation proxy, not a species "
        "inventory. Zero records means no recorded sampling, NOT zero "
        "biodiversity."
    ),
}


class LocationEnrichmentService:
    """
    Concurrent, fault-tolerant enrichment from coordinates.

    Heavy geospatial dependencies (`rasterio`, `pyproj`) are imported
    lazily inside the fetchers. If they are not installed, that source
    records a failure and the rest of the pipeline continues, rather
    than the whole API failing to import.
    """

    def __init__(self, timeouts: dict[str, float] | None = None):
        self.timeouts = {**TIMEOUTS, **(timeouts or {})}

    # ----------------------------------------------------------------
    async def enrich(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:
        """
        Returns a `live_context`:

            {
              "succeeded": bool,          # at least one source usable
              "values": {field: value},   # canonical candidate values
              "field_sources": {field: source_name},
              "sources": [ {...} ],       # successful sources
              "failures": [ {...} ],      # degraded sources + reason
              "observation_effort": int | None,
              "species_observed": int | None,
              "caveats": [str],
            }
        """
        tasks = {
            "NASA POWER": self._fetch_climate(latitude, longitude),
            "ISRIC SoilGrids": self._fetch_soil(latitude, longitude),
            "ESA WorldCover": self._fetch_land_cover(
                latitude, longitude
            ),
            "GBIF": self._fetch_biodiversity(
                latitude, longitude, radius_km
            ),
        }

        names = list(tasks)
        results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        values: dict[str, Any] = {}
        field_sources: dict[str, str] = {}
        sources: list[dict] = []
        failures: list[dict] = []
        caveats: list[str] = []

        observation_effort = None
        species_observed = None

        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                failures.append(
                    {
                        "source": name,
                        "status": "unavailable",
                        "reason": (
                            f"{type(result).__name__}: {result}"
                        ),
                    }
                )
                continue

            payload = result.get("payload", {})

            if result.get("status") != "ok":
                failures.append(
                    {
                        "source": name,
                        "status": result.get(
                            "status", "unavailable"
                        ),
                        "reason": result.get("reason", "no data"),
                    }
                )
                continue

            contributed = {}

            for field, value in result.get("fields", {}).items():
                if value is None:
                    continue
                values[field] = value
                field_sources[field] = name
                contributed[field] = value

            if name == "GBIF":
                observation_effort = payload.get("occurrence_records")
                species_observed = payload.get(
                    "observed_species_count_sample"
                )

            sources.append(
                {
                    "source": name,
                    "type": "live_api",
                    "fields": sorted(contributed),
                    "caveat": CAVEATS[name],
                    "detail": payload,
                }
            )

            caveats.append(f"{name}: {CAVEATS[name]}")

        return {
            "succeeded": bool(sources),
            "values": values,
            "field_sources": field_sources,
            "sources": sources,
            "failures": failures,
            "observation_effort": observation_effort,
            "species_observed": species_observed,
            "caveats": caveats,
        }

    # ----------------------------------------------------------------
    # Individual fetchers. Each returns a uniform envelope so a partial
    # or empty response is distinguishable from an exception.
    # ----------------------------------------------------------------
    async def _fetch_climate(self, latitude, longitude):
        from app.services.environment_data import (
            EnvironmentalDataService,
        )

        service = EnvironmentalDataService(
            timeout=self.timeouts["NASA POWER"]
        )

        payload = await asyncio.wait_for(
            service.fetch_climate(latitude, longitude),
            timeout=self.timeouts["NASA POWER"] + 5,
        )

        fields = {
            "temperature_c": payload.get("temperature_c"),
            "precipitation_mm_day": payload.get(
                "precipitation_mm_day"
            ),
        }

        if not any(value is not None for value in fields.values()):
            return {
                "status": "empty",
                "reason": "NASA POWER returned no usable values",
                "payload": payload,
            }

        return {"status": "ok", "fields": fields, "payload": payload}

    # ----------------------------------------------------------------
    async def _fetch_soil(self, latitude, longitude):
        # Lazy import: soil_data pulls in pyproj/rasterio.
        from app.services.soil_data import SoilGridsService

        service = SoilGridsService(
            timeout=self.timeouts["ISRIC SoilGrids"]
        )

        payload = await asyncio.wait_for(
            service.fetch_soil(latitude, longitude),
            timeout=self.timeouts["ISRIC SoilGrids"] + 10,
        )

        fields = {
            "soil_organic_carbon_g_per_kg": payload.get(
                "soil_organic_carbon_g_per_kg"
            ),
            "soil_ph": payload.get("soil_ph"),
        }

        if not any(value is not None for value in fields.values()):
            return {
                "status": "empty",
                "reason": (
                    "SoilGrids returned no data at this point "
                    "(commonly water, ice or outside coverage)"
                ),
                "payload": payload,
            }

        return {"status": "ok", "fields": fields, "payload": payload}

    # ----------------------------------------------------------------
    async def _fetch_land_cover(self, latitude, longitude):
        # Lazy import: landcover_data pulls in rasterio.
        from app.services.landcover_data import WorldCoverService

        service = WorldCoverService()

        payload = await asyncio.wait_for(
            service.fetch_land_cover(latitude, longitude),
            timeout=self.timeouts["ESA WorldCover"] + 10,
        )

        label = payload.get("land_cover_label")

        if not label:
            return {
                "status": payload.get(
                    "land_cover_status", "unavailable"
                ),
                "reason": payload.get(
                    "error", "no land-cover class at this point"
                ),
                "payload": payload,
            }

        # WorldCover labels are already canonical class tokens, so they
        # pass straight through `land_use` and are recognised by
        # land_cover.normalize_land_use.
        return {
            "status": "ok",
            "fields": {"land_use": label},
            "payload": payload,
        }

    # ----------------------------------------------------------------
    async def _fetch_biodiversity(
        self, latitude, longitude, radius_km
    ):
        from app.services.environment_data import (
            EnvironmentalDataService,
        )

        service = EnvironmentalDataService(
            timeout=self.timeouts["GBIF"]
        )

        payload = await asyncio.wait_for(
            service.fetch_biodiversity(
                latitude, longitude, radius_km
            ),
            timeout=self.timeouts["GBIF"] + 5,
        )

        # NOTE: zero occurrence records is a SUCCESSFUL result, not a
        # failure. It tells us the area is unsurveyed, which the
        # feature engineer reports as `no_observation` rather than as
        # zero biodiversity.
        species = payload.get("observed_species_count_sample")

        return {
            "status": "ok",
            "fields": (
                {"species_richness": species}
                if payload.get("occurrence_records")
                else {}
            ),
            "payload": payload,
        }


def merge_user_and_live(
    user_values: dict[str, Any],
    live_context: dict[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """
    Merge live values into user-supplied values, user wins.

    Returns (merged, notes, effective_sources).

    `effective_sources` maps a field to the live source ONLY where that
    source's value is the one actually in use. A field the user also
    supplied is absent from it, because the live value was offered and
    declined - which is what keeps `supplied_by_user` honest in the
    provenance block.

    Every declined override is reported, so the user can see that their
    own measurement was the one used.
    """
    merged = dict(user_values)
    notes: list[str] = []
    effective_sources: dict[str, str] = {}

    live_values = live_context.get("values", {})
    offered_sources = live_context.get("field_sources", {})

    for field, value in live_values.items():
        source = offered_sources.get(field, "live data")

        if user_values.get(field) is not None:
            if user_values[field] != value:
                notes.append(
                    f"{field}: kept your value "
                    f"{user_values[field]} rather than {source}'s "
                    f"{value}. Supplied measurements take precedence "
                    "over modelled or interpolated data."
                )
            continue

        merged[field] = value
        effective_sources[field] = source
        notes.append(
            f"{field}: filled from {source} ({value})."
        )

    return merged, notes, effective_sources
