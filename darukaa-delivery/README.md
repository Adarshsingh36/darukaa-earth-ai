# Darukaa.Earth

AI-powered environmental and biodiversity intelligence. The system
takes environmental observations (natural language, structured JSON, or
coordinates), derives interpretable condition indicators, reasons across
variables, retrieves scientific evidence per recommendation, and returns
actionable interventions with transparent uncertainty.

It is a decision-support prototype, not a validated ecological model.
Read "Scientific honesty" below before demoing it.

---

## Architecture

```
  natural language ──┐
  structured JSON  ──┼──> EnvironmentalInput (canonical units, strict schema)
  coordinates      ──┘              │
                                    ▼
                         ChatParser + units.py
                    (unit normalization, reported not silent)
                                    │
                                    ▼
                          ConversationMemory
                     (multi-turn accumulated state)
                                    │
                                    ▼
                    land_cover.py -> feature_engineering.py
                      (derived condition indicators)
                                    │
                                    ▼
                           ReasoningEngine
                (multi-variable rules -> candidate actions,
                 each carrying its own retrieval terms)
                                    │
                                    ▼
                   retrieval.py  EvidenceRetriever
             ONE ChromaDB query PER RECOMMENDATION, then
             hybrid rank + relevance floor + honest "insufficient"
                                    │
                                    ▼
                         confidence.py
            decomposed, weighted, bounded prototype score
                                    │
                                    ▼
                        analysis.py  AnalysisService
                                    │
                                    ▼
                          AnalysisResponse
```

`DATA -> FEATURES -> REASONING -> RETRIEVAL -> EVIDENCE ->
RECOMMENDATION`. The LLM layer (`services/llm.py`) is optional polish,
never the source of environmental truth. No endpoint forwards a user
prompt to a model and returns the generated text.

### Module map

| Path | Responsibility |
|---|---|
| `app/models/schemas.py` | Canonical `EnvironmentalInput` (`extra="forbid"`), response models |
| `app/services/units.py` | Unit normalization, external alias handling |
| `app/services/chat.py` | `ChatParser`, `ConversationMemory` |
| `app/services/land_cover.py` | Free-text land use -> canonical cover class |
| `app/services/feature_engineering.py` | Derived condition indicators |
| `app/services/reasoning.py` | Multi-variable rules -> candidate recommendations |
| `app/services/retrieval.py` | Recommendation-specific evidence retrieval + ranking |
| `app/services/confidence.py` | Decomposed prototype confidence |
| `app/services/enrichment.py` | Concurrent live geospatial fan-out, merge precedence |
| `app/services/reference_stats.py` | Percentile context from the training locations dataset |
| `app/services/analysis.py` | Orchestration shared by `/analyze` and `/chat` |
| `app/services/knowledge.py` | ChromaDB knowledge base, `get_by_id` |
| `app/services/{environment,soil,landcover}_data.py` | NASA POWER, SoilGrids, ESA WorldCover, GBIF |
| `app/main.py` | Thin FastAPI endpoints |

---

## Unit contract

The internal API representation uses explicit units. Ambiguous names
(`soil_organic_carbon`, `rainfall_mm`) are rejected by the schema and
must be normalized at the boundary via `POST /normalize` or
`units.normalize_external_payload`.

| Field | Unit |
|---|---|
| `soil_organic_carbon_g_per_kg` | g/kg |
| `precipitation_mm_day` | mm/day |
| `soil_moisture` | % |
| `temperature_c` | degrees Celsius |
| `soil_ph` | pH units (0-14) |

Conversions:

| Input | Canonical |
|---|---|
| `0.58% SOC` | `5.8 g/kg` (1% = 10 g/kg) |
| `5.8 g/kg SOC` | `5.8 g/kg` |
| `600 mm annual rainfall` | `1.6438 mm/day` (600 / 365.0) |
| `1.2 mm/day rainfall` | `1.2 mm/day` |

**Annual rainfall is never silently treated as daily rainfall.** Where a
unit is absent from free text, `units.infer_rainfall_unit` and
`units.infer_soc_unit` apply a documented heuristic *and the API reports
the assumption back to the user* in `normalization_notes`.

