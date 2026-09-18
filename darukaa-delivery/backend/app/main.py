"""
Darukaa.Earth Environmental Intelligence API.

Endpoints are thin. All pipeline logic lives in
`app.services.analysis.AnalysisService`, so /analyze and /chat share
exactly one code path and neither can drift from the other.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.api.environment import router as environment_router
from app.models.schemas import (
    AnalysisResponse,
    ChatRequest,
    EnvironmentalInput,
)
from app.services.analysis import REQUIRED_FOR_CHAT, AnalysisService
from app.services.chat import ChatParser, memory
from app.services.knowledge import KnowledgeService
from app.services.reasoning import ReasoningEngine
from app.services.units import normalize_external_payload

logger = logging.getLogger("darukaa")

app = FastAPI(
    title="Darukaa.Earth Environmental Intelligence API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

knowledge = KnowledgeService()
reasoning = ReasoningEngine()
analysis = AnalysisService(knowledge, reasoning)
parser = ChatParser()


# --------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "knowledge_documents": knowledge.count(),
        "knowledge": knowledge.status(),
    }


# --------------------------------------------------------------------
@app.post("/knowledge/search")
def search(payload: dict):
    query = (payload or {}).get("query", "")
    top_k = int((payload or {}).get("top_k", 5))

    if not query:
        raise HTTPException(
            status_code=422,
            detail="A non-empty 'query' is required.",
        )

    results = knowledge.search(query, top_k)

    return {
        "results": results,
        "vector_index_available": knowledge.available,
    }


# --------------------------------------------------------------------
@app.get("/knowledge/{knowledge_id}")
def get_knowledge(knowledge_id: str):
    item = knowledge.get_by_id(knowledge_id)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Knowledge record not found",
        )

    return item


# --------------------------------------------------------------------
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(env: EnvironmentalInput) -> AnalysisResponse:
    """
    Full assessment.

    When latitude and longitude are present, live geospatial context is
    retrieved first (NASA POWER, SoilGrids, WorldCover, GBIF). Values
    the caller supplied are never overwritten by live data; live data
    fills gaps only. Any source that fails is recorded in
    `data_provenance.degraded_sources` and the assessment continues.
    """
    return await analysis.analyze_location(env)


# --------------------------------------------------------------------
@app.post("/normalize")
def normalize(payload: dict):
    """
    Convert an external/legacy payload into canonical fields and units.

    Exposed so the unit assumptions are inspectable rather than
    implicit: the caller can see exactly what 'rainfall_mm: 600' was
    interpreted as before it reaches /analyze.
    """
    try:
        canonical, notes = normalize_external_payload(payload or {})
        env = EnvironmentalInput(**canonical)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors()
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc

    return {
        "canonical": env.model_dump(exclude_none=True),
        "conversion_notes": notes,
    }


# --------------------------------------------------------------------
@app.post("/chat")
async def chat(req: ChatRequest):
    cid = req.conversation_id

    memory.add_message(cid, "user", req.message)

    # Structured input first, then anything parsed from the message,
    # so an explicit field always beats a text guess.
    if req.environmental:
        memory.update(
            cid, req.environmental.model_dump(exclude_none=True)
        )

    try:
        parsed = parser.parse(req.message)
    except ValidationError as exc:
        reply = (
            "I read a value in that message that falls outside a "
            "physically valid range, so I did not record it. Could "
            "you re-check it?"
        )
        memory.add_message(cid, "assistant", reply)
        return {
            "conversation_id": cid,
            "type": "error",
            "message": reply,
            "detail": exc.errors(),
            "environment": memory.get(cid)["environment"],
        }

    if parsed:
        memory.update(cid, parsed.values, parsed.notes)

    state = memory.get(cid)
    environment_data = state["environment"]

    try:
        env = EnvironmentalInput(**environment_data)
    except ValidationError as exc:
        # Accumulated state should never be invalid; if it is, that is
        # a bug worth surfacing rather than silently discarding.
        logger.warning("Invalid accumulated state for %s", cid)
        raise HTTPException(
            status_code=500,
            detail=f"Corrupt conversation state: {exc.errors()}",
        ) from exc

    # Enrich BEFORE deciding what is missing. Coordinates can answer
    # soil carbon, precipitation and land use outright, so checking
    # first would ask the user for values the system can already get.
    env, live_context = await analysis.prepare(env)

    if live_context.get("values"):
        memory.update(cid, env.model_dump(exclude_none=True))
        environment_data = memory.get(cid)["environment"]

    missing = [
        field
        for field in REQUIRED_FOR_CHAT
        if getattr(env, field) is None
    ]

    if missing:
        labels = {
            "soil_organic_carbon_g_per_kg": (
                "soil organic carbon (g/kg, or a % and I will convert)"
            ),
            "precipitation_mm_day": (
                "precipitation (mm/day, or an annual mm total)"
            ),
            "land_use": "land-use type",
            "region": "region or climate zone",
        }

        reply = (
            "To complete the assessment I still need: "
            + ", ".join(labels[field] for field in missing)
            + "."
        )

        memory.add_message(cid, "assistant", reply)

        return {
            "conversation_id": cid,
            "type": "clarification",
            "message": reply,
            "environment": environment_data,
            "missing_variables": missing,
            "normalization_notes": (
                parsed.notes + live_context.get("merge_notes", [])
            ),
            "degraded_sources": live_context.get("failures", []),
        }

    result = analysis.analyze(env, live_context)

    memory.add_message(cid, "assistant", result.model_dump_json())

    return {
        "conversation_id": cid,
        "type": "analysis",
        "message": (
            "I combined the accumulated soil, climate, water and "
            "land-use variables, derived condition indicators, and "
            "retrieved evidence separately for each recommendation."
        ),
        "environment": environment_data,
        # Always present, on both branches, so the client never has to
        # tell "nothing missing" apart from "the key wasn't sent".
        "missing_variables": missing,
        "normalization_notes": parsed.notes,
        "degraded_sources": live_context.get("failures", []),
        "analysis": result,
    }


# --------------------------------------------------------------------
@app.post("/chat/reset")
def chat_reset(payload: dict | None = None):
    cid = (payload or {}).get("conversation_id", "default")
    memory.reset(cid)
    return {"conversation_id": cid, "status": "reset"}


app.include_router(environment_router)
