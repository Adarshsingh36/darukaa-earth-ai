from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "training_locations.csv"

# Broad India sampling grid.
# These are spatial sampling points for model development,
# not administrative boundaries or ecological classifications.
LATITUDES = [
    8.5, 11.0, 13.5, 16.0, 18.5,
    21.0, 23.5, 26.0, 28.5, 31.0, 33.5
]

LONGITUDES = [
    69.0, 72.0, 75.0, 78.0,
    81.0, 84.0, 87.0, 90.0
]

rows = []

for lat in LATITUDES:
    for lon in LONGITUDES:
        rows.append({
            "latitude": lat,
            "longitude": lon,
        })

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["latitude", "longitude"]
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {len(rows)} spatial sampling locations to:")
print(OUTPUT)