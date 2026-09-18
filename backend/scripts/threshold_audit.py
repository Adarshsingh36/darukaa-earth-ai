"""
Audits the fixed prototype thresholds in `feature_engineering.py`
against the distribution of `data/environment_training_final.csv`.

This is a reporting tool, not a calibration tool. It exists to make an
informed decision possible - "should these thresholds change" - rather
than to make that decision automatically. See
`app/services/reference_stats.py` for why an automatic refit would be
a scientific overreach: the dataset is a 43-point convenience sample,
not a stratified reference for global ecological stress.

Run from `backend/`:

    python -m scripts.threshold_audit
"""

from __future__ import annotations

from app.services.reference_stats import reference_dataset

#: (field, current threshold description, boundary values to locate)
THRESHOLDS = [
    (
        "precipitation_mm_day",
        "water_stress: high < 1.0 < moderate < 2.0 < low",
        [1.0, 2.0],
    ),
    (
        "temperature_c",
        "thermal_stress: high <5 or >35, moderate <10 or >30",
        [5.0, 10.0, 30.0, 35.0],
    ),
    (
        "soil_organic_carbon_g_per_kg",
        "soil_carbon_condition: high_stress <5, moderate_stress <10",
        [5.0, 10.0],
    ),
    (
        "soil_ph",
        "soil_ph_condition: high_stress <5.5 or >8.0, "
        "moderate_stress <6.0 or >7.5",
        [5.5, 6.0, 7.5, 8.0],
    ),
]


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def main() -> None:
    if not reference_dataset.available:
        print(
            "Reference dataset unavailable at "
            f"{reference_dataset.path} - nothing to audit."
        )
        return

    print(
        "Threshold audit against "
        f"{reference_dataset.path.name}\n"
        + "=" * 72
    )

    for field, rule_description, boundaries in THRESHOLDS:
        summary = reference_dataset.describe(field)

        if not summary:
            print(f"\n{field}: no data in reference set.")
            continue

        print(f"\n{field}")
        print(f"  rule:       {rule_description}")
        print(
            "  reference:  n={n}  min={min:.2f}  p25={p25:.2f}  "
            "median={median:.2f}  p75={p75:.2f}  max={max:.2f}".format(
                **summary
            )
        )

        for boundary in boundaries:
            position = reference_dataset.percentile_rank(
                field, boundary
            )
            if position:
                pct = position["percentile"]
                suffix = _ordinal_suffix(round(pct))
                print(
                    f"  boundary {boundary:>6}: sits at the "
                    f"{pct:.0f}{suffix} percentile of "
                    "the reference set"
                )

    print(
        "\n"
        + "=" * 72
        + "\nReading this report:\n"
        "  A rule boundary sitting at a LOW percentile (well below "
        "the reference median) means the reference dataset mostly "
        "describes conditions milder than what the rule calls "
        "'stressed' - which is what you want from a threshold meant "
        "to catch degraded sites, given a reference sample skewed "
        "toward well-watered, higher-carbon locations.\n"
        "  A boundary sitting ABOVE the reference median would mean "
        "most of this reference sample gets flagged as stressed by "
        "the current rule - worth a closer look, though still not "
        "proof the threshold is wrong, since the sample itself may "
        "simply not represent degraded sites well.\n"
        "  Either way: refitting a threshold to match this sample's "
        "own percentiles would tune the system to behave like this "
        "convenience sample, not like the ecology the threshold is "
        "meant to describe. Treat this report as a prompt to check "
        "primary literature for that variable, not as the answer."
    )


if __name__ == "__main__":
    main()
