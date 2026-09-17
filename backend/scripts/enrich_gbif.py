from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from app.services.environment_data import EnvironmentalDataService


ROOT = Path(__file__).resolve().parents[1]

INPUT = ROOT / "data" / "environment_training.csv"
OUTPUT = ROOT / "data" / "environment_training_final.csv"

CONCURRENCY = 3
SERVICE_TIMEOUT = 30
RADIUS_KM = 10.0


async def fetch_gbif(
    service: EnvironmentalDataService,
    latitude: float,
    longitude: float,
):
    try:
        return await asyncio.wait_for(
            service.fetch_biodiversity(
                latitude,
                longitude,
                radius_km=RADIUS_KM,
            ),
            timeout=SERVICE_TIMEOUT,
        )

    except Exception as exc:
        print(
            f"    GBIF unavailable: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}


async def main():

    with INPUT.open(
        newline="",
        encoding="utf-8",
    ) as f:
        rows = list(csv.DictReader(f))

    terrestrial = [
        row
        for row in rows
        if row.get("is_terrestrial", "").lower()
        == "true"
    ]

    print(
        f"Input rows: {len(rows)}"
    )

    print(
        f"Confirmed terrestrial: "
        f"{len(terrestrial)}"
    )

    print()
    print(
        "STAGE 2: GBIF biodiversity enrichment"
    )
    print(
        f"Radius: {RADIUS_KM} km"
    )
    print(
        f"Concurrency: {CONCURRENCY}"
    )
    print()

    service = EnvironmentalDataService()

    semaphore = asyncio.Semaphore(
        CONCURRENCY
    )

    async def bounded(index, row):

        async with semaphore:

            latitude = float(
                row["latitude"]
            )

            longitude = float(
                row["longitude"]
            )

            print(
                f"[{index}/{len(terrestrial)}] "
                f"{latitude:.2f}, "
                f"{longitude:.2f}"
            )

            biodiversity = await fetch_gbif(
                service,
                latitude,
                longitude,
            )

            row["gbif_occurrence_records"] = (
                biodiversity.get(
                    "occurrence_records"
                )
            )

            row["gbif_sampled_records"] = (
                biodiversity.get(
                    "sampled_records"
                )
            )

            row["observed_species_count_sample"] = (
                biodiversity.get(
                    "observed_species_count_sample"
                )
            )

            row["observed_genera_count_sample"] = (
                biodiversity.get(
                    "observed_genera_count_sample"
                )
            )

            row["observed_families_count_sample"] = (
                biodiversity.get(
                    "observed_families_count_sample"
                )
            )

            row["observed_orders_count_sample"] = (
                biodiversity.get(
                    "observed_orders_count_sample"
                )
            )

            row["observed_kingdom_count_sample"] = (
                biodiversity.get(
                    "observed_kingdom_count_sample"
                )
            )

            row["species_per_1000_records"] = (
                biodiversity.get(
                    "species_per_1000_records"
                )
            )

            species = row.get(
                "observed_species_count_sample"
            )

            records = row.get(
                "gbif_occurrence_records"
            )

            print(
                f"    -> GBIF records={records} "
                f"observed_species={species}"
            )

            return row

    enriched = await asyncio.gather(
        *(
            bounded(index, row)
            for index, row in enumerate(
                terrestrial,
                start=1,
            )
        )
    )

    # Preserve only confirmed terrestrial rows
    # for the ML/environmental training dataset.
    fieldnames = list(
        enriched[0].keys()
    ) if enriched else []

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
        writer.writerows(enriched)

    gbif_success = sum(
        1
        for row in enriched
        if row.get(
            "observed_species_count_sample"
        ) not in ("", None)
    )

    print()
    print("========================================")
    print("STAGE 2 COMPLETE")
    print("========================================")
    print(
        f"Terrestrial rows: "
        f"{len(enriched)}"
    )
    print(
        f"GBIF enriched:    "
        f"{gbif_success}"
    )
    print(
        f"GBIF unavailable: "
        f"{len(enriched) - gbif_success}"
    )
    print(
        f"Output: {OUTPUT}"
    )
    print("========================================")


if __name__ == "__main__":
    asyncio.run(main())
