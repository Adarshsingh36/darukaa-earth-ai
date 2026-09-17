
$ErrorActionPreference = "Stop"

$Root = (Get-Location).Path
if (-not (Test-Path ".\backend\app\main.py")) {
    throw "Run this script from C:\Users\Adarsh Singh\Downloads\darukaa-earth-ai"
}

$Backend = Join-Path $Root "backend"
$App = Join-Path $Backend "app"
$Services = Join-Path $App "services"
$Api = Join-Path $App "api"
$Data = Join-Path $Backend "data"
$Scripts = Join-Path $Backend "scripts"
$Models = Join-Path $App "models"

New-Item -ItemType Directory -Force -Path $Services,$Api,$Data,$Scripts,$Models | Out-Null

$requirements = Join-Path $Backend "requirements.txt"
if (Test-Path $requirements) {
    $req = Get-Content $requirements -Raw
    foreach ($pkg in @("httpx>=0.27,<1","scikit-learn>=1.5,<2","joblib>=1.4,<2")) {
        $name = ($pkg -split "[<>=]")[0]
        if ($req -notmatch "(?m)^$([regex]::Escape($name))([<>=]|$)") {
            Add-Content -Path $requirements -Value $pkg
        }
    }
}

@'
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
    """

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    async def fetch_climate(self, latitude: float, longitude: float) -> dict[str, Any]:
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
            # Climatology responses are keyed by month/day depending on endpoint.
            nums = [float(v) for v in values.values() if isinstance(v, (int, float))]
            return round(sum(nums) / len(nums), 3) if nums else None

        return {
            "temperature_c": scalar("T2M"),
            "temperature_max_c": scalar("T2M_MAX"),
            "temperature_min_c": scalar("T2M_MIN"),
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
            "geo_distance": f"{radius_km}km,{latitude},{longitude}",
            "has_coordinate": "true",
            "has_geospatial_issue": "false",
            "occurrence_status": "PRESENT",
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
        kingdoms = {
            item.get("kingdom")
            for item in results
            if item.get("kingdom")
        }

        return {
            "occurrence_records": payload.get("count", 0),
            "observed_species_count_sample": len(species_keys),
            "observed_kingdom_count_sample": len(kingdoms),
            "radius_km": radius_km,
            "source": "GBIF",
            "retrieved_at": date.today().isoformat(),
            "interpretation": (
                "Observed GBIF records/species are biodiversity observation "
                "proxies, not a complete census of local biodiversity."
            ),
        }

    async def enrich_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
    ) -> dict[str, Any]:
        climate, biodiversity = await self._gather(
            latitude, longitude, radius_km
        )
        return {
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "climate": climate,
            "biodiversity": biodiversity,
            "data_sources": [
                {
                    "name": "NASA POWER",
                    "type": "live_api",
                    "variables": [
                        "T2M",
                        "T2M_MAX",
                        "T2M_MIN",
                        "PRECTOTCORR",
                    ],
                },
                {
                    "name": "GBIF",
                    "type": "live_api",
                    "variables": [
                        "occurrence_records",
                        "observed_species_count_sample",
                    ],
                },
            ],
        }

    async def _gather(self, latitude: float, longitude: float, radius_km: float):
        import asyncio

        return await asyncio.gather(
            self.fetch_climate(latitude, longitude),
            self.fetch_biodiversity(latitude, longitude, radius_km),
        )
'@ | Set-Content -Encoding UTF8 (Join-Path $Services "environment_data.py")

@'
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=10.0, gt=0, le=50)


class LocationResponse(BaseModel):
    location: dict[str, float]
    climate: dict[str, Any]
    biodiversity: dict[str, Any]
    data_sources: list[dict[str, Any]]
'@ | Set-Content -Encoding UTF8 (Join-Path $Models "environment.py")

@'
from fastapi import APIRouter, HTTPException

from app.models.environment import LocationRequest, LocationResponse
from app.services.environment_data import EnvironmentalDataService


router = APIRouter(prefix="/environment", tags=["environment"])
service = EnvironmentalDataService()


@router.post("/location", response_model=LocationResponse)
async def enrich_location(req: LocationRequest):
    try:
        return await service.enrich_location(
            req.latitude,
            req.longitude,
            req.radius_km,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Environmental data acquisition failed: {exc}",
        ) from exc
'@ | Set-Content -Encoding UTF8 (Join-Path $Api "environment.py")

$main = Join-Path $App "main.py"
$mainText = Get-Content $main -Raw
if ($mainText -notmatch "app\.api\.environment") {
    $mainText = "from app.api.environment import router as environment_router`r`n" + $mainText
}
if ($mainText -notmatch "environment_router") {
    $mainText += "`r`napp.include_router(environment_router)`r`n"
} elseif ($mainText -notmatch "include_router\(environment_router\)") {
    $mainText += "`r`napp.include_router(environment_router)`r`n"
}
Set-Content -Encoding UTF8 $main $mainText

@'
# Real-data training pipeline

This folder is intentionally based on live public environmental APIs rather than
invented training rows.

1. Put sampling coordinates in `backend/data/training_locations.csv`:
   latitude,longitude
2. Run:
   python scripts/build_training_dataset.py
3. Then:
   python scripts/train_biodiversity_model.py

The target is `observed_species_count_sample`, a GBIF observation proxy.
It must not be described as a complete local species census.
'@ | Set-Content -Encoding UTF8 (Join-Path $Data "README.md")

@'
latitude,longitude
19.033,73.029
19.076,72.877
18.5204,73.8567
19.9975,73.7898
20.5937,78.9629
23.2599,77.4126
28.6139,77.2090
13.0827,80.2707
12.9716,77.5946
17.3850,78.4867
'@ | Set-Content -Encoding UTF8 (Join-Path $Data "training_locations.csv")

@'
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

    with INPUT.open(newline="", encoding="utf-8") as f:
        locations = list(csv.DictReader(f))

    for i, item in enumerate(locations, start=1):
        lat = float(item["latitude"])
        lon = float(item["longitude"])
        print(f"[{i}/{len(locations)}] {lat}, {lon}")

        try:
            data = await service.enrich_location(lat, lon, radius_km=10)
            climate = data["climate"]
            biodiversity = data["biodiversity"]

            rows.append({
                "latitude": lat,
                "longitude": lon,
                "temperature_c": climate.get("temperature_c"),
                "temperature_max_c": climate.get("temperature_max_c"),
                "temperature_min_c": climate.get("temperature_min_c"),
                "precipitation_mm_day": climate.get("precipitation_mm_day"),
                "gbif_occurrence_records": biodiversity.get("occurrence_records"),
                "observed_species_count_sample": biodiversity.get(
                    "observed_species_count_sample"
                ),
                "observed_kingdom_count_sample": biodiversity.get(
                    "observed_kingdom_count_sample"
                ),
            })
        except Exception as exc:
            print(f"  skipped: {exc}")

    if not rows:
        raise RuntimeError("No training rows were collected.")

    fieldnames = list(rows[0].keys())
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
'@ | Set-Content -Encoding UTF8 (Join-Path $Scripts "build_training_dataset.py")

@'
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "environment_training.csv"
MODEL_DIR = ROOT / "app" / "models"
MODEL_PATH = MODEL_DIR / "biodiversity_proxy.joblib"
METRICS_PATH = MODEL_DIR / "biodiversity_proxy_metrics.json"

FEATURES = [
    "temperature_c",
    "temperature_max_c",
    "temperature_min_c",
    "precipitation_mm_day",
]

TARGET = "observed_species_count_sample"


def main():
    df = pd.read_csv(DATASET)
    df = df.dropna(subset=FEATURES + [TARGET])

    if len(df) < 8:
        raise RuntimeError(
            "Need at least 8 complete real API samples before training."
        )

    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=250,
        random_state=42,
        min_samples_leaf=2,
    )
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, predictions)),
        "r2": float(r2_score(y_test, predictions)),
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "target": TARGET,
        "target_definition": (
            "GBIF observed species count in a 10 km search radius; "
            "observation proxy, not complete species richness."
        ),
        "features": FEATURES,
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"Model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
'@ | Set-Content -Encoding UTF8 (Join-Path $Scripts "train_biodiversity_model.py")

Write-Host ""
Write-Host "Phase 1 installed."
Write-Host "Next commands:"
Write-Host "  cd backend"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  pip install -r requirements.txt"
Write-Host "  python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload"
Write-Host ""
Write-Host "Then test POST /environment/location with coordinates."
Write-Host "Do NOT train yet if the live endpoint is failing."
