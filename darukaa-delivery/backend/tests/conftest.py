"""
Shared fixtures.

`StubKnowledgeService` implements the same `search`/`get_by_id`/`count`
contract as `KnowledgeService` but scores documents with deterministic
token overlap instead of sentence-transformer embeddings. This keeps
the whole pipeline testable without downloading a model or standing up
ChromaDB, and it makes retrieval assertions reproducible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
KNOWLEDGE_JSON = BACKEND / "app" / "data" / "knowledge.json"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z]+", text.lower())
        if len(token) > 3
    }


class StubKnowledgeService:
    """Offline stand-in for the ChromaDB-backed KnowledgeService."""

    def __init__(self, records=None, fail=False):
        self.fail = fail
        self.available = not fail

        if records is None:
            records = json.loads(
                KNOWLEDGE_JSON.read_text(encoding="utf-8-sig")
            )

        self._records = records
        self._by_id = {r["id"]: r for r in records}

    def count(self):
        return len(self._records)

    def _text(self, record):
        return (
            f"Title: {record['title']}\n"
            f"Source: {record['source']}\n"
            f"Variables: {', '.join(record.get('variables', []))}\n"
            f"Mechanism: {record['mechanism']}\n"
            f"Intervention: {record['intervention']}\n"
            f"Evidence: {record['evidence']}"
        )

    def search(self, query, n=5):
        if self.fail:
            raise RuntimeError("vector store unavailable")

        query_tokens = _tokens(query)
        scored = []

        for record in self._records:
            text = self._text(record)
            overlap = len(query_tokens & _tokens(text))
            denominator = max(1, len(query_tokens))

            # Map overlap onto a pseudo squared-L2 distance in [0, 2],
            # matching the range the real collection returns.
            distance = max(
                0.05, 2.0 - 2.0 * (overlap / denominator) * 3.0
            )

            scored.append(
                {
                    "id": record["id"],
                    "distance": round(distance, 4),
                    "text": text,
                    "metadata": {
                        key: str(value)
                        for key, value in record.items()
                        if key != "id"
                    },
                }
            )

        scored.sort(key=lambda item: item["distance"])
        return scored[:n]

    def get_by_id(self, knowledge_id):
        if not knowledge_id:
            return None
        return self._by_id.get(knowledge_id.strip().upper())

    def status(self):
        return {
            "vector_index_available": self.available,
            "documents": self.count(),
            "records_in_source_file": len(self._records),
            "error": None,
        }


@pytest.fixture
def knowledge():
    return StubKnowledgeService()


@pytest.fixture
def broken_knowledge():
    return StubKnowledgeService(fail=True)


@pytest.fixture
def analysis_service(knowledge):
    from app.services.analysis import AnalysisService

    return AnalysisService(knowledge)


@pytest.fixture
def demo_environment():
    """The scenario from section 18 of the project brief."""
    from app.models.schemas import EnvironmentalInput

    return EnvironmentalInput(
        soil_organic_carbon_g_per_kg=5.8,
        precipitation_mm_day=1.6438,
        soil_ph=5.4,
        temperature_c=26.0,
        land_use="wheat monoculture",
        crop="wheat",
        region="semi-arid",
    )


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio only (no trio dependency)."""
    return "asyncio"