The mm/day figure is a mean daily rate. It discards seasonality, which
matters in monsoonal and Mediterranean climates. Water-stress indicators
built on it are prototype indicators.

---

## Scientific honesty

These are enforced in code and covered by tests, not just documented.

1. **No fabricated citations.** Every `EvidenceItem.id` resolves via
   `GET /knowledge/{id}`. Nothing is synthesised.
2. **No invented numbers.** Recommendations state *expected direction*
   ("increased soil organic carbon"), never an unsupported percentage.
   A test asserts no `\d+%` appears in any recommendation text.
3. **Insufficient evidence is declared.** Evidence below the relevance
   floor is dropped rather than attached. The recommendation is marked
   `evidence_status: "insufficient"` with an explanation.
4. **Confidence is labelled, bounded, decomposed.** Scores are capped at
   0.80, carry `confidence_label: "prototype confidence"` and an
   explicit uncalibrated caveat, and expose every weighted factor.
5. **Derived indicators are not ground truth.** Thresholds in
   `feature_engineering.py` are prototype thresholds, surfaced in
   `AnalysisResponse.caveats`.
6. **GBIF is an observation proxy.** Zero occurrence records means no
   recorded sampling, *not* zero biodiversity. Observation confidence is
   reported separately from recommendation confidence.
7. **Provenance is explicit.** `data_provenance` separates values the
   user supplied, values retrieved live (attributed per field in
   `field_sources`), and indicators that were derived.
8. **User measurements outrank models.** Live data fills gaps only. A
   supplied soil test is never overwritten by a 250 m SoilGrids raster,
   and every declined override is reported in `normalization_notes`.

---

## Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

First start downloads the `all-MiniLM-L6-v2` sentence-transformer and
seeds ChromaDB from `app/data/knowledge.json`. Override the index
location with `CHROMA_PATH`.

If ChromaDB or the embedding model is unavailable the API still starts.
`/health` reports `vector_index_available: false`, reasoning continues,
and every recommendation is honestly marked `insufficient` evidence.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the API at `http://127.0.0.1:8080`.

It is laid out as a **field assessment record**, not a chat app:

* **Observations** — every value with its provenance, so a figure from
  SoilGrids is visibly distinct from one the user measured. Unit
  conversions and declined overrides are listed beneath.
* **Condition** — the seven derived indicators plotted on ordinal
  scales against their reference ranges, the way a lab result is shown
  against a normal band. Colour is reserved for the condition ramp, so
  a colour on the page always encodes a measurement.
* **Reasoning** — the causal chain, in order.
* **Recommended interventions** — ranked by prototype confidence, each
  with why it works, affected metrics, time horizon, a confidence score
  that expands into its weighted factors, and citations linking to
  `/knowledge/{id}` so any source can be opened and checked.
* **What this assessment cannot tell you** — caveats, given the same
  typographic weight as the findings rather than shrunk into a
  footnote.

There is no seeded environmental state. The previous version opened
with invented values under the ambiguous field names
`soil_organic_carbon` and `rainfall_mm` (which the schema now rejects),
and rendered three hardcoded knowledge records as "evidence" whenever
retrieval returned nothing.

### Tests

```bash
cd backend
pytest -q
```

Tests run offline: `tests/conftest.py` provides `StubKnowledgeService`,
which honours the same contract as `KnowledgeService` but scores with
deterministic token overlap, so no model download or vector store is
needed.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Status + knowledge base availability |
| POST | `/analyze` | Full assessment from `EnvironmentalInput` |
| POST | `/chat` | Multi-turn conversational assessment |
| POST | `/chat/reset` | Clear one conversation's state |
| POST | `/normalize` | Convert legacy/external payload to canonical units |
| POST | `/knowledge/search` | Vector search over the knowledge base |
| GET | `/knowledge/{id}` | Resolve a citation to its full record |
| POST | `/environment/location` | Live enrichment from lat/lon |

### Live geospatial context

Supplying `latitude`/`longitude` to `/analyze` or mentioning
coordinates in `/chat` triggers a concurrent fan-out to all four
sources. Each has its own timeout and is awaited with
`return_exceptions=True`, so one dead API degrades that source only.
In `/chat` enrichment runs **before** the missing-variable check, so
the system does not ask for soil carbon that SoilGrids can answer.

