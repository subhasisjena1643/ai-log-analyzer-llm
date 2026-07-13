"""
backend/api/routes.py

HTTP surface for the analysis pipeline.

Endpoints
  POST /api/analyze          multipart upload of a diagnostic bundle -> full RCA result (JSON)
  POST /api/analyze/stream   same, but streams progress events (SSE) then the final result
  POST /api/redact/preview   preview the redaction layer on ad-hoc text (item #6 helper)

Uploaded files are written to a per-request temp directory, analyzed, and the temp
directory is always removed afterwards. Nothing is persisted server-side.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import tempfile
import threading
from typing import List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core.redaction import Redactor, RedactionConfig

router = APIRouter()

_CHUNK = 10 * 1024 * 1024  # 10 MB streaming writes for large bundles


def _parse_terms(confidential_terms: Optional[str]) -> List[str]:
    if not confidential_terms:
        return []
    # Accept JSON array or comma/newline separated
    try:
        parsed = json.loads(confidential_terms)
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [t.strip() for t in confidential_terms.replace("\n", ",").split(",") if t.strip()]


async def _save_uploads(files: List[UploadFile], dest: str) -> int:
    saved = 0
    for uf in files:
        target = os.path.join(dest, os.path.basename(uf.filename or f"upload_{saved}"))
        with open(target, "wb") as out:
            while True:
                chunk = await uf.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
        saved += 1
    return saved


def _knowledge_fn(request: Request, demo_mode: bool, use_knowledge: bool):
    """Build the retrieval-reasoning callback the pipeline invokes, or None."""
    if not use_knowledge:
        return None
    reasoner = getattr(request.app.state, "reasoner", None)
    if reasoner is None:
        return None
    return lambda response, redactor: reasoner.reason(response, demo_mode=demo_mode, redactor=redactor)


@router.post("/analyze")
async def analyze(
    request: Request,
    files: List[UploadFile] = File(...),
    query: str = Form("Analyze the uploaded diagnostics and identify the root cause."),
    confidential_terms: Optional[str] = Form(None),
    extra_context: str = Form(""),
    app_label: str = Form("APP"),
    demo_mode: bool = Form(True),
    use_knowledge: bool = Form(True),
    high_assurance: bool = Form(False),
):
    pipeline = request.app.state.pipeline
    tmp = tempfile.mkdtemp(prefix="logsentry_")
    try:
        n = await _save_uploads(files, tmp)
        if n == 0:
            return JSONResponse({"error": "No files uploaded."}, status_code=400)

        result = await asyncio.to_thread(
            pipeline.analyze_directory,
            tmp, query,
            confidential_terms=_parse_terms(confidential_terms),
            extra_context=extra_context,
            app_label=app_label,
            high_assurance=high_assurance,
            knowledge_fn=_knowledge_fn(request, demo_mode, use_knowledge),
        )
        return JSONResponse(result)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _stream_analysis(request: Request, source_dir: str, cleanup_dir: Optional[str], params: dict) -> StreamingResponse:
    """Shared SSE runner: analyze source_dir in a worker thread, stream progress +
    final result. cleanup_dir is removed afterwards (None = analyze in place, e.g. a
    user's local/share folder we must not delete)."""
    pipeline = request.app.state.pipeline
    knowledge_fn = _knowledge_fn(request, params["demo_mode"], params["use_knowledge"])
    events: "queue.Queue" = queue.Queue()

    def _progress(stage, status, pct):
        events.put({"type": "progress", "stage": stage, "status": status, "pct": round(float(pct), 3)})

    def _worker():
        try:
            result = pipeline.analyze_directory(
                source_dir, params["query"],
                confidential_terms=params["terms"], extra_context=params["extra_context"],
                app_label=params["app_label"], progress_cb=_progress, knowledge_fn=knowledge_fn,
                high_assurance=params.get("high_assurance", False),
            )
            events.put({"type": "result", "result": result})
        except Exception as e:
            events.put({"type": "error", "error": str(e)})
        finally:
            events.put({"type": "__end__"})
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    threading.Thread(target=_worker, daemon=True).start()

    async def _stream():
        while True:
            try:
                evt = await asyncio.to_thread(events.get, True, 30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if evt.get("type") == "__end__":
                break
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/analyze/stream")
async def analyze_stream(
    request: Request,
    files: List[UploadFile] = File(...),
    query: str = Form("Analyze the uploaded diagnostics and identify the root cause."),
    confidential_terms: Optional[str] = Form(None),
    extra_context: str = Form(""),
    app_label: str = Form("APP"),
    demo_mode: bool = Form(True),
    use_knowledge: bool = Form(True),
    high_assurance: bool = Form(False),
):
    """Browser-upload analysis with streamed progress (SSE)."""
    tmp = tempfile.mkdtemp(prefix="logsentry_")
    n = await _save_uploads(files, tmp)
    if n == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return JSONResponse({"error": "No files uploaded."}, status_code=400)
    return _stream_analysis(request, tmp, tmp, {
        "query": query, "terms": _parse_terms(confidential_terms), "extra_context": extra_context,
        "app_label": app_label, "demo_mode": demo_mode, "use_knowledge": use_knowledge,
        "high_assurance": high_assurance,
    })


@router.post("/ingest/scan")
async def ingest_scan(request: Request):
    """Preview a source's size and the adaptive processing plan before running."""
    from backend.core.ingestion import IngestionPlanner, resolve_local_path, IngestionError
    body = await request.json()
    source_type = body.get("source_type", "path")
    try:
        if source_type == "path":
            path = resolve_local_path(body.get("location", ""))
            profile = await asyncio.to_thread(IngestionPlanner.scan, path)
            return {"resolved": path, "profile": profile.to_dict()}
        return JSONResponse({"error": "Scan supports source_type='path' (cloud is sized on fetch)."}, status_code=400)
    except IngestionError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/analyze/path/stream")
async def analyze_path_stream(request: Request):
    """Analyze a local/share folder the backend can read — in place, no copy (SSE)."""
    from backend.core.ingestion import resolve_local_path, IngestionError
    body = await request.json()
    try:
        path = resolve_local_path(body.get("location", ""))
    except IngestionError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _stream_analysis(request, path, None, _json_params(body))


@router.post("/analyze/s3/stream")
async def analyze_s3_stream(request: Request):
    """Fetch a bundle from S3 (s3://bucket/prefix) then analyze it (SSE)."""
    from backend.core.ingestion import download_s3, IngestionError
    body = await request.json()
    uri = body.get("uri", "")
    tmp = tempfile.mkdtemp(prefix="logsentry_s3_")
    try:
        await asyncio.to_thread(download_s3, uri, tmp)
    except IngestionError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return JSONResponse({"error": f"S3 fetch failed: {e}"}, status_code=400)
    return _stream_analysis(request, tmp, tmp, _json_params(body))


def _json_params(body: dict) -> dict:
    """Extract analysis params from a JSON body (path/s3 endpoints)."""
    terms = body.get("confidential_terms", [])
    if isinstance(terms, str):
        terms = _parse_terms(terms)
    return {
        "query": body.get("query", "Analyze the diagnostics and identify the root cause."),
        "terms": terms,
        "extra_context": body.get("extra_context", ""),
        "app_label": body.get("app_label", "APP"),
        "demo_mode": bool(body.get("demo_mode", True)),
        "use_knowledge": bool(body.get("use_knowledge", True)),
        "high_assurance": bool(body.get("high_assurance", False)),
    }


@router.post("/redact/preview")
async def redact_preview(request: Request):
    body = await request.json()
    text = body.get("text", "")
    terms = body.get("confidential_terms", [])
    redactor = Redactor(RedactionConfig(confidential_terms=terms))
    res = redactor.redact_verbose(text)
    return {"redacted": res.text, "replacements": res.replacements, "summary": redactor.summary}


# ---------------------------------------------------------------------------
# Integrations — runtime, in-app connections (creds kept in memory only)
# ---------------------------------------------------------------------------

@router.get("/integrations/status")
async def integrations_status(request: Request, demo_mode: bool = True):
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        return {"providers": []}
    return {"providers": [s.to_dict() for s in registry.states(demo_mode)]}


@router.post("/integrations/confluence/connect")
async def connect_confluence(request: Request):
    body = await request.json()
    registry = request.app.state.registry
    st = await asyncio.to_thread(
        registry.connect_confluence,
        body.get("base_url", ""), body.get("email", ""), body.get("token", ""),
        body.get("spaces", []),
    )
    return st.to_dict()


@router.post("/integrations/jira/connect")
async def connect_jira(request: Request):
    body = await request.json()
    registry = request.app.state.registry
    st = await asyncio.to_thread(
        registry.connect_jira,
        body.get("base_url", ""), body.get("email", ""), body.get("token", ""),
        body.get("jql", ""),
    )
    return st.to_dict()


@router.post("/integrations/{provider}/disconnect")
async def disconnect_provider(request: Request, provider: str):
    registry = request.app.state.registry
    registry.disconnect(provider)
    return {"provider": provider, "connected": False}


@router.post("/knowledge/search")
async def knowledge_search(request: Request):
    """Ad-hoc retrieval preview (used by the Integrations UI to test a connection)."""
    body = await request.json()
    registry = request.app.state.registry
    query = body.get("query", "")
    demo_mode = bool(body.get("demo_mode", True))
    docs = await asyncio.to_thread(registry.search_all, query, demo_mode, 5)
    return {"matches": [d.to_dict() for d in docs]}
