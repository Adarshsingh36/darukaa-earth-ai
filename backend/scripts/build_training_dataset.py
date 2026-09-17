from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from app.services.environment_data import EnvironmentalDataService
from app.services.soil_data import SoilGridsService


ROOT = Path(__file__).resolve().parents[1]

INPUT = ROOT / "data" / "training_locations.csv"
OUTPUT = ROOT / "data" / "environment_training.csv"


async def main():

    climate_service = EnvironmentalDataService()
    soil_service = SoilGridsService()

    with INPUT.open(
        newline="",
        encoding="utf-8-sig",
    ) as f:
        locations = list(csv.DictReader(f))

    if not locations:
        raise RuntimeError(
            "No training locations found."
        )

    rows = []

    total = len(locations)

    for i, item in enumerate(
        locations,
        start=1,
    ):

        latitude = float(
            item["latitude"]
        )

        longitude = float(
            item["longitude"]
        )

        print(
            f"[{i}/{total}] "
            f"{latitude}, {longitude}",
            flush=True,
        )

        try:

            climate, biodiversity, soil = (
                await asyncio.gather(
                    climate_service.fetch_climate(
                        latitude,
                        longitude,
                    ),
                    climate_service.fetch_biodiversity(
                        latitude,
                        longitude,
                        radius_km=10,
                    ),
                    soil_service.fetch_soil(
                        latitude,
                        longitude,
                    ),
                )
            )

            rows.append(
                {
                    "latitude": latitude,
                    "longitude": longitude,

                    # Climate
                    "temperature_c":
                        climate.get(
                            "temperature_c"
                        ),

                    "temperature_max_c":
                        climate.get(
                            "temperature_max_c"
                        ),

                    "temperature_min_c":
                        climate.get(
                            "temperature_min_c"
                        ),

                    "temperature_range_c":
                        climate.get(
                            "temperature_range_c"
                        ),

                    "precipitation_mm_day":
                        climate.get(
                            "precipitation_mm_day"
                        ),

                    # Soil
                    "soil_organic_carbon_g_per_kg":
                        soil.get(
                            "soil_organic_carbon_g_per_kg"
                        ),

                    "soil_ph":
                        soil.get(
                            "soil_ph"
                        ),

                    "soil_source_distance_m":
                        soil.get(
                            "soc_source_distance_m"
                        ),

                    "soil_ph_source_distance_m":
                        soil.get(
                            "ph_source_distance_m"
                        ),

                    # Biodiversity observation proxy
                    "gbif_occurrence_records":
                        biodiversity.get(
                            "occurrence_records"
                        ),

                    "gbif_sampled_records":
                        biodiversity.get(
                            "sampled_records"
                        ),

                    "observed_species_count_sample":
                        biodiversity.get(
                            "observed_species_count_sample"
                        ),

                    "observed_genera_count_sample":
                        biodiversity.get(
                            "observed_genera_count_sample"
                        ),

                    "observed_families_count_sample":
                        biodiversity.get(
                            "observed_families_count_sample"
                        ),

                    "observed_orders_count_sample":
                        biodiversity.get(
                            "observed_orders_count_sample"
                        ),

                    "observed_kingdom_count_sample":
                        biodiversity.get(
                            "observed_kingdom_count_sample"
                        ),

                    "species_per_1000_records":
                        biodiversity.get(
                            "species_per_1000_records"
                        ),
                }
            )

        except Exception as exc:

            print(
                f"  skipped: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    if not rows:
        raise RuntimeError(
            "No training rows were collected."
        )

    fieldnames = list(
        rows[0].keys()
    )

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
        writer.writerows(rows)

    print()
    print(
        f"Wrote {len(rows)} rows to:"
    )
    print(OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
