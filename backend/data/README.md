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
