"""
Land-use / land-cover normalization.

WHY THIS EXISTS
---------------
`EnvironmentalFeatureEngineer` classifies habitat condition against a
fixed vocabulary of ESA WorldCover-style class tokens (`cropland`,
`tree_cover`, `grassland`, ...). Free-text land use supplied through
chat or the API ("wheat monoculture", "rice paddy", "cattle pasture")
did not match that vocabulary, so it silently fell through to
`habitat_condition = "unknown"` and the habitat-related reasoning rules
never fired. This module closes that gap.

SCOPE CAVEAT
------------
ESA WorldCover is a land-COVER classification. Mapping a free-text
land-use description onto a cover class is an approximation: it tells
you the broad cover type, not field-level habitat quality, management
intensity, or vegetation structure. Anything derived from it is a
prototype indicator, not a habitat survey.
"""

from __future__ import annotations

#: Canonical land-cover classes. Aligned to ESA WorldCover v200 naming,
#: plus `agroforestry`, which WorldCover does not separate but which
#: behaves very differently from plain cropland for biodiversity.
CANONICAL_CLASSES = {
    "tree_cover",
    "shrubland",
    "grassland",
    "cropland",
    "agroforestry",
    "built_up",
    "bare_sparse_vegetation",
    "snow_ice",
    "permanent_water",
    "herbaceous_wetland",
    "mangroves",
    "moss_lichen",
}

#: Ordered longest-first at match time. Phrases are matched as
#: substrings of the lowercased land-use text.
_KEYWORD_MAP: dict[str, str] = {
    # --- agroforestry / mixed systems (checked before cropland) ----
    "agroforestry": "agroforestry",
    "silvopasture": "agroforestry",
    "alley cropping": "agroforestry",
    "shade grown": "agroforestry",
    "shade-grown": "agroforestry",
    "home garden": "agroforestry",
    "homegarden": "agroforestry",
    # --- cropland ---------------------------------------------------
    "monoculture": "cropland",
    "cropland": "cropland",
    "crop land": "cropland",
    "croplands": "cropland",
    "arable": "cropland",
    "farmland": "cropland",
    "agricultural land": "cropland",
    "agriculture": "cropland",
    "agricultural": "cropland",
    "plantation": "cropland",
    "orchard": "cropland",
    "vineyard": "cropland",
    "paddy": "cropland",
    "rice field": "cropland",
    "wheat": "cropland",
    "maize": "cropland",
    "corn": "cropland",
    "soybean": "cropland",
    "sugarcane": "cropland",
    "cotton": "cropland",
    "millet": "cropland",
    "sorghum": "cropland",
    "farm": "cropland",
    # --- tree cover -------------------------------------------------
    "mangrove": "mangroves",
    "tree cover": "tree_cover",
    "tree_cover": "tree_cover",
    "forest": "tree_cover",
    "woodland": "tree_cover",
    "woodlot": "tree_cover",
    "jungle": "tree_cover",
    # --- grass / pasture --------------------------------------------
    "grassland": "grassland",
    "grass land": "grassland",
    "pasture": "grassland",
    "rangeland": "grassland",
    "meadow": "grassland",
    "savanna": "grassland",
    "savannah": "grassland",
    "steppe": "grassland",
    "prairie": "grassland",
    "grazing": "grassland",
    # --- shrub ------------------------------------------------------
    "shrubland": "shrubland",
    "shrub": "shrubland",
    "scrub": "shrubland",
    "thicket": "shrubland",
    "chaparral": "shrubland",
    # --- wetland / water --------------------------------------------
    "wetland": "herbaceous_wetland",
    "marsh": "herbaceous_wetland",
    "swamp": "herbaceous_wetland",
    "peatland": "herbaceous_wetland",
    "bog": "herbaceous_wetland",
    "lake": "permanent_water",
    "river": "permanent_water",
    "reservoir": "permanent_water",
    # --- built / bare -----------------------------------------------
    "built up": "built_up",
    "built-up": "built_up",
    "built_up": "built_up",
    "urban": "built_up",
    "city": "built_up",
    "settlement": "built_up",
    "industrial": "built_up",
    "bare soil": "bare_sparse_vegetation",
    "barren": "bare_sparse_vegetation",
    "bare": "bare_sparse_vegetation",
    "desert": "bare_sparse_vegetation",
    "sparse vegetation": "bare_sparse_vegetation",
    # --- ice / lichen -----------------------------------------------
    "glacier": "snow_ice",
    "snow": "snow_ice",
    "ice": "snow_ice",
    "tundra": "moss_lichen",
    "lichen": "moss_lichen",
    "moss": "moss_lichen",
}

#: Management-intensity signals kept alongside the cover class. These
#: are NOT cover classes; they modulate habitat interpretation.
_INTENSITY_KEYWORDS = {
    "monoculture": "monoculture",
    "single crop": "monoculture",
    "continuous crop": "monoculture",
    "intensive": "intensive",
    "conventional": "intensive",
    "organic": "extensive",
    "rotational": "extensive",
    "mixed crop": "mixed",
    "intercrop": "mixed",
    "polyculture": "mixed",
}


def normalize_land_use(raw: str | None) -> dict[str, str | None]:
    """
    Map free-text land use onto a canonical land-cover class.

    Returns a dict with:
      raw                 : the original string, preserved verbatim
      land_cover_class    : canonical class, or None if unrecognised
      management_intensity: 'monoculture' | 'intensive' | 'extensive'
                            | 'mixed' | None
      normalization_note  : human-readable description of what was
                            assumed, for display in the API response

    Returning None rather than guessing is deliberate: an unrecognised
    land use must stay `unknown` downstream instead of being coerced
    into a class that drives recommendations.
    """
    if not raw or not str(raw).strip():
        return {
            "raw": raw,
            "land_cover_class": None,
            "management_intensity": None,
            "normalization_note": None,
        }

    text = str(raw).strip().lower().replace("_", " ")

    # Already canonical?
    direct = str(raw).strip().lower().replace(" ", "_")
    if direct in CANONICAL_CLASSES:
        return {
            "raw": raw,
            "land_cover_class": direct,
            "management_intensity": _detect_intensity(text),
            "normalization_note": None,
        }

    # Longest keyword first so "tree cover" beats "cover", and
    # "agroforestry" is reached before "forest".
    matched_class: str | None = None
    matched_keyword: str | None = None

    for keyword in sorted(_KEYWORD_MAP, key=len, reverse=True):
        if keyword in text:
            matched_class = _KEYWORD_MAP[keyword]
            matched_keyword = keyword
            break

    note = None
    if matched_class:
        note = (
            f"Land use '{raw}' was mapped to land-cover class "
            f"'{matched_class}' on the keyword '{matched_keyword}'. "
            "This is a cover-class approximation, not a habitat survey."
        )

    return {
        "raw": raw,
        "land_cover_class": matched_class,
        "management_intensity": _detect_intensity(text),
        "normalization_note": note,
    }


def _detect_intensity(text: str) -> str | None:
    for keyword in sorted(_INTENSITY_KEYWORDS, key=len, reverse=True):
        if keyword in text:
            return _INTENSITY_KEYWORDS[keyword]
    return None
