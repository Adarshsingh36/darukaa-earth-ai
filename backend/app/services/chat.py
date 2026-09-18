"""
Natural-language environmental parsing and conversation memory.

The parser is deliberately deterministic (regex + unit rules), not an
LLM call. Extracting a measurement is a place where a hallucinated
number would be silently wrong, so it stays rule-based and testable.

Every numeric extraction records how the unit was resolved, so the API
can tell the user "I read 600 mm as an annual total" instead of
quietly converting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.schemas import EnvironmentalInput
from app.services import units as U
from app.services.land_cover import normalize_land_use


class ConversationMemory:
    """
    Multi-turn store of messages plus accumulated environmental state.

    Environmental values accumulate across turns so that a user never
    has to repeat a variable they have already given.
    """

    def __init__(self):
        self.sessions: dict[str, dict] = {}

    def get(self, cid: str) -> dict:
        return self.sessions.setdefault(
            cid,
            {
                "messages": [],
                "environment": {},
                "notes": [],
            },
        )

    def update(
        self,
        cid: str,
        env: EnvironmentalInput | dict | None,
        notes: list[str] | None = None,
    ) -> dict:
        session = self.get(cid)

        if env:
            if isinstance(env, EnvironmentalInput):
                values = env.model_dump(exclude_none=True)
            else:
                values = {
                    key: value
                    for key, value in env.items()
                    if value is not None
                }

            session["environment"].update(values)

        if notes:
            session["notes"].extend(notes)

        return session

    def add_message(self, cid: str, role: str, text: str) -> None:
        self.get(cid)["messages"].append(
            {"role": role, "content": text}
        )

    def history(self, cid: str) -> list[dict]:
        return self.get(cid)["messages"]

    def reset(self, cid: str) -> None:
        self.sessions.pop(cid, None)


memory = ConversationMemory()


@dataclass
class ParsedMessage:
    """Result of parsing one user message."""

    values: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_input(self) -> EnvironmentalInput:
        return EnvironmentalInput(**self.values)

    def __bool__(self) -> bool:
        return bool(self.values)


# Number pattern reused throughout.
_NUM = r"(-?\d+(?:\.\d+)?)"

# Unit fragments.
_SOC_UNIT = r"(%|percent|g\s*/?\s*kg|g\s*per\s*kg|gkg)"
_RAIN_UNIT = (
    r"(mm\s*/?\s*(?:day|d)\b|mm\s*per\s*day|"
    r"mm\s*/?\s*(?:year|yr|a)\b|mm\s*per\s*year|"
    r"mm\s*/?\s*(?:month|mo)\b|mm)"
)

_SOC_WORDS = r"(?:soc|soil\s+organic\s+carbon|organic\s+carbon)"
_RAIN_WORDS = (
    r"(?:annual\s+rainfall|annual\s+precipitation|yearly\s+rainfall|"
    r"mean\s+annual\s+precipitation|rainfall|precipitation|rain)"
)


class ChatParser:
    """
    Extract canonical environmental variables from free text.

    Handles both orders:
        "SOC is 0.58%"        (keyword then value)
        "0.58% SOC"           (value then keyword)
    """

    def parse(self, text: str) -> ParsedMessage:
        if not text:
            return ParsedMessage()

        lowered = text.lower()
        values: dict = {}
        notes: list[str] = []

        self._parse_soc(lowered, values, notes)
        self._parse_rainfall(lowered, values, notes)
        self._parse_ph(lowered, values)
        self._parse_soil_moisture(lowered, values)
        self._parse_temperature(lowered, values)
        self._parse_species_richness(lowered, values)
        self._parse_coordinates(lowered, values)
        self._parse_land_use(lowered, values, notes)
        self._parse_region(lowered, values)

        # Validate through the canonical schema. A parse that produces
        # an out-of-range value is a parse bug, so surface it rather
        # than passing a bad number downstream.
        EnvironmentalInput(**values)

        return ParsedMessage(values=values, notes=notes)

    # ----------------------------------------------------------------
    # Soil organic carbon -> g/kg
    # ----------------------------------------------------------------
    def _parse_soc(self, text, values, notes):
        match = re.search(
            rf"{_SOC_WORDS}\s*(?:is|of|at|=|:)?\s*{_NUM}\s*{_SOC_UNIT}?",
            text,
        )

        if not match:
            # Reverse order: "0.58% SOC", "5.8 g/kg organic carbon"
            match = re.search(
                rf"{_NUM}\s*{_SOC_UNIT}?\s*(?:of\s+)?{_SOC_WORDS}",
                text,
            )

        if not match:
            return

        raw_value = float(match.group(1))
        raw_unit = match.group(2)
        resolved_unit = U.infer_soc_unit(raw_value, raw_unit)

        values["soil_organic_carbon_g_per_kg"] = U.soc_to_g_per_kg(
            raw_value, resolved_unit
        )

        if not raw_unit:
            notes.append(
                f"No unit was given for SOC ({raw_value}); it was read "
                f"as {resolved_unit} and converted to "
                f"{values['soil_organic_carbon_g_per_kg']} g/kg. "
                "State the unit to override this."
            )
        elif resolved_unit in {"%", "percent"}:
            notes.append(
                f"SOC {raw_value}% converted to "
                f"{values['soil_organic_carbon_g_per_kg']} g/kg "
                "(1% = 10 g/kg)."
            )

    # ----------------------------------------------------------------
    # Precipitation -> mm/day
    # ----------------------------------------------------------------
    def _parse_rainfall(self, text, values, notes):
        match = re.search(
            rf"{_RAIN_WORDS}\s*(?:is|of|at|=|:)?\s*{_NUM}\s*{_RAIN_UNIT}?",
            text,
        )

        if not match:
            # "600 mm annual rainfall", "1.2 mm/day of rain"
            match = re.search(
                rf"{_NUM}\s*{_RAIN_UNIT}?\s*(?:of\s+)?{_RAIN_WORDS}",
                text,
            )

        if not match:
            return

        raw_value = float(match.group(1))
        raw_unit = match.group(2)

        # "annual rainfall 600 mm" carries the annual signal in the
        # keyword rather than the unit, so honour it explicitly.
        matched_span = match.group(0)
        annual_keyword = bool(
            re.search(r"annual|yearly", matched_span)
        )

        if raw_unit and not re.fullmatch(
            r"mm", raw_unit.strip(), flags=re.I
        ):
            resolved_unit = _canonical_rain_unit(raw_unit)
        elif annual_keyword:
            resolved_unit = "mm/year"
        else:
            resolved_unit = U.infer_rainfall_unit(raw_value, raw_unit)

        values["precipitation_mm_day"] = U.rainfall_to_mm_day(
            raw_value, resolved_unit
        )

        if resolved_unit != "mm/day":
            notes.append(
                f"Precipitation {raw_value} was read as "
                f"{resolved_unit} and converted to "
                f"{values['precipitation_mm_day']} mm/day "
                "(mean daily rate; seasonality is not represented)."
            )
        elif not raw_unit:
            notes.append(
                f"No unit was given for precipitation ({raw_value}); "
                "it was read as mm/day."
            )

    # ----------------------------------------------------------------
    # Soil pH
    # ----------------------------------------------------------------
    def _parse_ph(self, text, values):
        # \b keeps this from firing on "phosphorus", "phase", "graph".
        match = re.search(
            rf"\b(?:soil\s+)?ph\b\s*(?:is|of|at|=|:)?\s*{_NUM}",
            text,
        )

        if not match:
            match = re.search(
                rf"{_NUM}\s*(?:soil\s+)?ph\b",
                text,
            )

        if not match:
            return

        value = float(match.group(1))

        # Out-of-range numbers next to "ph" are almost always a
        # different quantity that happened to sit nearby.
        if 0 <= value <= 14:
            values["soil_ph"] = value

    # ----------------------------------------------------------------
    # Soil moisture (%)
    # ----------------------------------------------------------------
    def _parse_soil_moisture(self, text, values):
        match = re.search(
            rf"(?:soil\s+)?moisture\b\s*(?:is|of|at|=|:)?\s*{_NUM}\s*%?",
            text,
        )

        if not match:
            match = re.search(
                rf"{_NUM}\s*%?\s*(?:soil\s+)?moisture\b",
                text,
            )

        if not match:
            return

        value = float(match.group(1))

        if 0 <= value <= 100:
            values["soil_moisture"] = value

    # ----------------------------------------------------------------
    # Temperature (degC)
    # ----------------------------------------------------------------
    def _parse_temperature(self, text, values):
        match = re.search(
            rf"\b(?:temperature|temp)\b\s*(?:is|of|at|=|:)?\s*"
            rf"{_NUM}\s*(?:°\s*)?(?:c|celsius|centigrade)?\b",
            text,
        )

        if not match:
            match = re.search(
                rf"{_NUM}\s*(?:°\s*)?(?:c|celsius)\b",
                text,
            )

        if not match:
            return

        values["temperature_c"] = float(match.group(1))

    # ----------------------------------------------------------------
    # Species richness
    # ----------------------------------------------------------------
    def _parse_species_richness(self, text, values):
        match = re.search(
            r"(?:species\s+richness|richness)\s*(?:is|of|at|=|:)?\s*"
            r"(\d+)",
            text,
        )

        if not match:
            match = re.search(
                r"(\d+)\s*species\b",
                text,
            )

        if match:
            values["species_richness"] = int(match.group(1))

    # ----------------------------------------------------------------
    # Coordinates
    # ----------------------------------------------------------------
    def _parse_coordinates(self, text, values):
        match = re.search(
            rf"\blat(?:itude)?\b\s*(?:is|=|:)?\s*{_NUM}",
            text,
        )
        if match:
            candidate = float(match.group(1))
            if -90 <= candidate <= 90:
                values["latitude"] = candidate

        match = re.search(
            rf"\blon(?:g|gitude)?\b\s*(?:is|=|:)?\s*{_NUM}",
            text,
        )
        if match:
            candidate = float(match.group(1))
            if -180 <= candidate <= 180:
                values["longitude"] = candidate

        if "latitude" in values and "longitude" in values:
            return

        # Bare "18.99, 73.12" pair, only when the user signalled that
        # they are giving coordinates.
        if "coordinat" not in text:
            return

        match = re.search(
            rf"(?<![\d.]){_NUM}\s*,\s*{_NUM}(?![\d.])",
            text,
        )
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                values["latitude"] = lat
                values["longitude"] = lon

    # ----------------------------------------------------------------
    # Land use
    # ----------------------------------------------------------------
    # The previous implementation used `[a-z\s-]{1,40}?` which spans
    # word boundaries and produced land_use values like
    # "and this is wheat monoculture". The phrase is now bounded to at
    # most three preceding words and stripped of filler.
    _LAND_TERMS = (
        r"(?:intensive\s+agriculture|intensive\s+farming|intensive\s+agricultural\s+land|monoculture|croplands?|crop\s*land|plantations?|pasture|"
        r"agroforestry|forests?|woodland|grassland|shrubland|scrub|"
        r"savannah?|rangeland|orchard|vineyard|paddy|farmland|"
        r"wetland|mangroves?|built[-\s]?up|urban|bare\s+soil|tundra)"
    )

    def _parse_land_use(self, text, values, notes):
        patterns = [
            # "this is wheat monoculture" / "the land is cropland"
            rf"(?:the\s+land\s+is|land\s+use\s+is|land\s+is|"
            rf"it\s+is|this\s+is)\s+(?:an?\s+)?"
            rf"((?:[a-z]+[\s-]){{0,3}}{self._LAND_TERMS})",
            # bare "wheat monoculture" with at most 3 leading words
            rf"\b((?:[a-z]+[\s-]){{0,3}}{self._LAND_TERMS})\b",
        ]

        raw_land_use = None

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                raw_land_use = _trim_land_phrase(match.group(1))
                break

        if not raw_land_use:
            return

        # Strip common filler captured before explicit management phrases.
        raw_land_use = re.sub(
            r"^(?:currently\s+)?(?:used\s+for|uses|using)\s+",
            "",
            raw_land_use,
        ).strip()

        intensive_match = re.search(
            r"(intensive\s+(?:agriculture|farming|agricultural\s+land))",
            raw_land_use,
        )
        if intensive_match:
            raw_land_use = intensive_match.group(1)

        values["land_use"] = raw_land_use

        normalized = normalize_land_use(raw_land_use)
        if normalized["normalization_note"]:
            notes.append(normalized["normalization_note"])

        crop = _extract_crop(raw_land_use)
        if crop:
            values["crop"] = crop

    # ----------------------------------------------------------------
    # Region / climate zone
    # ----------------------------------------------------------------
    _REGIONS = [
        "semi-arid",
        "semi arid",
        "semiarid",
        "hyper-arid",
        "arid",
        "sub-humid",
        "sub humid",
        "semi-humid",
        "semi humid",
        "humid",
        "tropical",
        "subtropical",
        "sub-tropical",
        "temperate",
        "mediterranean",
        "boreal",
        "alpine",
        "montane",
        "dryland",
        "coastal",
    ]

    def _parse_region(self, text, values):
        # Longest first so "semi-arid" wins over "arid" and
        # "subtropical" wins over "tropical".
        for region in sorted(self._REGIONS, key=len, reverse=True):
            if re.search(rf"(?<![a-z]){re.escape(region)}\b", text):
                values["region"] = region.replace(" ", "-")
                return


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

_STOPWORDS = {
    "and",
    "the",
    "this",
    "that",
    "is",
    "was",
    "a",
    "an",
    "in",
    "on",
    "of",
    "it",
    "with",
    "my",
    "our",
    "here",
    "there",
    "we",
    "have",
    "has",
    "under",
    "land",
    "area",
    "site",
    "field",
    "plot",
    "region",
    "zone",
    "currently",
    "mostly",
    "entirely",
    "all",
    "but",
    "so",
}

_KNOWN_CROPS = {
    "wheat",
    "rice",
    "maize",
    "corn",
    "soybean",
    "soy",
    "cotton",
    "sugarcane",
    "millet",
    "sorghum",
    "barley",
    "coffee",
    "tea",
    "cocoa",
    "oil palm",
    "palm",
    "banana",
    "cassava",
    "groundnut",
    "chickpea",
    "mustard",
}


def _trim_land_phrase(phrase: str) -> str:
    """Drop leading filler words from a captured land-use phrase."""
    tokens = [token for token in phrase.split() if token]

    while tokens and tokens[0] in _STOPWORDS:
        tokens.pop(0)

    return " ".join(tokens).strip(" -")


def _extract_crop(land_use: str) -> str | None:
    lowered = land_use.lower()

    for crop in sorted(_KNOWN_CROPS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(crop)}\b", lowered):
            return crop

    return None


def _canonical_rain_unit(raw_unit: str) -> str:
    cleaned = raw_unit.strip().lower().replace(" ", "")

    if re.search(r"(year|yr|/a$|pera)", cleaned):
        return "mm/year"

    if re.search(r"(month|mo)", cleaned):
        return "mm/month"

    return "mm/day"

