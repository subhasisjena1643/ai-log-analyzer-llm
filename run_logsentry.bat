@echo off
REM ── LogSentry AI — single-process launcher (packaged mode) ──────────────
REM Serves the built React UI + API from one FastAPI process on :8000.
REM No Docker, minimal disk. First run builds the frontend if needed.
cd /d "%~dp0"

if not exist "frontend\dist\index.html" (
    echo [LogSentry] Building frontend ^(first run^)...
    pushd frontend
    if not exist "node_modules" call npm install
    call npm run build
    popd
)

echo [LogSentry] Starting on http://127.0.0.1:8000  (Ctrl+C to stop)
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
