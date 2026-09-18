"""
Recommendation-specific scientific evidence retrieval.

PROBLEM THIS REPLACES
---------------------
The previous flow ran ONE ChromaDB query built from the whole
environmental state, took the top 5 documents, and then re-ranked
those same 5 documents for every recommendation. Consequences:

  * a recommendation about soil pH could only ever be supported by
    documents that a soil-carbon-and-rainfall query happened to return
  * lexical re-ranking inside a fixed candidate pool cannot recover a
    relevant document that the single query missed
  * a document scoring 0 still got attached when nothing else matched

CORRECT FLOW (implemented here)
-------------------------------
    candidate recommendation
        -> recommendation-specific retrieval query
        -> ChromaDB vector search (per recommendation)
        -> hybrid rank: vector similarity + metadata/lexical agreement
        -> relevance floor
        -> attach strongest evidence, or declare it insufficient

HONESTY RULES ENCODED HERE
--------------------------
  * Evidence below `RELEVANCE_FLOOR` is dropped, not attached. A
    recommendation with no qualifying evidence is reported as
    `evidence_status = "insufficient"` with an explicit message.
  * Nothing is synthesised. Every returned record corresponds to a real
    document in the knowledge base, addressable via /knowledge/{id}.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Minimum blended relevance for a document to be attached at all.
#: Tuned against the current knowledge base; it is a prototype
#: threshold, not a statistical significance level.
RELEVANCE_FLOOR = 0.35

#: Relevance at or above which evidence is treated as well-matched.
STRONG_RELEVANCE = 0.60

#: How many documents to pull from the vector store per recommendation
#: before re-ranking and filtering.
RETRIEVE_K = 6

#: How many to attach to a recommendation after filtering.
ATTACH_K = 3

_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "than",
    "rather",
    "through",
    "where",
    "when",
    "using",
    "use",
    "add",
    "their",
    "locally",
    "appropriate",
    "existing",
    "between",
}


@dataclass
class EvidenceBundle:
    """Evidence attached to a single recommendation."""

    items: list[dict]
    status: str  # "supported" | "weak" | "insufficient"
    message: str | None
    top_relevance: float
    independent_sources: int


class EvidenceRetriever:
    """
    Retrieves and ranks evidence for one recommendation at a time.

    `knowledge` must expose `search(query: str, n: int) -> list[dict]`
    where each dict has `id`, `distance`, `text`, `metadata`. That is
    the existing `KnowledgeService` contract, so this composes with the
    live ChromaDB collection and with a stub in tests.
    """

    def __init__(
        self,
        knowledge,
        relevance_floor: float = RELEVANCE_FLOOR,
        retrieve_k: int = RETRIEVE_K,
        attach_k: int = ATTACH_K,
    ):
        self.knowledge = knowledge
        self.relevance_floor = relevance_floor
        self.retrieve_k = retrieve_k
        self.attach_k = attach_k

    # ----------------------------------------------------------------
    def build_query(self, candidate: dict) -> str:
        """
        Construct a retrieval query describing THIS recommendation.

        Ordered so the intervention terms lead, because the retrieval
        target is the intervention and its mechanism, not the site
        conditions that triggered it.
        """
        parts: list[str] = []

        parts.extend(candidate.get("retrieval_terms", []))
        parts.append(candidate.get("recommendation", ""))
        parts.extend(candidate.get("impacted_metrics", []))

        query = ". ".join(part for part in parts if part)

        return query.strip()

    # ----------------------------------------------------------------
    def retrieve(self, candidate: dict) -> EvidenceBundle:
        query = self.build_query(candidate)

        if not query:
            return self._insufficient(
                "This recommendation carries no retrieval terms, so "
                "no targeted evidence lookup was possible."
            )

        try:
            raw = self.knowledge.search(query, self.retrieve_k)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            return self._insufficient(
                "The scientific knowledge base was unavailable, so "
                "this recommendation is presented without retrieved "
                f"evidence ({type(exc).__name__}). The reasoning is "
                "unaffected."
            )

        scored = []

        for record in raw or []:
            relevance, matched = self._relevance(record, candidate)

            if relevance < self.relevance_floor:
                continue

            metadata = record.get("metadata") or {}

            scored.append(
                {
                    "id": record.get("id"),
                    "source": metadata.get("source"),
                    "title": metadata.get("title"),
                    "year": metadata.get("year"),
                    "relevance": round(relevance, 3),
                    "distance": _round_or_none(record.get("distance")),
                    "evidence_type": metadata.get(
                        "evidence_type", "knowledge_base_record"
                    ),
                    "intervention": metadata.get("intervention"),
                    "matched_terms": matched[:6],
                }
            )

        scored.sort(key=lambda item: item["relevance"], reverse=True)
        attached = scored[: self.attach_k]

        if not attached:
            return self._insufficient(
                "No knowledge-base record cleared the relevance "
                "threshold for this recommendation. The recommendation "
                "follows from the environmental reasoning rules alone "
                "and is not evidence-backed in this prototype."
            )

        top_relevance = attached[0]["relevance"]
        sources = {
            item["source"] for item in attached if item.get("source")
        }

        if top_relevance >= STRONG_RELEVANCE:
            status = "supported"
            message = None
        else:
            status = "weak"
            message = (
                "The closest knowledge-base records are only "
                "partially on-topic for this recommendation. Treat "
                "the supporting evidence as indicative rather than "
                "direct."
            )

        return EvidenceBundle(
            items=attached,
            status=status,
            message=message,
            top_relevance=top_relevance,
            independent_sources=len(sources),
        )

    # ----------------------------------------------------------------
    def _relevance(
        self,
        record: dict,
        candidate: dict,
    ) -> tuple[float, list[str]]:
        """
        Blend vector similarity with metadata and lexical agreement.

        Vector similarity carries the semantic match; the lexical and
        metadata components correct for the fact that a short
        knowledge-base abstract can be embedded close to almost any
        environmental query.
        """
        similarity = _distance_to_similarity(record.get("distance"))

        text = str(record.get("text", "")).lower()
        metadata = record.get("metadata") or {}

        intervention = str(
            metadata.get("intervention", "")
        ).lower()
        variables = str(metadata.get("variables", "")).lower()
        haystack = f"{text} {intervention} {variables}"

        matched: list[str] = []

        # --- intervention-term agreement ----------------------------
        terms = [
            term.lower()
            for term in candidate.get("retrieval_terms", [])
        ]
        term_hits = 0

        for term in terms:
            tokens = [
                token
                for token in re.findall(r"[a-z]+", term)
                if len(token) > 3 and token not in _STOPWORDS
            ]
            if not tokens:
                continue

            overlap = sum(
                1 for token in tokens if token in haystack
            )

            if overlap / len(tokens) >= 0.5:
                term_hits += 1
                matched.append(term)

        term_score = min(1.0, term_hits / 2.0) if terms else 0.0

        # --- impacted-metric agreement ------------------------------
        metrics = [
            metric.lower()
            for metric in candidate.get("impacted_metrics", [])
        ]
        metric_hits = 0

        for metric in metrics:
            tokens = [
                token
                for token in re.findall(r"[a-z]+", metric)
                if len(token) > 3 and token not in _STOPWORDS
            ]
            if tokens and all(
                token in haystack for token in tokens
            ):
                metric_hits += 1
                matched.append(metric)

        metric_score = (
            min(1.0, metric_hits / 2.0) if metrics else 0.0
        )

        # Weights: semantic match dominates, but a document that
        # shares no intervention vocabulary with the recommendation
        # cannot reach the "supported" band on similarity alone.
        relevance = (
            0.50 * similarity
            + 0.32 * term_score
            + 0.18 * metric_score
        )

        return relevance, matched

    # ----------------------------------------------------------------
    @staticmethod
    def _insufficient(message: str) -> EvidenceBundle:
        return EvidenceBundle(
            items=[],
            status="insufficient",
            message=message,
            top_relevance=0.0,
            independent_sources=0,
        )


def _distance_to_similarity(distance) -> float:
    """
    Map a ChromaDB distance onto [0, 1].

    ChromaDB's default collection metric is squared L2 over normalized
    sentence-transformer embeddings, so distances land roughly in
    [0, 2]. The mapping is monotonic and bounded; it is a ranking aid,
    not a probability.
    """
    if distance is None:
        return 0.5

    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.5

    if value < 0:
        return 1.0

    return max(0.0, min(1.0, 1.0 - (value / 2.0)))


def _round_or_none(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
