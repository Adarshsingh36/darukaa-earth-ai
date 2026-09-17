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

    def parse(self, text: str) -> EnvironmentalInput:
        """Extract supported environmental values from a natural-language message."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

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
            r"(?:land\s+is|the\s+land\s+is|it\s+is|this\s+is)\s+"
            r"([a-z][a-z\s-]{1,40}?(?:monoculture|cropland|plantation|pasture|agroforestry|forest))",
            r"\b([a-z][a-z\s-]{1,40}?(?:monoculture|cropland|plantation|pasture|agroforestry|forest))\b",
        ]

        for pattern in land_use_patterns:
            m = re.search(pattern, t)
            if m:
                d["land_use"] = m.group(1).strip()
                break

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

class ChatIntent:

    @staticmethod
    def detect(text: str) -> str:
        t = text.lower().strip()

        if any(
            phrase in t
            for phrase in [
                "what is the result",
                "what's the result",
                "what is the assessment",
                "what's the assessment",
                "summarize the result",
                "give me the result",
                "overall result",
                "overall assessment"
            ]
        ):
            return "result"

        if any(
            phrase in t
            for phrase in [
                "why",
                "why does this work",
                "why is this happening",
                "explain why",
                "how does this work"
            ]
        ):
            return "why"

        if any(
            phrase in t
            for phrase in [
                "what metrics",
                "which metrics",
                "what will improve",
                "what improves",
                "environmental metrics"
            ]
        ):
            return "metrics"

        if any(
            phrase in t
            for phrase in [
                "what evidence",
                "which evidence",
                "what studies",
                "what research",
                "what sources",
                "show me the evidence"
            ]
        ):
            return "evidence"

        if any(
            phrase in t
            for phrase in [
                "recommendation",
                "recommendations",
                "what should i do",
                "what should we do",
                "what action",
                "next step",
                "intervention"
            ]
        ):
            return "recommendation"

        return "assessment"