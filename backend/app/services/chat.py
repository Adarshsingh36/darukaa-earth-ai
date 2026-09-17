import re

from app.models.schemas import EnvironmentalInput


class ConversationMemory:
    def __init__(self):
        self.sessions = {}

    def get(self, cid):
        return self.sessions.setdefault(
            cid,
            {
                "messages": [],
                "environment": {}
            }
        )

    def update(self, cid, env: EnvironmentalInput | dict | None):
        s = self.get(cid)

        if env:
            if isinstance(env, EnvironmentalInput):
                values = env.model_dump(exclude_none=True)
            else:
                values = {
                    k: v
                    for k, v in env.items()
                    if v is not None
                }

            s["environment"].update(values)

        return s

    def add_message(self, cid, role, text):
        self.get(cid)["messages"].append({
            "role": role,
            "content": text
        })


memory = ConversationMemory()


class ChatParser:

    def parse(self, text):
        t = text.lower()
        d = {}

        # -------------------------------------------------
        # SOIL ORGANIC CARBON
        # -------------------------------------------------
        # Accepted examples:
        #   SOC 5.8 g/kg
        #   soil organic carbon is 5.8 g/kg
        #   SOC is 0.58%
        #   organic carbon = 0.58%
        #
        # Canonical internal unit:
        #   g/kg
        # -------------------------------------------------

        m = re.search(
            r"(?:soc|soil\s+organic\s+carbon|organic\s+carbon)"
            r"\s*(?:is|=|:)?\s*"
            r"(\d+(?:\.\d+)?)"
            r"\s*(%|g\s*/?\s*kg|gkg)?",
            t
        )

        if m:
            value = float(m.group(1))
            unit = (m.group(2) or "").replace(" ", "")

            if "%" in unit:
                # 1% SOC ≈ 10 g/kg
                value = value * 10.0

            d["soil_organic_carbon_g_per_kg"] = value

        # -------------------------------------------------
        # RAINFALL
        # -------------------------------------------------
        # Canonical internal unit:
        #   mm/day
        #
        # Accepted:
        #   rainfall 1.2 mm/day
        #   precipitation 1.2 mm/day
        #   annual rainfall 600 mm
        #
        # Annual rainfall is converted to mean daily rainfall.
        # -------------------------------------------------

        m = re.search(
            r"(?:annual\s+rainfall|annual\s+precipitation|"
            r"rainfall|precipitation|rain)"
            r"\s*(?:is|=|:)?\s*"
            r"(\d+(?:\.\d+)?)"
            r"\s*(mm\s*/?\s*day|mm/day|mm)?",
            t
        )

        if m:
            value = float(m.group(1))
            unit = (m.group(2) or "").replace(" ", "")

            if "day" in unit:
                # Already mm/day
                precipitation = value
            else:
                # Treat plain mm rainfall as annual rainfall.
                precipitation = value / 365.0

            d["precipitation_mm_day"] = precipitation

        # -------------------------------------------------
        # SOIL pH
        # -------------------------------------------------

        m = re.search(
            r"(?:soil\s+)?ph"
            r"\s*(?:is|=|:)?\s*"
            r"(\d+(?:\.\d+)?)",
            t
        )

        if m:
            d["soil_ph"] = float(m.group(1))

        # -------------------------------------------------
        # SOIL MOISTURE
        # -------------------------------------------------

        m = re.search(
            r"(?:soil\s+)?moisture"
            r"\s*(?:is|=|:)?\s*"
            r"(\d+(?:\.\d+)?)"
            r"\s*%?",
            t
        )

        if m:
            d["soil_moisture"] = float(m.group(1))

        # -------------------------------------------------
        # TEMPERATURE
        # -------------------------------------------------

        m = re.search(
            r"(?:temperature|temp)"
            r"\s*(?:is|=|:)?\s*"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*(?:°?c)?",
            t
        )

        if m:
            d["temperature_c"] = float(m.group(1))

        # -------------------------------------------------
        # SPECIES RICHNESS
        # -------------------------------------------------

        m = re.search(
            r"(?:species\s+richness|richness)"
            r"\s*(?:is|=|:)?\s*"
            r"(\d+)",
            t
        )

        if m:
            d["species_richness"] = int(m.group(1))

        # -------------------------------------------------
        # LAND USE / LAND COVER
        # -------------------------------------------------

        land_use_patterns = [
            r"(?:land\s+is|the\s+land\s+is|it\s+is|this\s+is)\s+"
            r"([a-z][a-z\s-]{1,40}?"
            r"(?:monoculture|cropland|plantation|pasture|"
            r"agroforestry|forest|grassland|shrubland))",

            r"\b([a-z][a-z\s-]{1,40}?"
            r"(?:monoculture|cropland|plantation|pasture|"
            r"agroforestry|forest|grassland|shrubland))\b",
        ]

        for pattern in land_use_patterns:
            m = re.search(pattern, t)

            if m:
                d["land_use"] = m.group(1).strip()
                break

        if "monoculture" in t and "land_use" not in d:
            d["land_use"] = "monoculture"

        # -------------------------------------------------
        # REGION / CLIMATE ZONE
        # -------------------------------------------------

        region_patterns = [
            "semi-arid",
            "semi arid",
            "arid",
            "humid",
            "semi-humid",
            "semi humid",
            "tropical",
            "subtropical",
            "temperate",
            "mediterranean",
            "dryland",
        ]

        for region in region_patterns:

            if region in t:
                d["region"] = region.replace(" ", "-")
                break

        # -------------------------------------------------
        # FINAL VALIDATION
        # -------------------------------------------------

        return EnvironmentalInput(**d)