"""
Reference distribution from `data/environment_training_final.csv`.

WHAT THIS IS FOR
----------------
Section 20 of the project brief lists the training dataset as something
that "must remain usable" and flags calibrating the prototype
thresholds against it as future work. This module makes the dataset
usable for that purpose without doing the calibration itself.

WHY IT DOES NOT SILENTLY RECALIBRATE THE THRESHOLDS
----------------------------------------------------
The 43 locations are a convenience sample assembled for pipeline
testing, not a stratified or representative global sample: the median
precipitation here is 2.78 mm/day and the median SOC is 12.8 g/kg,
which describes a bias toward well-watered, higher-carbon sites. Fixed
thresholds in `feature_engineering.py` are calibrated to flag
DEGRADED/stressed conditions (e.g. rainfall < 1.0 mm/day, SOC <
5 g/kg) - conditions this convenience sample mostly does not contain.
Refitting the thresholds to this sample's percentiles would make the
system LESS sensitive to genuine degradation, not more accurate, and
would misrepresent 43 opportunistic points as an ecological standard.
See `scripts/threshold_audit.py` for the actual numbers.

What this module DOES provide: for a given observation, where does it
fall relative to this specific reference set. That is a different,
weaker claim than "this value is stressed", and it is presented as
such - as context, alongside the threshold-based classification, never
in place of it.
"""

from __future__ import annotations

import csv
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[2]
DATASET_PATH = BASE / "data" / "environment_training_final.csv"

#: Fields this module can contextualize. Restricted to columns that
#: exist in both the canonical schema and the CSV.
SUPPORTED_FIELDS = (
    "temperature_c",
    "precipitation_mm_day",
    "soil_organic_carbon_g_per_kg",
    "soil_ph",
)


class ReferenceDataset:
    """
    Lazily-loaded, cached view of the training locations dataset.

    Percentile lookups only; this is deliberately NOT a model. Fitting
    anything predictive to 43 points would overstate what the sample
    supports.
    """

    def __init__(self, path: Path = DATASET_PATH):
        self.path = path
        self._sorted: dict[str, list[float]] | None = None
        self._error: str | None = None

    # ----------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._sorted is not None or self._error is not None:
            return

        try:
            with self.path.open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            self._sorted = {}
            return

        columns: dict[str, list[float]] = {
            field: [] for field in SUPPORTED_FIELDS
        }

        for row in rows:
            for field in SUPPORTED_FIELDS:
                raw = row.get(field)
                if raw in (None, ""):
                    continue
                try:
                    columns[field].append(float(raw))
                except ValueError:
                    continue

        self._sorted = {
            field: sorted(values)
            for field, values in columns.items()
        }

    # ----------------------------------------------------------------
    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._error is None and any(
            self._sorted.values()
        )

    # ----------------------------------------------------------------
    def sample_size(self, field: str) -> int:
        self._ensure_loaded()
        return len((self._sorted or {}).get(field, []))

    # ----------------------------------------------------------------
    def describe(self, field: str) -> dict[str, Any] | None:
        """Five-number summary for one field, or None if unavailable."""
        self._ensure_loaded()
        values = (self._sorted or {}).get(field)

        if not values:
            return None

        n = len(values)

        return {
            "n": n,
            "min": values[0],
            "p25": _percentile(values, 25),
            "median": _percentile(values, 50),
            "p75": _percentile(values, 75),
            "max": values[-1],
        }

    # ----------------------------------------------------------------
    def percentile_rank(
        self, field: str, value: float
    ) -> dict[str, Any] | None:
        """
        Where `value` falls within this reference set for `field`.

        Returns None if the field is unsupported or the dataset could
        not be loaded, so a caller can distinguish "no context
        available" from "this is the 0th percentile".
        """
        self._ensure_loaded()
        values = (self._sorted or {}).get(field)

        if not values:
            return None

        n = len(values)

        # Midpoint of the tie range, so a value equal to several
        # reference points lands at the centre of that tie rather
        # than its edge.
        lower = bisect_left(values, value)
        upper = bisect_right(values, value)
        rank = (lower + upper) / 2.0

        percentile = round(100.0 * rank / n, 1)

        return {
            "percentile": percentile,
            "reference_n": n,
            "reference_median": _percentile(values, 50),
            "note": (
                f"This value sits at roughly the "
                f"{_ordinal(round(percentile))} percentile of the "
                f"{n}-location reference dataset. The dataset is a "
                "convenience sample assembled for pipeline testing, "
                "not a representative global sample, so this "
                "describes relative position only and is not itself "
                "a stress classification."
            ),
        }


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list."""
    n = len(sorted_values)
    index = min(n - 1, max(0, int(round(pct / 100.0 * (n - 1)))))
    return sorted_values[index]


#: Module-level singleton. The CSV is small (43 rows); reloading it
#: per request would be wasteful for no benefit.
reference_dataset = ReferenceDataset()
