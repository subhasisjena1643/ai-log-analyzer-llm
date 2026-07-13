# LogSentry AI — Enterprise Log Analyzer with LLM-Based Root Cause Analysis

An intelligent diagnostic platform that ingests enterprise log/diagnostic bundles, detects anomalies, and automatically identifies root causes using a distributed multi-agent pipeline and Large Language Models — now with retrieval-augmented reasoning over organizational knowledge (Confluence/Jira), NDA-safe data handling, and a production-grade web UI.

## Problem Statement
In large-scale enterprise systems, manual log analysis across logs, databases, JVM diagnostics, network captures, and healthchecks is time-consuming, error-prone, and doesn't scale to multi-gigabyte incident bundles.

## Solution
This project automates end-to-end incident diagnosis:
- Classifies and parses 8+ diagnostic file types in parallel (logs, SQL, PDF, JVM, PCAP/SIP, audio/CDR, config, SRE notes)
- Detects anomalies and correlates errors by time
- Generates a structured, evidence-grounded Root Cause Analysis via AWS Bedrock
- Matches the current incident against prior runbooks and resolved tickets (Confluence/Jira) to narrow down the fix
- Redacts confidential/PII data before anything is stored, embedded, or sent to the LLM

## Key Features
- **Distributed multi-agent diagnostics** — 8 specialized agents (App Log, SQL, PDF, JVM, PCAP/SIP, Audio, SRE Notes, Config) run in parallel, each compressing its findings so the LLM sees a dense summary instead of raw multi-GB text
- **LLM-powered Root Cause Analysis** with severity classification (INFO/WARN/ERROR/CRITICAL) and actionable fix recommendations
- **Retrieval-augmented reasoning** — matches incidents against Confluence runbooks and Jira tickets, with a synthetic Demo Mode that works with zero external connections
- **High-assurance consensus mode** — runs the RCA multiple times and keeps only claims that independent runs agree on, flagging single-run outliers as possible hallucinations
- **NDA-safe redaction** — PII, secrets, emails, IPs, keys, and confidential client/site names are neutralized before touching storage, embeddings, or the LLM
- **Adaptive ingestion** — automatically scales worker count and memory caps to the size of the bundle, so multi-GB uploads don't exhaust memory
- **Multi-source ingestion** — browser upload, local/network-share path (analyzed in place), or cloud (S3)
- **SIP/voice call diagnostics** — extracts SIP call-setup failures (4xx/5xx/6xx) directly from PCAP captures, with wav/mp3/CDR fallback for audio evidence
- **Two interfaces**: a modern FastAPI + React SPA (recommended) and the original Streamlit dashboard (legacy)

## Workflow
1. Ingest a diagnostic bundle (upload, local path, or cloud) — recursive archive extraction, adaptively bounded to the bundle's size
2. Classify and route each file to its specialized agent, executed in parallel
3. Detect anomalies and correlate errors across time
4. Redact confidential data, then generate a Root Cause Analysis via AWS Bedrock (optionally cross-checked with N-run consensus)
5. Retrieve and reason over similar past incidents/runbooks (Confluence/Jira or Demo Mode) to narrow the fix
6. Return a structured report: root cause, impact, suggested fix, confidence, evidence

## Sample Logs
Demo logs are available in `ipc/log/demo/`. A synthetic runbook/incident knowledge base and a synthetic SIP-capture generator are also included (`backend/demo/`) so the full pipeline — including knowledge retrieval and voice diagnostics — can be exercised without any real client data.

## Tech Stack
**Backend:** Python, FastAPI, AWS Bedrock (LLM), FAISS (vector search), sentence-transformers, boto3, Pandas
**Frontend:** React, TypeScript, Vite, Tailwind CSS (new SPA) · Streamlit (legacy dashboard)

## Architecture

```
Ingestion (upload / local-share / S3)
        │  adaptive size-aware planning
        ▼
Distributed Agent Orchestrator ── AppLog · SQL · PDF · JVM · PCAP/SIP · Audio · SRE Notes · Config
        │  compressed, redacted findings
        ▼
Bedrock LLM RCA  ──(optional)──▶  N-run Consensus (hallucination flagging)
        │
        ▼
Retrieval Reasoner ── Confluence / Jira / Demo Knowledge Base
        │
        ▼
Structured RCA Report (React SPA or Streamlit)
```

See [`backend/README.md`](backend/README.md) for the FastAPI/React architecture in detail, and `CLAUDE.md` for full codebase orientation.

## How to Run

### Option A — FastAPI + React (recommended)

```bash
git clone https://github.com/subhasisjena1643/ai-log-analyzer-llm
cd ai-log-analyzer-llm
pip install -r requirements.txt

# Single-process, packaged mode (builds the frontend on first run)
run_logsentry.bat
```
Then open **http://127.0.0.1:8000**.

For development with hot reload, run the backend and frontend separately:
```bash
.venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### Option B — Streamlit (legacy)

```bash
pip install -r requirements.txt
streamlit run app.py
```

**Note:** AWS Bedrock credentials (`.env`) are required for LLM-based analysis. Without them, the application still runs, with RCA falling back to a local rule-based/deterministic analyzer. Confluence/Jira are optional and connected live, in-app, at runtime — **Demo Mode** provides the full retrieval-reasoning experience with zero external connections and no credentials required.

## Privacy & NDA Safety
All free text reaching the LLM, the API response, or persistent storage is redacted first: PII, secrets, emails, IPs, and API keys are neutralized automatically, and operators can add their organization's confidential client/site names as an additional redaction layer. Parsed diagnostics run under neutral placeholder metadata rather than real client/zone identifiers. Redaction is enforced server-side and cannot be bypassed from the UI.

## Recent Enhancements
- **FastAPI + React SPA** — a decoupled, production-shaped web UI alongside the original Streamlit dashboard
- **Confluence + Jira retrieval-augmented reasoning** with runtime, in-app credential connection and a synthetic Demo Mode
- **NDA-safe redaction layer** enforced across the entire pipeline
- **Adaptive, multi-source ingestion** (upload / local-share / S3) with size-aware memory bounding for multi-GB bundles
- **SIP call-failure diagnostics** extracted directly from PCAP captures
- **High-assurance consensus mode** for cross-checked, hallucination-resistant RCA
- Improved LLM prompt for structured RCA (Root Cause, Impact, Fix, Confidence)
- Enhanced RAG with metadata filtering for accurate retrieval
- Support for multi-log analysis, file uploads, and anomaly/trend visualization

Full build history and verification details are documented in `run_#1.md` through `run_#4.md`.
