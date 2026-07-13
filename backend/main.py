"""
backend/main.py

FastAPI application exposing the LogSentry AI analysis pipeline to the React SPA.

Run (from repo root):
    .venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import sys

# Ensure repo root is importable and is the working directory, regardless of where
# uvicorn was launched from (the src services load config.yaml by relative path).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.core.pipeline import AnalysisPipeline

app = FastAPI(
    title="LogSentry AI API",
    version="1.0.0",
    description="Enterprise log & diagnostics RCA pipeline (FastAPI backend for the React SPA).",
)

# The React dev server (Vite) runs on 5173 by default.
_origins = os.getenv("LOGSENTRY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    # Build heavy services once and stash on app.state for reuse across requests.
    pipeline = AnalysisPipeline(config_path="config.yaml")
    app.state.pipeline = pipeline

    # Knowledge integrations (Confluence/Jira + always-on Demo). Reuse the KB's
    # embedding model so the demo index costs no extra disk/memory.
    from backend.integrations.registry import ProviderRegistry
    from backend.integrations.reasoner import RetrievalReasoner
    registry = ProviderRegistry(embedding_service=pipeline.knowledge_base.vector_store.embedding_service)
    app.state.registry = registry
    app.state.reasoner = RetrievalReasoner(registry, pipeline.llm)


app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    pipeline: AnalysisPipeline = app.state.pipeline
    return {"status": "ok", "llm": pipeline.llm_health()}


# Serve the built React SPA (production/packaged mode) if it exists. In dev you run
# the Vite server on :5173 instead. Mounted last so /api/* always takes precedence.
_DIST = os.path.join(_ROOT, "frontend", "dist")
if os.path.isdir(_DIST):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="spa")
