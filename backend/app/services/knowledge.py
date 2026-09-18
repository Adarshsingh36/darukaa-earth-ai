"""
Scientific knowledge base backed by ChromaDB.

CHANGES
-------
1. `get_by_id` now exists. `main.py` already exposed
   GET /knowledge/{id} and called `knowledge.get_by_id(...)`, which
   raised AttributeError and returned a 500 for every request. The
   endpoint is the mechanism by which a user checks a citation, so a
   broken version is worse than no version.

2. Startup no longer hard-fails. If ChromaDB or the embedding model is
   unavailable the service degrades to `available = False`; /health
   reports it, search returns empty, and recommendations are labelled
   `evidence_status = "insufficient"` rather than the whole API dying.

3. The JSON file remains the source of truth for record content, so a
   citation can always be resolved even if the vector index is down.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "knowledge.json"


class KnowledgeService:
    def __init__(self, eager: bool = True):
        self.available = False
        self.error: str | None = None
        self.client = None
        self.collection = None
        self.embedder = None

        self._records = self._load_records()
        self._by_id = {record["id"]: record for record in self._records}

        if eager:
            self._connect()

    # ----------------------------------------------------------------
    def _load_records(self) -> list[dict]:
        try:
            # utf-8-sig: the committed file carries a BOM.
            return json.loads(DATA.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            self.error = f"knowledge.json unreadable: {exc}"
            return []

    # ----------------------------------------------------------------
    def _connect(self) -> None:
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer

            self.client = chromadb.PersistentClient(
                path=os.getenv(
                    "CHROMA_PATH", str(BASE / "chroma_db")
                )
            )
            self.collection = self.client.get_or_create_collection(
                "environmental_knowledge"
            )
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            self._seed()
            self.available = True
        except Exception as exc:  # noqa: BLE001
            self.error = (
                f"{type(exc).__name__}: {exc}"
            )
            self.available = False

    # ----------------------------------------------------------------
    def _seed(self) -> None:
        if not self._records:
            return

        if self.collection.count() >= len(self._records):
            return

        ids = [record["id"] for record in self._records]
        texts = [self._text(record) for record in self._records]
        embeddings = self.embedder.encode(texts).tolist()

        self.collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    key: str(value)
                    for key, value in record.items()
                    if key not in ("id",)
                }
                for record in self._records
            ],
        )

    # ----------------------------------------------------------------
    @staticmethod
    def _text(record: dict) -> str:
        return (
            f"Title: {record['title']}\n"
            f"Source: {record['source']}\n"
            f"Year: {record.get('year', '')}\n"
            f"Variables: {', '.join(record.get('variables', []))}\n"
            f"Mechanism: {record['mechanism']}\n"
            f"Intervention: {record['intervention']}\n"
            f"Evidence: {record['evidence']}"
        )

    # ----------------------------------------------------------------
    def count(self) -> int:
        if self.available and self.collection is not None:
            try:
                return self.collection.count()
            except Exception:  # noqa: BLE001
                pass
        return len(self._records)

    # ----------------------------------------------------------------
    def search(self, query: str, n: int = 5) -> list[dict]:
        if not self.available or self.collection is None:
            return []

        if not query:
            return []

        embedding = self.embedder.encode([query]).tolist()

        result = self.collection.query(
            query_embeddings=embedding,
            n_results=min(n, max(1, self.count())),
            include=["documents", "metadatas", "distances"],
        )

        out = []

        for index, document in enumerate(result["documents"][0]):
            out.append(
                {
                    "id": result["ids"][0][index],
                    "distance": result["distances"][0][index],
                    "text": document,
                    "metadata": result["metadatas"][0][index],
                }
            )

        return out

    # ----------------------------------------------------------------
    def get_by_id(self, knowledge_id: str) -> dict | None:
        """
        Resolve a citation to its full record.

        Reads from the JSON source of truth so a citation shown in the
        UI stays resolvable even when the vector index is unavailable.
        """
        if not knowledge_id:
            return None

        return self._by_id.get(knowledge_id.strip().upper()) or (
            self._by_id.get(knowledge_id.strip())
        )

    # ----------------------------------------------------------------
    def status(self) -> dict:
        return {
            "vector_index_available": self.available,
            "documents": self.count(),
            "records_in_source_file": len(self._records),
            "error": self.error,
        }
