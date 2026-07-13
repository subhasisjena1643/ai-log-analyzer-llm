# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

LogSentry AI is a Streamlit app that ingests enterprise diagnostic bundles (logs, SQL, PDFs, JVM dumps, PCAP, audio CDRs, SRE notes, config files — including nested archives up to ~15 GB), routes each file to a specialized agent, and produces an LLM-driven Root Cause Analysis for an IPC Unigy trading environment. AWS Bedrock (LLaMA 3) is the LLM; when Bedrock is throttled or unavailable, a local prompt-parsing fallback engine generates the RCA instead.

## Commands

```bash
# Run the app (primary entry point)
streamlit run app.py
# or on Windows: run_app.bat  (note: it activates venv\, but the repo venv is .venv\)

pip install -r requirements.txt

# Verify Bedrock connectivity / credentials
python test_bedrock_connection.py

# Regenerate demo IPC logs under ipc/log/demo/
python create_ipc_logs.py
```

There is **no test suite, linter, or build step** — `test_bedrock_connection.py` is a connectivity smoke check, not a unit test. Verify changes by running the Streamlit app.

## Configuration

- `.env` — AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`). Loaded via `python-dotenv`; required for LLM features. The app still runs without them but RCA falls back to local rule-based analysis.
- `config.yaml` — paths, embedding model (`all-MiniLM-L6-v2`), retrieval params, and the `agents:` block (`max_workers`, size limits, `llm_summary_max_tokens`). `paths.log_root` is a hardcoded local absolute path.
- `.streamlit/config.toml` — `maxUploadSize` (currently 5120 MB).

## Architecture

Two RCA pipelines coexist. Know which one a code path belongs to.

**Phase 3 distributed agent pipeline** (`src/services/agent_framework.py` + `src/services/agents/`) is the current primary flow for uploaded bundles:
1. `FileClassifier.classify()` routes each file to an agent type by extension first, then by content-signature regex for text files (JVM and SRE-notes signatures are checked before the generic `app_log` fallback — order matters). Archives are extracted by `ArchiveProcessor`, not routed to an agent.
2. `AgentOrchestrator.execute()` groups files by type and runs one agent per type **in parallel** (ThreadPoolExecutor, `max_workers` from config), each agent processing its files **serially**. `app.py` registers all 8 agents (`AppLogAgent`, `SQLAgent`, `PDFAgent`, `JVMAgent`, `PCAPAgent`, `AudioAgent`, `SRENotesAgent`, `ConfigAgent`) around `app.py:855`.
3. Every agent subclasses `BaseAgent` and returns a standardized `AgentResult` dataclass. New agents implement `analyze(filepath, filename)`; batching/summary/severity are inherited.
4. `AgentResultMerger.merge()` combines all `AgentResult`s into a unified context dict (backward-compatible with the older pipeline's `*_context` buckets). `build_llm_prompt_context()` compresses this to a small token budget, which `BedrockLLM.generate_from_agent_results()` turns into the final RCA. Agents parse locally so the LLM prompt stays small regardless of bundle size.

**Legacy RAG pipeline** (`src/services/rag_engine.py`, `analyze_logs()` in `app.py`) does keyword/vector search over log text plus a knowledge-base lookup, and produces rule-based + "simulated" RCA. Still wired into parts of the UI; largely superseded by the agent pipeline for multi-file bundles.

**LLM layer** (`src/services/bedrock_llm.py`): `BedrockLLM.generate()` calls Bedrock with retry/backoff on throttling. On repeated `ThrottlingException`/`LimitExceededException` it silently falls back to `_generate_fallback_rca()` — a large heuristic that reconstructs a structured RCA (Root Cause / Impact / Suggested Fix / Confidence / Evidence) by regex-scanning the prompt for DB, JVM, PDF-healthcheck, and SRE-inference signals. Both LLM and fallback paths must emit the same `### Root Cause / ### Impact Level / ...` markdown sections, since `app.py`'s `extract_section()` parses them.

**Retrieval / KB**: `FlexibleVectorStore` tries FAISS → Annoy → sklearn → numpy backends in order, so it works even where FAISS won't install. `KnowledgeBase` loads fixes from `data/kb/kb_fixes.csv` (regenerating `data/kb/fixes.json`), embeds them, and persists the index under `data/vectors/kb_index.*`. Embeddings come from `EmbeddingService` (sentence-transformers) with a Bedrock embeddings variant available.

**UI** (`app.py`, ~2000 lines): single Streamlit script with an 11-tab layout. `init_services()` is `@st.cache_resource`; LLM readiness is tracked in `st.session_state["llm_ready"]`/`["llm_error"]`. `generate_rca_markdown_report()` builds the exportable report.

## Conventions

- New file-type support = a new `BaseAgent` subclass in `src/services/agents/`, plus registration in `FileClassifier.EXTENSION_MAP` or `CONTENT_SIGNATURES` and an `orchestrator.register_agent(...)` call in `app.py`.
- Always open files with `encoding="utf-8"` (or `errors="ignore"`) — this is a Windows repo and several past fixes were `UnicodeEncodeError`/`UnicodeDecodeError` regressions.
- Keep the RCA markdown section headers stable across the LLM path and every fallback path; downstream parsing depends on them.
- `run_#1.md` / `run_#2.md` / `run_#3.md` are development run logs/notes, not code.
