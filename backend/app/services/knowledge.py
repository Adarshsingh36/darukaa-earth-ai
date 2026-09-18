from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer


BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "knowledge.json"


class KnowledgeService:
    """
    Scientific environmental knowledge retrieval using ChromaDB
    and sentence-transformer embeddings.

    The knowledge base is deliberately retrieval-oriented:
    documents contain the mechanism, intervention, variables,
    and supporting evidence text used to ground recommendations.
    """

    COLLECTION_NAME = "environmental_knowledge"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        chroma_path = os.getenv(
            "CHROMA_PATH",
            str(BASE / "chroma_db"),
        )

        self.client = chromadb.PersistentClient(
            path=chroma_path
        )

        self.collection = self.client.get_or_create_collection(
            self.COLLECTION_NAME
        )

        self.embedder = SentenceTransformer(
            self.EMBEDDING_MODEL
        )

        self._seed()

    # ------------------------------------------------------------------
    # Knowledge-base management
    # ------------------------------------------------------------------

    def _load_documents(self) -> list[dict[str, Any]]:
        return json.loads(
            DATA.read_text(encoding="utf-8")
        )

    def _seed(self) -> None:
        docs = self._load_documents()

        if not docs:
            return

        ids = [str(d["id"]) for d in docs]

        texts = [
            self._text(d)
            for d in docs
        ]

        embeddings = self.embedder.encode(
            texts
        ).tolist()

        metadatas = [
            {
                str(k): self._metadata_value(v)
                for k, v in d.items()
                if k not in {"id", "evidence"}
            }
            for d in docs
        ]

        self.collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    @staticmethod
    def _metadata_value(value: Any) -> str:
        if isinstance(value, (list, dict)):
            return json.dumps(
                value,
                ensure_ascii=False,
            )

        return str(value)

    @staticmethod
    def _text(d: dict[str, Any]) -> str:
        variables = d.get("variables", [])

        if isinstance(variables, list):
            variables_text = ", ".join(
                str(v) for v in variables
            )
        else:
            variables_text = str(variables)

        return (
            f"Title: {d.get('title', '')}\n"
            f"Source: {d.get('source', '')}\n"
            f"Year: {d.get('year', '')}\n"
            f"Topic: {d.get('topic', '')}\n"
            f"Variables: {variables_text}\n"
            f"Mechanism: {d.get('mechanism', '')}\n"
            f"Intervention: {d.get('intervention', '')}\n"
            f"Evidence: {d.get('evidence', '')}"
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n: int = 5,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()

        if not query:
            return []

        n = max(1, int(n))

        embedding = self.embedder.encode(
            [query]
        ).tolist()

        result = self.collection.query(
            query_embeddings=embedding,
            n_results=n,
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        ids = result.get("ids", [[]])[0]

        output: list[dict[str, Any]] = []

        for i, document in enumerate(documents):
            metadata = (
                metadatas[i]
                if i < len(metadatas)
                else {}
            )

            distance = (
                distances[i]
                if i < len(distances)
                else None
            )

            knowledge_id = (
                ids[i]
                if i < len(ids)
                else None
            )

            output.append(
                {
                    "id": knowledge_id,
                    "distance": distance,
                    "text": document,
                    "metadata": metadata or {},
                }
            )

        return output

    # ------------------------------------------------------------------
    # Direct lookup
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        knowledge_id: str,
    ) -> dict[str, Any] | None:
        knowledge_id = str(
            knowledge_id or ""
        ).strip()

        if not knowledge_id:
            return None

        result = self.collection.get(
            ids=[knowledge_id],
            include=[
                "documents",
                "metadatas",
            ],
        )

        ids = result.get("ids", [])

        if not ids:
            return None

        documents = result.get(
            "documents",
            [],
        )

        metadatas = result.get(
            "metadatas",
            [],
        )

        return {
            "id": ids[0],
            "text": (
                documents[0]
                if documents
                else ""
            ),
            "metadata": (
                metadatas[0]
                if metadatas
                else {}
            ),
        }

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self.collection.count()

    @property
    def available(self) -> bool:
        try:
            return self.collection.count() > 0
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        try:
            count = self.collection.count()

            return {
                "available": count > 0,
                "document_count": count,
                "embedding_model": self.EMBEDDING_MODEL,
                "collection": self.COLLECTION_NAME,
            }

        except Exception as exc:
            return {
                "available": False,
                "document_count": 0,
                "embedding_model": self.EMBEDDING_MODEL,
                "collection": self.COLLECTION_NAME,
                "error": str(exc),
            }