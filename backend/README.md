# LogSentry AI — Backend API + React SPA

This is the new professional UI stack that replaces the Streamlit app (`app.py`),
built **on top of the existing `src/services` pipeline** — the agent framework, RCA
engine, vector store, and Bedrock layer are unchanged. The legacy Streamlit app still
runs untouched during the transition.

```
┌──────────────┐    /api (proxied)   ┌───────────────────┐
│  React SPA    │  ───────────────▶   │  FastAPI backend   │
│  (frontend/)  │   SSE + JSON        │  (backend/)        │
└──────────────┘                     └─────────┬─────────┘
                                                │ reuses
                                       ┌────────▼─────────┐
                                       │  src/services/…   │  (unchanged)
                                       │  agents · RAG · KB │
                                       │  Bedrock · vectors │
                                       └───────────────────┘
```

## Layout

| Path | Purpose |
|------|---------|
| `backend/core/pipeline.py` | Framework-agnostic `AnalysisPipeline` extracted from `app.py` (upload → agents → anomaly/RCA → LLM → RAG). Returns JSON-safe results. |
| `backend/core/redaction.py` | NDA-safe de-identification: neutralizes client/site names, PII, secrets, emails, IPs, keys before anything is stored or sent to the LLM. |
| `backend/core/serialization.py` | Converts internal objects (LogEntry, numpy, datetimes) to JSON; strips client/zone fields. |
| `backend/api/routes.py` | `POST /api/analyze`, `POST /api/analyze/stream` (SSE progress), `POST /api/redact/preview`. |
| `backend/main.py` | FastAPI app + CORS + `/api/health`. |
| `frontend/` | Vite + React + TypeScript + Tailwind v4 SPA. |

## Run (development) — two processes, hot reload

```bash
# 1) Backend  (http://127.0.0.1:8000)
.venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000

# 2) Frontend (http://localhost:5173) — proxies /api to the backend
cd frontend && npm install    # first time only
npm run dev
```

Open http://localhost:5173.

## Run (packaged) — single process, minimal disk

```bat
run_logsentry.bat
```

Builds the frontend if needed, then serves the **UI + API from one FastAPI process**
on http://127.0.0.1:8000 (no Docker). `backend/main.py` mounts `frontend/dist/` when
it exists; `/api/*` always takes precedence over the static mount.

## Ingestion sources & scale

Three ways in, all streamed with an adaptive budget (`backend/core/ingestion.py`):

| Source | Endpoint | Notes |
|--------|----------|-------|
| Browser upload | `POST /api/analyze/stream` | multipart, streamed to a temp dir |
| Local / share path | `POST /api/analyze/path/stream` | analyzed **in place, no copy** — for very large bundles |
| Cloud (S3) | `POST /api/analyze/s3/stream` | streams `s3://bucket/prefix` to disk, analyzes, cleans up |

`POST /api/ingest/scan` previews a source's size and the derived plan (worker count +
memory caps) before you run. The planner scales caps by size tier (small→xlarge) so an
8–10 GB bundle bounds memory automatically; `ArchiveProcessor.process_directory` takes
an optional `max_structured_entries` cap (default unbounded, backward-compatible).

Restrict readable roots in production with `LOGSENTRY_ALLOWED_ROOTS` (os.pathsep-separated).

## NDA / privacy model

- All free text reaching the LLM, the API response, or storage is redacted first.
- Parsed logs are stripped of `client` / `zone` identifiers; analysis runs under
  neutral `GLOBAL` / `NEUTRAL` / `APP` metadata.
- Operators add client-specific names (e.g. an internal portal export) as
  **confidential terms** per run; those are neutralized like everything else.
- Redaction is enforced server-side and cannot be disabled from the UI.

## Roadmap (next phases)

- **Confluence + Jira retrieval** (REST API tokens): agents search runbooks/KB and
  prior incidents to find similar problems and narrow the fix. Config surface is in
  the **Integrations** view; connection wiring is pending.
- **PCAP/SIP**: Wireshark/tshark-based SIP call analysis with wav/mp3/CDR fallback.
