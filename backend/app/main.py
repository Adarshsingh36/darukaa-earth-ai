from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.models.schemas import EnvironmentalInput, ChatRequest, AnalysisResponse, Recommendation
from app.services.knowledge import KnowledgeService
from app.services.reasoning import ReasoningEngine
from app.services.chat import memory, ChatParser

app=FastAPI(title='Darukaa.Earth Environmental Intelligence API', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
knowledge=KnowledgeService(); reasoning=ReasoningEngine(); parser=ChatParser()

@app.get('/health')
def health(): return {'status':'ok','knowledge_documents':knowledge.collection.count()}

@app.post('/knowledge/search')
def search(payload: dict):
    return {'results':knowledge.search(payload.get('query',''),payload.get('top_k',5))}

@app.post('/analyze', response_model=AnalysisResponse)
def analyze(env: EnvironmentalInput):
    x, chain, candidates = reasoning.analyze(env)

    # Build a retrieval query from the detected environmental variables
    query = ' '.join(
        [f'{k}: {v}' for k, v in x.items()]
    )

    # Retrieve scientific evidence from ChromaDB
    evidence = knowledge.search(
        query or 'biodiversity environmental management',
        5
    )

    # Keep the original retrieved text internally so we can
    # match recommendations against the actual knowledge content.
    ev = [
    {
        'id': r['id'],
        'source': r['metadata'].get('source'),
        'title': r['metadata'].get('title'),
        'distance': r['distance'],
        'text': r.get('text', ''),
        'metadata': r.get('metadata', {})
    }
    for r in evidence
]

    recs = []

    for action, why, metrics, horizon in candidates:

        # Match retrieved evidence to the metrics affected
        def evidence_score(record, action, metrics):
            text = record.get("text", "").lower()
            metadata = record.get("metadata", {})

            score = 0

            # Metric relevance
            for metric in metrics:
                if metric.lower() in text:
                    score += 3

            # Recommendation/intervention relevance
            action_terms = [
                term.lower()
                for term in action.split()
                if len(term) > 3
            ]

            for term in action_terms:
                if term in text:
                    score += 1

            # Metadata relevance
            intervention = str(
                metadata.get("intervention", "")
            ).lower()

            topic = str(
                metadata.get("topic", "")
            ).lower()

            if intervention and any(
                term in intervention
                for term in action_terms
            ):
                score += 5

            if topic and any(
                metric.lower() in topic
                for metric in metrics
            ):
                score += 2

            return score

        scored = [
            (
                r,
                evidence_score(
                    r,
                    action,
                    metrics
                )
            )
            for r in ev
        ]

        matched = [
            r
            for r, score in sorted(
                scored,
                key=lambda item: item[1],
                reverse=True
            )
            if score > 0
        ]

        best_score = (
            evidence_score(matched[0], action, metrics)
            if matched
            else 0
            )

        confidence = round(
    min(
        0.95,
        0.55 + (best_score * 0.05)
    ),
    2
)

        recs.append(
            Recommendation(
                recommendation=action,
                why_it_works=why,
                impacted_metrics=metrics,
                time_horizon=horizon,
                confidence=confidence,
                evidence=[
                    {
                        'id': r['id'],
                        'source': r['source'],
                        'title': r['title']
                    }
                    for r in matched[:3]
                ]
            )
        )

        
    required = [
        'soil_organic_carbon',
        'rainfall_mm',
        'land_use'
    ]

    missing = [
        k for k in required
        if getattr(env, k) is None
    ]

    # Do not expose the raw retrieved text in the final API response.
    retrieved_evidence = [
        {
            'id': r['id'],
            'source': r['source'],
            'title': r['title'],
            'distance': r['distance']
        }
        for r in ev
    ]

    return AnalysisResponse(
        detected_variables=x,
        missing_variables=missing,
        reasoning_chain=chain,
        recommendations=recs,
        retrieved_evidence=retrieved_evidence
    )

@app.post('/chat')
def chat(req: ChatRequest):
    # Parse environmental information from natural language
    parsed = parser.parse(req.message)

    # Start with explicitly supplied structured environmental data
    if req.environmental:
        memory.update(
            req.conversation_id,
            req.environmental.model_dump(exclude_none=True)
        )

    # Merge values extracted from the user's message
    if parsed:
        memory.update(
            req.conversation_id,
            parsed
        )

    # Retrieve the accumulated environmental context
    state = memory.get(req.conversation_id)

    environment_data = state.get(
        "environment",
        {}
    )

    env = EnvironmentalInput(
        **environment_data
    )

    # Variables required before we can make a meaningful
    # environmental assessment
    required = [
        "soil_organic_carbon",
        "rainfall_mm",
        "land_use",
        "region"
    ]

    missing = [
        field
        for field in required
        if getattr(env, field) is None
    ]

    # Store the user message
    memory.add_message(
        req.conversation_id,
        "user",
        req.message
    )

    # Ask targeted clarification questions when information
    # is incomplete.
    if missing:

        labels = {
            "soil_organic_carbon":
                "soil organic carbon (%)",

            "rainfall_mm":
                "average annual rainfall (mm)",

            "land_use":
                "land-use type",

            "region":
                "region or climate zone"
        }

        requested = [
            labels[field]
            for field in missing
        ]

        reply = (
            "I can assess the biodiversity conditions, "
            "but I need a little more information: "
            + ", ".join(requested)
            + "."
        )

        memory.add_message(
            req.conversation_id,
            "assistant",
            reply
        )

        return {
            "conversation_id": req.conversation_id,
            "type": "clarification",
            "message": reply,
            "environment": environment_data,
            "missing_variables": missing
        }

    # We have sufficient information for analysis
    result = analyze(env)

    memory.add_message(
        req.conversation_id,
        "assistant",
        result.model_dump_json()
    )

    return {
        "conversation_id": req.conversation_id,
        "type": "analysis",
        "message": (
            "I combined the available soil, climate, "
            "water and land-use variables and grounded "
            "the recommendations in the environmental "
            "knowledge base."
        ),
        "environment": environment_data,
        "analysis": result
    }


@app.get("/knowledge/{knowledge_id}")
def get_knowledge(knowledge_id: str):
    item = knowledge.get_by_id(knowledge_id)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Knowledge record not found"
        )

    return item