```bash
curl -s localhost:8080/analyze -H 'content-type: application/json' -d '{
  "latitude": 18.99, "longitude": 73.12,
  "soil_organic_carbon_g_per_kg": 5.8
}'
```

Returns, alongside the assessment:

* `data_provenance.field_sources` — which source supplied each value
* `data_provenance.supplied_by_user` — values the caller gave
* `data_provenance.degraded_sources` — what failed and why
* `normalization_notes` — e.g. *"kept your value 5.8 rather than ISRIC
  SoilGrids's 7.2"*

### Demo scenario

```bash
curl -s localhost:8080/chat -H 'content-type: application/json' -d '{
  "conversation_id": "demo",
  "message": "My SOC is 0.58%, annual rainfall is 600 mm, pH is 5.4 and this is wheat monoculture."
}'
# -> clarification: asks for region; SOC already stored as 5.8 g/kg,
#    rainfall as 1.6438 mm/day

curl -s localhost:8080/chat -H 'content-type: application/json' -d '{
  "conversation_id": "demo",
  "message": "It is semi-arid."
}'
# -> full analysis; prior turn's values are remembered
```

---

## Known limitations

* **The knowledge base holds 11 records, all individually attributed
  to a specific, checkable publication.** The original 8 were
  organisation-and-year placeholders (`FAO, 2022`) rather than named
  publications; they have been rewritten to cite the specific report
  or paper each summary actually reflects — e.g. KB-002 now cites
  Poeplau & Don (2015, *Agriculture, Ecosystems & Environment*) on
  cover crops and soil carbon, KB-003 cites Bhagwat et al. (2008,
  *Trends in Ecology & Evolution*) on agroforestry as biodiversity
  refuge, and KB-008 cites FAO/ITPS's *Status of the World's Soil
  Resources* (2015) on acidification. Three further records
  (KB-009/010/011) were added from scratch to close retrieval gaps
  found while testing — FAO's *State of the World's Biodiversity for
  Food and Agriculture* (2019) for the monoculture-diversification
  rule, Stutter et al. (2019, *Journal of Environmental Quality*) on
  riparian buffers for the water-plus-habitat rule, and Abebaw et al.
  (2025, *Climate Resilience and Sustainability*) on agroforestry
  microclimate buffering for the thermal-stress rule. Every rule was
  re-checked after the rewrite to confirm it still retrieves its
  intended top match. The corpus is still only 11 records, so most
  queries will find *something* plausibly on-topic; growing it further
  is still the natural next step, but everything in it now names a
  source you could actually go read.
* **Confidence is uncalibrated.** It has never been validated against
  held-out ecological outcomes. It summarises input completeness, rule
  strength and evidence quality — nothing more.
* **`environment_training_final.csv` is wired in as reference context,
  not as calibration.** Every response now shows where a supplied value
  sits (percentile) against the 43 locations in this dataset -
  `derived_features.reference_dataset_context`, and a small percentile
  annotation next to each observation in the UI. It is presented as
  context alongside the fixed threshold classification, never in place
  of it. The reasoning behind NOT auto-fitting the thresholds to this
  sample, plus the actual boundary-vs-percentile numbers, are in
  `app/services/reference_stats.py` and
  `python -m scripts.threshold_audit` (from `backend/`): the sample is
  a 43-point convenience set skewed toward well-watered, higher-carbon
  sites, and refitting stress thresholds to its percentiles would tune
  the system to behave like this sample rather than like the ecology
  the thresholds are meant to describe.
* **Live enrichment is untested against the real APIs from here.** The
  fan-out, merge precedence and every degradation path are covered by
  tests with the sources monkeypatched, but the live endpoints were not
  called during development. Verify NASA POWER, SoilGrids, WorldCover
  and GBIF against real coordinates before demoing.
* **SoilGrids and WorldCover need `rasterio` and `pyproj`.** They are
  imported lazily, so a missing install degrades those two sources and
  records the reason rather than breaking the API.
