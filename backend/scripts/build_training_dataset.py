from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from app.services.environment_data import EnvironmentalDataService
from app.services.soil_data import SoilGridsService
from app.services.landcover_data import WorldCoverService


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "training_locations.csv"
OUTPUT = ROOT / "data" / "environment_training.csv"

# Keep the acquisition reasonably parallel, but do not overload
# external scientific data services.
CONCURRENCY = 4

# A single service should not hold a location forever.
SERVICE_TIMEOUT = 30


async def safe_call(coro, name: str):
    """Run one external service call without killing the location."""
    try:
        return await asyncio.wait_for(
            coro,
            timeout=SERVICE_TIMEOUT,
        )
    except Exception as exc:
        print(
            f"    {name}: {type(exc).__name__}: {exc}"
        )
        return {}


async def fetch_one(
    environment_service: EnvironmentalDataService,
    soil_service: SoilGridsService,
    landcover_service: WorldCoverService,
    latitude: float,
    longitude: float,
):
    """
    Stage 1 environmental acquisition.

    GBIF is intentionally NOT queried here.

    Terrestrial classification, climate and soil are sufficient
    to build the first environmental training table. GBIF will
    be added later only for confirmed terrestrial locations.
    """

    climate, soil, landcover = await asyncio.gather(
        safe_call(
            environment_service.fetch_climate(
                latitude,
                longitude,
            ),
            "NASA",
        ),
        safe_call(
            soil_service.fetch_soil(
                latitude,
                longitude,
            ),
            "SoilGrids",
        ),
        safe_call(
            landcover_service.fetch_land_cover(
                latitude,
                longitude,
            ),
            "WorldCover",
        ),
    )

    return {
        "latitude": latitude,
        "longitude": longitude,

        # NASA POWER
        "temperature_c": climate.get(
            "temperature_c"
        ),
        "temperature_max_c": climate.get(
            "temperature_max_c"
        ),
        "temperature_min_c": climate.get(
            "temperature_min_c"
        ),
        "temperature_range_c": climate.get(
            "temperature_range_c"
        ),
        "precipitation_mm_day": climate.get(
            "precipitation_mm_day"
        ),

        # SoilGrids
        "soil_organic_carbon_g_per_kg": soil.get(
            "soil_organic_carbon_g_per_kg"
        ),
        "soil_ph": soil.get(
            "soil_ph"
        ),
        "soil_source_distance_m": soil.get(
            "soc_source_distance_m"
        ),
        "soil_ph_source_distance_m": soil.get(
            "ph_source_distance_m"
        ),

        # ESA WorldCover
        "land_cover_class": landcover.get(
            "land_cover_class"
        ),
        "land_cover_label": landcover.get(
            "land_cover_label"
        ),
        "is_terrestrial": landcover.get(
            "is_terrestrial"
        ),
        "land_cover_status": landcover.get(
            "land_cover_status"
        ),

        # GBIF is deliberately left empty in Stage 1.
        "gbif_occurrence_records": None,
        "gbif_sampled_records": None,
        "observed_species_count_sample": None,
        "observed_genera_count_sample": None,
        "observed_families_count_sample": None,
        "observed_orders_count_sample": None,
        "observed_kingdom_count_sample": None,
        "species_per_1000_records": None,
    }


async def main():
    environment_service = EnvironmentalDataService()
    soil_service = SoilGridsService()
    landcover_service = WorldCoverService()

    with INPUT.open(
        newline="",
        encoding="utf-8",
    ) as f:
        locations = list(csv.DictReader(f))

    print(
        f"Input locations: {len(locations)}"
    )
    print(
        f"Concurrency: {CONCURRENCY}"
    )
    print(
        f"Service timeout: {SERVICE_TIMEOUT}s"
    )
    print()
    print(
        "STAGE 1: NASA + SoilGrids + ESA WorldCover"
    )
    print(
        "GBIF will be collected separately for "
        "confirmed terrestrial locations."
    )
    print()

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def bounded(index, row):
        async with semaphore:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])

            print(
                f"[{index}/{len(locations)}] "
                f"{latitude:.2f}, {longitude:.2f}"
            )

            try:
                result = await fetch_one(
                    environment_service,
                    soil_service,
                    landcover_service,
                    latitude,
                    longitude,
                )

                label = result.get(
                    "land_cover_label"
                )
                terrestrial = result.get(
                    "is_terrestrial"
                )
                status = result.get(
                    "land_cover_status"
                )

                print(
                    f"    -> landcover={label} "
                    f"terrestrial={terrestrial} "
                    f"status={status}"
                )

                return result

            except Exception as exc:
                print(
                    f"    -> FAILED: "
                    f"{type(exc).__name__}: {exc}"
                )

                return {
                    "latitude": latitude,
                    "longitude": longitude,
                    "land_cover_status": "error",
                }

    results = await asyncio.gather(
        *(
            bounded(index, row)
            for index, row in enumerate(
                locations,
                start=1,
            )
        )
    )

    fieldnames = [
        "latitude",
        "longitude",

        "temperature_c",
        "temperature_max_c",
        "temperature_min_c",
        "temperature_range_c",
        "precipitation_mm_day",

        "soil_organic_carbon_g_per_kg",
        "soil_ph",
        "soil_source_distance_m",
        "soil_ph_source_distance_m",

        "land_cover_class",
        "land_cover_label",
        "is_terrestrial",
        "land_cover_status",

        "gbif_occurrence_records",
        "gbif_sampled_records",
        "observed_species_count_sample",
        "observed_genera_count_sample",
        "observed_families_count_sample",
        "observed_orders_count_sample",
        "observed_kingdom_count_sample",
        "species_per_1000_records",
    ]

    with OUTPUT.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(results)

    terrestrial = [
        r for r in results
        if r.get("is_terrestrial") is True
    ]

    non_terrestrial = [
        r for r in results
        if r.get("is_terrestrial") is False
    ]

    unknown = [
        r for r in results
        if r.get("is_terrestrial") is None
    ]

    available = [
        r for r in results
        if r.get("land_cover_status") == "available"
    ]

    print()
    print("========================================")
    print("STAGE 1 DATASET BUILD COMPLETE")
    print("========================================")
    print(
        f"Rows written:        {len(results)}"
    )
    print(
        f"LandCover available: {len(available)}"
    )
    print(
        f"Terrestrial rows:    {len(terrestrial)}"
    )
    print(
        f"Non-terrestrial:     {len(non_terrestrial)}"
    )
    print(
        f"Unknown:             {len(unknown)}"
    )
    print(
        f"Output:              {OUTPUT}"
    )
    print("========================================")
    print()
    print(
        "Next step: run GBIF only on confirmed "
        "terrestrial rows."
    )


if __name__ == "__main__":
    asyncio.run(main())
