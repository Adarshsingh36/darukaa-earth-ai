# How to apply this

Every file here is a complete, final version of that path in the repo —
not a diff. Copy each one to the same path in `darukaa-earth-ai/`,
overwriting what's there. No `git apply` needed.

## Fastest path (from inside your repo root)

Unzip this delivery somewhere, then from your repo root:

    cp -r /path/to/unzipped/* .

That overwrites the 19 modified files and adds the 8 new ones in one
shot, because every path below already matches the repo's own layout.

## New files (create these — they don't exist yet)
    backend/app/services/analysis.py
    backend/app/services/confidence.py
    backend/app/services/enrichment.py
    backend/app/services/land_cover.py
    backend/app/services/reference_stats.py
    backend/app/services/retrieval.py
    backend/app/services/units.py
    backend/requirements-dev.txt
    backend/scripts/threshold_audit.py
    backend/tests/__init__.py
    backend/tests/conftest.py
    backend/tests/test_api.py
    backend/tests/test_enrichment.py
    backend/tests/test_pipeline.py

## Modified files (overwrite these — they already exist)
    README.md
    backend/app/api/environment.py
    backend/app/data/knowledge.json
    backend/app/main.py
    backend/app/models/environment.py
    backend/app/models/schemas.py
    backend/app/services/chat.py
    backend/app/services/environment_data.py
    backend/app/services/knowledge.py
    backend/app/services/reasoning.py
    frontend/index.html
    frontend/src/App.jsx
    frontend/src/index.css

## Verify it worked

    cd backend
    pip install -r requirements.txt -r requirements-dev.txt
    pytest -q
    # expect: 103 passed

    uvicorn app.main:app --reload --port 8080
    # in another terminal:
    cd frontend && npm install && npm run dev

If pytest fails on an import, the most likely cause is a file that
didn't get copied — recheck the two lists above against what's on disk.
