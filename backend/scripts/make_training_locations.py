import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "training_locations.csv"

locations = [
    # Western / northwestern drylands
    (11.5, 72.5),
    (14.5, 73.5),
    (17.0, 73.5),
    (19.5, 72.5),
    (22.0, 72.5),
    (24.5, 70.5),
    (27.0, 72.5),
    (29.5, 74.5),

    # Central / Deccan
    (15.5, 75.5),
    (18.0, 75.5),
    (20.5, 77.5),
    (22.5, 77.5),
    (24.5, 77.5),
    (26.5, 78.5),
    (28.5, 78.5),
    (30.5, 78.5),

    # Southern India
    (10.5, 76.5),
    (12.5, 76.5),
    (14.5, 76.5),
    (10.5, 79.5),
    (12.5, 79.5),
    (14.5, 79.5),
    (16.5, 79.5),
    (18.5, 79.5),

    # Eastern India
    (18.5, 82.5),
    (20.5, 82.5),
    (22.5, 82.5),
    (24.5, 82.5),
    (20.5, 85.5),
    (22.5, 85.5),
    (24.5, 85.5),
    (26.5, 85.5),

    # Indo-Gangetic region
    (25.5, 77.5),
    (27.5, 79.5),
    (29.5, 81.5),
    (27.5, 82.5),
    (29.5, 83.5),
    (26.5, 84.5),

    # Northeast
    (24.5, 90.5),
    (25.5, 91.5),
    (26.5, 91.5),
    (27.5, 93.5),
    (25.5, 94.5),
    (27.5, 95.5),

    # Himalayan / northern transition
    (30.5, 77.5),
    (31.5, 78.5),
    (32.5, 79.5),
    (30.5, 81.5),
    (31.5, 82.5),
    (32.5, 84.5),
]

with OUTPUT.open(
    "w",
    newline="",
    encoding="utf-8",
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["latitude", "longitude"],
    )
    writer.writeheader()

    for latitude, longitude in locations:
        writer.writerow({
            "latitude": latitude,
            "longitude": longitude,
        })

print(f"Wrote {len(locations)} locations to {OUTPUT}")
