"""
Explicit unit normalization for environmental variables.

CANONICAL INTERNAL UNITS
------------------------
soil_organic_carbon_g_per_kg : g/kg
precipitation_mm_day         : mm/day
soil_moisture                : % (volumetric or gravimetric, caller-defined)
temperature_c                : degrees Celsius

SCIENTIFIC ASSUMPTIONS
----------------------
1. SOC mass fraction: 1% SOC == 10 g/kg by definition
   (1 g C per 100 g soil == 10 g C per 1000 g soil).

2. Annual precipitation -> mean daily precipitation uses a 365.0 day
   year. This is a MEAN, not a daily observation. It deliberately
   discards seasonality, which matters a great deal in monsoonal and
   Mediterranean climates. Downstream water-stress indicators built on
   this mean are prototype indicators only.

3. Ambiguous external field names (`soil_organic_carbon`, `rainfall_mm`)
   are accepted ONLY at the boundary, in `normalize_external_payload`,
   and are converted immediately. They never enter the internal model.
"""

from __future__ import annotations

from typing import Any

# 1% SOC by mass == 10 g/kg
SOC_PERCENT_TO_G_PER_KG = 10.0

# Mean-daily conversion basis. 365.0 (not 365.25) so that the documented
# demo case 600 mm/yr -> 1.6438 mm/day holds exactly.
DAYS_PER_YEAR = 365.0


class UnitConversionError(ValueError):
    """Raised when a value cannot be normalized to a canonical unit."""


def soc_to_g_per_kg(value: float, unit: str | None) -> float:
    """
    Normalize soil organic carbon to g/kg.

    >>> soc_to_g_per_kg(0.58, "%")
    5.8
    >>> soc_to_g_per_kg(5.8, "g/kg")
    5.8
    """
    normalized_unit = _clean_unit(unit)

    if normalized_unit in {"%", "percent", "pct"}:
        return round(value * SOC_PERCENT_TO_G_PER_KG, 6)

    if normalized_unit in {"g/kg", "gkg", "gperkg", ""}:
        # Bare numbers are assumed to already be g/kg, because g/kg is
        # the canonical unit. See `infer_soc_unit` for the heuristic used
        # when parsing free text, where bare numbers are riskier.
        return round(float(value), 6)

    if normalized_unit in {"g/100g", "g/100 g"}:
        return round(value * SOC_PERCENT_TO_G_PER_KG, 6)

    raise UnitConversionError(
        f"Unsupported soil organic carbon unit: {unit!r}"
    )


def infer_soc_unit(value: float, unit: str | None) -> str:
    """
    Decide the unit of a free-text SOC value when none was written.

    Heuristic, and flagged as such: agricultural topsoil SOC is roughly
    2-60 g/kg, i.e. 0.2-6%. A bare value <= 2.0 is far more likely to be
    a percentage than a g/kg reading, since 2 g/kg topsoil is close to
    the degradation floor and is rarely quoted casually.

    This heuristic is applied ONLY to free-text chat parsing. Structured
    API input is never reinterpreted.
    """
    explicit = _clean_unit(unit)
    if explicit:
        return explicit

    if value <= 2.0:
        return "%"

    return "g/kg"


def rainfall_to_mm_day(value: float, unit: str | None) -> float:
    """
    Normalize precipitation to mm/day.

    >>> rainfall_to_mm_day(1.2, "mm/day")
    1.2
    >>> round(rainfall_to_mm_day(600, "mm/year"), 4)
    1.6438
    """
    normalized_unit = _clean_unit(unit)

    if normalized_unit in {"mm/day", "mmday", "mmd", "mm/d"}:
        return round(float(value), 6)

    if normalized_unit in {
        "mm/year",
        "mm/yr",
        "mm/annum",
        "mmyear",
        "mmyr",
        "mm/a",
    }:
        return round(value / DAYS_PER_YEAR, 6)

    if normalized_unit in {"mm/month", "mm/mo", "mmmonth"}:
        return round(value / (DAYS_PER_YEAR / 12.0), 6)

    if normalized_unit in {"mm", ""}:
        raise UnitConversionError(
            "Bare 'mm' is ambiguous for precipitation. Use "
            "infer_rainfall_unit() at a text-parsing boundary, or "
            "supply mm/day or mm/year explicitly."
        )

    raise UnitConversionError(
        f"Unsupported precipitation unit: {unit!r}"
    )


