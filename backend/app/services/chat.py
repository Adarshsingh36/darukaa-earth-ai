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
                    k: v for k, v in env.items()
                    if v is not None
                }

            s["environment"].update(values)

        return s

    def add_message(self, cid, role, text):
        self.get(cid)["messages"].append(
            {
                "role": role,
                "content": text
            }
        )


memory = ConversationMemory()


class ChatParser:

    def parse(self, text):
        t = text.lower()
        d = {}

        # Soil organic carbon
        m = re.search(
            r"(?:soc|soil\s+organic\s+carbon|organic\s+carbon)"
            r"\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*%?",
            t
        )

        if m:
            d["soil_organic_carbon"] = float(m.group(1))

        # Rainfall
        m = re.search(
            r"(?:rainfall|annual\s+rainfall|rain)"
            r"\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?",
            t
        )

        if m:
            d["rainfall_mm"] = float(m.group(1))

        # Soil pH
        m = re.search(
            r"(?:soil\s+)?ph"
            r"\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)",
            t
        )

        if m:
            d["soil_ph"] = float(m.group(1))

        # Soil moisture
        m = re.search(
            r"(?:soil\s+)?moisture"
            r"\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*%?",
            t
        )

        if m:
            d["soil_moisture"] = float(m.group(1))

        # Temperature
        m = re.search(
            r"(?:temperature|temp)"
            r"\s*(?:is|=|:)?\s*(-?\d+(?:\.\d+)?)\s*(?:°?c)?",
            t
        )

        if m:
            d["temperature_c"] = float(m.group(1))

        # Species richness
        m = re.search(
            r"(?:species\s+richness|richness)"
            r"\s*(?:is|=|:)?\s*(\d+)",
            t
        )

        if m:
            d["species_richness"] = int(m.group(1))

        # Land-use patterns
        land_use_patterns = [
            r"([\w\s-]+monoculture)",
            r"([\w\s-]+cropland)",
            r"([\w\s-]+plantation)",
            r"([\w\s-]+pasture)",
            r"([\w\s-]+agroforestry)",
            r"([\w\s-]+forest)",
        ]

        for pattern in land_use_patterns:
            m = re.search(pattern, t)

            if m:
                value = m.group(1).strip()

                # Remove common leading phrases
                value = re.sub(
                    r"^(?:it is|the land is|land is|this is)\s+",
                    "",
                    value
                )

                d["land_use"] = value
                break

        # Specific common land-use terms
        if "monoculture" in t and "land_use" not in d:
            d["land_use"] = "monoculture"

        # Region / climate
        region_patterns = [
            "semi-arid",
            "arid",
            "humid",
            "semi-humid",
            "tropical",
            "subtropical",
            "temperate",
            "mediterranean",
            "dryland",
        ]

        for region in region_patterns:
            if region in t:
                d["region"] = region
                break

        return EnvironmentalInput(**d)