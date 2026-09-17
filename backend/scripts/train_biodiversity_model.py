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