def infer_rainfall_unit(value: float, unit: str | None) -> str:
    """
    Resolve a bare or missing precipitation unit at a text boundary.

    Rule, stated explicitly so it is auditable:
      * an explicit unit always wins
      * a bare value >= 50 is treated as an ANNUAL total in mm/year,
        because 50 mm/day sustained is physically implausible as a
        long-run mean (that would be 18 m of rain per year)
      * a bare value < 50 is treated as mm/day

    Never silently treat an annual total as a daily rate.
    """
    explicit = _clean_unit(unit)

    if explicit and explicit not in {"mm"}:
        return explicit

    if value >= 50:
        return "mm/year"

    return "mm/day"


# --------------------------------------------------------------------
# External alias handling
# --------------------------------------------------------------------
# `EnvironmentalInput` uses ConfigDict(extra="forbid"), so ambiguous
# names must be stripped BEFORE model construction, not after.

#: external alias -> (canonical field, assumed unit)
EXTERNAL_ALIASES: dict[str, tuple[str, str | None]] = {
    "soil_organic_carbon": ("soil_organic_carbon_g_per_kg", "g/kg"),
    "soc": ("soil_organic_carbon_g_per_kg", "g/kg"),
    "soc_g_per_kg": ("soil_organic_carbon_g_per_kg", "g/kg"),
    "soc_percent": ("soil_organic_carbon_g_per_kg", "%"),
    "soil_organic_carbon_percent": (
        "soil_organic_carbon_g_per_kg",
        "%",
    ),
    "rainfall_mm": ("precipitation_mm_day", "mm/year"),
    "annual_rainfall_mm": ("precipitation_mm_day", "mm/year"),
    "precipitation_mm_year": ("precipitation_mm_day", "mm/year"),
    "rainfall_mm_day": ("precipitation_mm_day", "mm/day"),
    "precipitation": ("precipitation_mm_day", "mm/day"),
    "temperature": ("temperature_c", None),
    "temp_c": ("temperature_c", None),
    "ph": ("soil_ph", None),
    "lat": ("latitude", None),
    "lon": ("longitude", None),
    "lng": ("longitude", None),
}


def normalize_external_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """
    Convert an external/legacy payload into canonical fields+units.

    Returns (canonical_payload, conversion_notes). Every conversion is
    reported so the API can show the user what was assumed rather than
    silently reinterpreting their numbers.
    """
    canonical: dict[str, Any] = {}
    notes: list[str] = []

    for key, value in payload.items():
        if value is None:
            continue

        lowered = key.lower().strip()

        if lowered not in EXTERNAL_ALIASES:
            canonical[key] = value
            continue

        field, assumed_unit = EXTERNAL_ALIASES[lowered]

        if field == "soil_organic_carbon_g_per_kg":
            converted = soc_to_g_per_kg(float(value), assumed_unit)
        elif field == "precipitation_mm_day":
            converted = rainfall_to_mm_day(float(value), assumed_unit)
        else:
            converted = value

        canonical[field] = converted

        if assumed_unit and converted != value:
            notes.append(
                f"'{key}' was read as {value} {assumed_unit} and "
                f"normalized to {converted} "
                f"({_canonical_unit_label(field)})."
            )

    return canonical, notes


def _canonical_unit_label(field: str) -> str:
    return {
        "soil_organic_carbon_g_per_kg": "g/kg",
        "precipitation_mm_day": "mm/day",
        "soil_moisture": "%",
        "temperature_c": "degC",
    }.get(field, "canonical unit")


def _clean_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    return (
        unit.strip()
        .lower()
        .replace(" ", "")
        .replace("°", "")
    )
