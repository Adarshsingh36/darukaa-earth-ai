from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from app.services.environment_data import EnvironmentalDataService


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "training_locations.csv"
OUTPUT = ROOT / "data" / "environment_training.csv"


async def main():
    service = EnvironmentalDataService()
    rows = []

    with INPUT.open(newline="", encoding="utf-8-sig") as f:
        locations = list(csv.DictReader(f))

    if not locations:
        raise RuntimeError("No training locations found.")

    required_columns = {"latitude", "longitude"}
    actual_columns = set(locations[0].keys())

    missing = required_columns - actual_columns
    if missing:
        raise RuntimeError(
            f"Training locations missing columns: {sorted(missing)}"
        )

    for i, item in enumerate(locations, start=1):
        lat = float(item["latitude"])
        lon = float(item["longitude"])

        print(
            f"[{i}/{len(locations)}] "
            f"{lat}, {lon}",
            flush=True,
        )

        try:
            data = await service.enrich_location(
                lat,
                lon,
                radius_km=10,
            )

            climate = data["climate"]
            biodiversity = data["biodiversity"]

            rows.append({
                "latitude": lat,
                "longitude": lon,

                # Climate features
                "temperature_c": climate.get("temperature_c"),
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

                # Biodiversity observation features
                "gbif_occurrence_records": biodiversity.get(
                    "occurrence_records"
                ),
                "gbif_sampled_records": biodiversity.get(
                    "sampled_records"
                ),
                "observed_species_count_sample": biodiversity.get(
                    "observed_species_count_sample"
                ),
                "observed_genera_count_sample": biodiversity.get(
                    "observed_genera_count_sample"
                ),
                "observed_families_count_sample": biodiversity.get(
                    "observed_families_count_sample"
                ),
                "observed_orders_count_sample": biodiversity.get(
                    "observed_orders_count_sample"
                ),
                "observed_kingdom_count_sample": biodiversity.get(
                    "observed_kingdom_count_sample"
                ),
                "species_per_1000_records": biodiversity.get(
                    "species_per_1000_records"
                ),
            })

        except Exception as exc:
            print(
                f"  skipped: {type(exc).__name__}: {exc}",
                flush=True,
            )

    if not rows:
        raise RuntimeError(
            "No training rows were collected."
        )

    fieldnames = list(rows[0].keys())

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
        f"Wrote {len(rows)} rows to {OUTPUT}"
    )


if __name__ == "__main__":
    asyncio.run(main())
