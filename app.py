
import streamlit as st
import plotly.graph_objects as go  
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
import yaml
import os
from collections import defaultdict
from dotenv import load_dotenv
from src.services.bedrock_llm import BedrockLLM
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import IsolationForest


# ✅ LOAD ENV FIRST
load_dotenv()

# (optional debug — keep for now)
bedrock_llm = BedrockLLM()

# ✅ ADD THIS BLOCK RIGHT HERE
try:
    is_ready, llm_error = bedrock_llm.health_check()
    st.session_state["llm_ready"] = is_ready
    st.session_state["llm_error"] = llm_error

except Exception as e:
    st.session_state["llm_ready"] = False
    st.session_state["llm_error"] = str(e)

def _legacy_analyze_log_with_llm(log_text):
    raise RuntimeError("Use analyze_log_with_llm instead.")


def classify_log(log):
    log_lower = log.lower()
    if "timeout" in log_lower:
        return "Timeout Issue"
    elif "connection" in log_lower:
        return "Network Issue"
    elif "error" in log_lower:
        return "Application Error"
    return "Other"
 
def format_archive_context_for_prompt(archive_context):
    if not archive_context:
        return ""
    
    parts = []
    
    # 1. SQL contexts
    sql_ctx = archive_context.get("sql_context", {})
    if sql_ctx:
        parts.append("=== EXTRACTED DATABASE (SQL) DIAGNOSTICS ===")
        for file, data in sql_ctx.items():
            parts.append(f"File: {file}")
            if data.get("tables_found"):
                parts.append(f"Tables Found: {', '.join(data['tables_found'])}")
            if data.get("errors_found"):
                parts.append("SQL Errors/Exceptions Found:")
                for err in data["errors_found"][:5]:
                    parts.append(f"  - {err}")
            if data.get("queries_count"):
                parts.append(f"Total Queries Executed: {data['queries_count']}")
        parts.append("")

    # 2. PDF contexts
    pdf_ctx = archive_context.get("pdf_context", {})
    if pdf_ctx:
        parts.append("=== EXTRACTED HEALTHCHECK REPORT (PDF) ===")
        for file, data in pdf_ctx.items():
            parts.append(f"Report File: {file}")
            if data.get("failures"):
                parts.append("Failed Checkpoints:")
                for f in data["failures"][:5]:
                    parts.append(f"  - [FAILED] {f}")
            if data.get("warnings"):
                parts.append("Degraded Checkpoints:")
                for w in data["warnings"][:5]:
                    parts.append(f"  - [WARN] {w}")
        parts.append("")

    # 3. Memory contexts
    mem_ctx = archive_context.get("memory_context", {})
    if mem_ctx:
        parts.append("=== EXTRACTED JVM & HEAP MEMORY DIAGNOSTICS ===")
        for file, data in mem_ctx.items():
            parts.append(f"Diagnostic File: {file}")
            if data.get("heap_max_mb") or data.get("heap_used_mb"):
                parts.append(f"  Heap Used: {data.get('heap_used_mb', 'N/A')} MB / Max: {data.get('heap_max_mb', 'N/A')} MB")
            if data.get("thread_states"):
                states_str = ", ".join([f"{k}: {v}" for k, v in data["thread_states"].items() if v > 0])
                parts.append(f"  JVM Thread Counts by State: {states_str}")
            if data.get("gc_pauses"):
                parts.append("  Garbage Collection Events / Pauses:")
                for pause in data["gc_pauses"][:3]:
                    parts.append(f"    * {pause}")
        parts.append("")

    # 4. Inference contexts
    inf_ctx = archive_context.get("inference_context", {})
    if inf_ctx:
        parts.append("=== PRIOR PROBLEM INVESTIGATIONS & INFERENCE NOTES ===")
        for file, data in inf_ctx.items():
            parts.append(f"Investigation File: {file}")
            content_preview = data.get("content", "")
            if content_preview:
                # preview first 1000 characters
                parts.append(content_preview[:1000])
                if len(content_preview) > 1000:
                    parts.append("... [Truncated Inference Context] ...")
        parts.append("")
        
    return "\n".join(parts)


def generate_rca_markdown_report(results, query, log_data):
    lines = []
    lines.append("# LogSentry AI - Root Cause Analysis (RCA) Incident Report")
    lines.append(f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Zone:** {log_data.get('zone', 'N/A')} | **Client:** {log_data.get('client', 'N/A')} | **App:** {log_data.get('app', 'N/A')} | **Version:** {log_data.get('version', 'N/A')}")
    lines.append(f"**Query asked:** \"{query}\"")
    lines.append("---")
    
    # AI Explanation Section
    lines.append("## 🤖 AI Root Cause Analysis (AWS Bedrock)")
    if results.get("llm_explanation"):
        lines.append(results["llm_explanation"])
    else:
        lines.append("*No AI explanation generated.*")
    lines.append("")
    
    # Automated RCA Summary
    lines.append("## 📊 Automated Analysis Summary")
    if results.get("automated_rca"):
        lines.append(results["automated_rca"])
    lines.append("")
    
    # Time correlation
    if results.get("time_correlation"):
        lines.append("### ⏱ Time Correlation Details")
        lines.append(results["time_correlation"].get("message", ""))
    lines.append("")
    
    # Extracted diagnostics summary
    lines.append("## 📦 Diagnostics Context Summary")
    file_counts = log_data.get("file_counts", {})
    if file_counts:
        for k, v in file_counts.items():
            if v > 0:
                lines.append(f"- **{k.capitalize()} files parsed:** {v}")
    else:
        lines.append(f"- **Total files analyzed:** {log_data.get('file_count', 0)}")
    lines.append("")
    
    # SQL contexts summary
    sql_ctx = log_data.get("sql_context", {})
    if sql_ctx:
        lines.append("### 🗄️ Database Contexts")
        for f, d in sql_ctx.items():
            lines.append(f"**File:** {f}")
            if d.get("tables_found"):
                lines.append(f"- Tables: {', '.join(d['tables_found'])}")
            if d.get("errors_found"):
                lines.append("- Errors:")
                for e in d["errors_found"][:3]:
                    lines.append(f"  - `{e}`")
    lines.append("")
    
    # JVM memory summary
    mem_ctx = log_data.get("memory_context", {})
    if mem_ctx:
        lines.append("### ☕ JVM Memory Contexts")
        for f, d in mem_ctx.items():
            lines.append(f"**File:** {f}")
            lines.append(f"- Heap Max: {d.get('heap_max_mb', 'N/A')} MB | Used: {d.get('heap_used_mb', 'N/A')} MB")
            if d.get("thread_states"):
                states_str = ", ".join([f"{k}: {v}" for k, v in d["thread_states"].items() if v > 0])
                lines.append(f"- Thread states: {states_str}")
    lines.append("")
    
    # PDF summary
    pdf_ctx = log_data.get("pdf_context", {})
    if pdf_ctx:
        lines.append("### 📄 PDF Health Checks Summary")
        for f, d in pdf_ctx.items():
            lines.append(f"**File:** {f}")
            if d.get("failures"):
                lines.append("- Failures:")
                for fail in d["failures"][:3]:
                    lines.append(f"  - `{fail}`")
    lines.append("")
    
    # Conclusion footer
    lines.append("---")
    lines.append("*Report generated by LogSentry AI | Production Support Portal*")
    
    return "\n".join(lines)


def analyze_log_with_llm(log_text, archive_context=None):
    try:
        extra_context = format_archive_context_for_prompt(archive_context)
        
        prompt = f"""
You are an expert production support engineer and site reliability engineer (SRE) analyzing logs and diagnostics for an enterprise trading communications environment (IPC Unigy / central console manager).

Analyze the logs and diagnostic evidence provided below and generate a highly precise, production-support focused Root Cause Analysis (RCA).

If additional diagnostic files (such as database schemas, JVM heap dumps, or healthcheck reports) are provided in the context, integrate them to establish correlation (e.g. database locks causing timeouts, JVM memory exhaustion leading to service drop-offs).

Return the answer in this exact structure:

### Root Cause
- Identify the most likely technical cause.
- Correlate log error signals with memory, database, or healthcheck warnings if available.
- Mention specific services/components (e.g. Unigy DB, replication engine, JVM Heap).

### Impact Level
- Low, Medium, or High.
- Explain the operational and trading impact (e.g., service failover, synchronization delay, console offline).

### Suggested Fix
- Provide practical, sequence-ordered remediation steps for the operations team.

### Confidence Level
- Low, Medium, or High.
- Cite the supporting evidence from logs/diagnostics.

### Evidence From Diagnostics
- Quote or summarize key log signals, SQL errors, JVM heap saturation, or PDF check failures.

Rules:
- Do not invent components, timestamps, or errors.
- If no JVM memory or SQL files are provided, do not make assumptions; focus strictly on standard log events.
- Be concise and actionable.

Log Events:
{log_text}
"""
        if extra_context:
            prompt += f"\nAdditional Diagnostics Context:\n{extra_context}\n"
            
        result = bedrock_llm.generate(prompt, max_tokens=700, temperature=0.2)
        st.session_state["llm_ready"] = True
        st.session_state["llm_error"] = ""
        return result
    except Exception as e:
        import traceback
        st.session_state["llm_ready"] = False
        st.session_state["llm_error"] = str(e)
        return f"LLM Error:\n{traceback.format_exc()}"


def detect_error_anomaly(structured_logs, threshold=5, bucket_minutes=5):
    error_logs = [
        log for log in structured_logs
        if getattr(log, "log_level", "").upper() == "ERROR"
        or "error" in str(log).lower()
    ]
    error_count = len(error_logs)
    buckets = defaultdict(int)

    for log in error_logs:
        parsed_time = parse_log_timestamp(getattr(log, "timestamp", None))
        if not parsed_time:
            continue
        bucket_minute = (parsed_time.minute // bucket_minutes) * bucket_minutes
        bucket_time = parsed_time.replace(minute=bucket_minute, second=0, microsecond=0)
        buckets[bucket_time] += 1

    spike_time = None
    spike_count = 0
    if buckets:
        spike_time, spike_count = max(buckets.items(), key=lambda item: item[1])

    spike_detected = spike_count >= threshold
    count_anomaly = error_count > threshold
    anomaly_flag = spike_detected or count_anomaly

    if spike_detected:
        explanation = (
            f"Error spike detected at {spike_time.strftime('%I:%M %p')}.\n\n"
            f"Reason:\n{spike_count} errors occurred within a "
            f"{bucket_minutes}-minute window, meeting the spike threshold of {threshold}.\n\n"
            "This indicates concentrated failure activity rather than isolated errors."
        )
    elif count_anomaly:
        explanation = (
            "An anomaly has been detected in the system logs.\n\n"
            f"Reason:\nThe observed error count ({error_count}) exceeded the "
            f"predefined threshold ({threshold}).\n\n"
            "This indicates abnormal system behavior such as repeated failures "
            "or operational instability."
        )
    else:
        explanation = (
            "No anomaly detected.\n\n"
            f"The total error count ({error_count}) is within the acceptable "
            f"threshold ({threshold}), and no time-based error spike was found."
        )

    return {
        "anomaly_detected": anomaly_flag,
        "message": explanation,
        "error_count": error_count,
        "threshold": threshold,
        "bucket_minutes": bucket_minutes,
        "spike_detected": spike_detected,
        "spike_time": spike_time.strftime("%I:%M %p") if spike_time else None,
        "spike_count": spike_count,
        "error_frequency": [
            {
                "time": bucket_time.strftime("%I:%M %p"),
                "count": count
            }
            for bucket_time, count in sorted(buckets.items())
        ]
    }


def parse_log_timestamp(timestamp):
    if not timestamp:
        return None
    if isinstance(timestamp, datetime):
        return timestamp

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(str(timestamp), fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
def detect_log_anomalies(logs):
    # Convert logs to numerical vectors
    vectorizer = TfidfVectorizer(max_features=500)
    X = vectorizer.fit_transform(logs)

    # Train Isolation Forest
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(X)

    predictions = model.predict(X)

    # -1 = anomaly, 1 = normal
    results = []
    for log, pred in zip(logs, predictions):
        results.append({
            "log": log,
            "anomaly": "YES" if pred == -1 else "NO"
        })

    return results

def extract_section(text, section):
    try:
        start = text.index(section) + len(section)
        end = min(
            [text.index(s, start) for s in [
                "Response:",
                "What happened:",
                "Possible root cause:",
                "Recommended fix:",
                "Additional considerations:"
            ] if s != section and s in text] + [len(text)]
        )
        return text[start:end].strip()
    except ValueError:
        return ""



from src.services.log_reader import LogReader
from src.services.rag_engine import RAGEngine
from src.services.knowledge_base import KnowledgeBase
from src.services.template_rca import TemplateRCA
from src.services.anomaly_detector import detect_error_anomaly
from src.services.time_correlation import correlate_errors_by_time
from src.services.automated_rca import generate_automated_rca
from src.services.archive_processor import ArchiveProcessor

# Phase 3: Distributed Agent Framework
from src.services.agent_framework import (
    FileClassifier, AgentOrchestrator, AgentResultMerger,
    AGENT_APP_LOG, AGENT_SQL, AGENT_PDF, AGENT_JVM,
    AGENT_PCAP, AGENT_AUDIO, AGENT_SRE_NOTES, AGENT_CONFIG,
    AGENT_ARCHIVE, AGENT_UNKNOWN
)
from src.services.agents.app_log_agent import AppLogAgent
from src.services.agents.sql_agent import SQLAgent
from src.services.agents.pdf_agent import PDFAgent
from src.services.agents.jvm_agent import JVMAgent
from src.services.agents.pcap_agent import PCAPAgent
from src.services.agents.audio_agent import AudioAgent
from src.services.agents.sre_notes_agent import SRENotesAgent
from src.services.agents.config_agent import ConfigAgent

# ... after imports ...

def analyze_logs(log_data, query=None, rag_engine=None, kb=None):
    """
    Analyze logs and return structured results
    """
    

    results = {
        'log_stats': {},
        'log_data': log_data,
        'exact_matches': [],
        'similar_errors': [],
        'error_lines': [],
        'kb_solutions': [],
        'solutions': []
    }
   # -------------------------
# -------------------------
    results['solutions'] = []   # make sure it's initialized

    for sol in results['kb_solutions']:
        results['solutions'].append({
        "error": sol.get("error_type", "Known Issue"),
        "solution": "\n".join(sol.get("solution_steps", [])),
        "confidence": sol.get("confidence", "Medium"),
        "severity": sol.get("severity", "Medium"),
        "prevention": sol.get("prevention", "Follow standard best practices"),
        "exact_match": True
    })
   

    if not log_data or 'structured' not in log_data:
        return results

    # -------------------------
    # BASIC STATS
    # -------------------------
    structured_logs = log_data.get('structured', [])

    total_errors = sum(1 for log in structured_logs if log.log_level == 'ERROR')
    unique_components = set(log.component for log in structured_logs if log.component)

    results['log_stats'] = {
        'file_count': log_data.get('file_count', 0),
        'total_errors': total_errors,
        'unique_components': len(unique_components)
    }

    # Extract error lines
    results['error_lines'] = [
        str(log) for log in structured_logs if log.log_level == 'ERROR'
    ]

    # -------------------------
    # RAG SEARCH
    # -------------------------
    if query and rag_engine:
        raw_log_text = log_data.get('raw', '')

        exact_matches = rag_engine.find_exact_matches(query, raw_log_text)
        results['exact_matches'] = exact_matches

        if not exact_matches:
            similar = rag_engine.find_similar_errors(query, raw_log_text)
            results['similar_errors'] = similar[:5]

    # -------------------------
    # KNOWLEDGE BASE SEARCH
    # -------------------------
    if kb and query:
        kb_solutions = []

        # 1️⃣ PRIMARY: semantic search using user query
        query_fixes = kb.search_similar_issues(query, top_k=3)

        for fix in query_fixes:
            kb_solutions.append({
                "error_type": fix["issue"],
                "root_cause": fix["root_cause"],
                "solution_steps": [
                    step.strip()
                    for step in fix["solution"].split(".")
                    if step.strip()
                ],
                "confidence": fix["confidence"]
            })

        # 2️⃣ SECONDARY: component-based search
        for component in list(unique_components)[:2]:
            component_fixes = kb.search_by_component(component)
            if component_fixes:
                kb_solutions.extend(component_fixes)

        # Save KB results
        results['kb_solutions'] = kb_solutions[:5]

    for sol in results['kb_solutions']:
        results['solutions'].append({
            "error": sol.get("error_type", "Known Issue"),
            "solution": "\n".join(sol.get("solution_steps", [])),
            "confidence": sol.get("confidence", "Medium"),
            "exact_match": True
        })

    return results


def build_uploaded_log_data(uploaded_files, zone, client, app, version, sub_version):
    parser = log_reader.parser
    
    # Instantiate ArchiveProcessor
    archive_processor = ArchiveProcessor(temp_dir="./temp_archive_extracted")
    archive_processor.clean_temp_dir()
    os.makedirs(archive_processor.temp_dir, exist_ok=True)
    
    try:
        # Write all uploaded files to the temp directory
        for uploaded_file in uploaded_files:
            target_path = os.path.join(archive_processor.temp_dir, uploaded_file.name)
            with open(target_path, "wb") as f:
                # Stream file in 10MB chunks to keep memory usage low for large archives (4-5 GB)
                uploaded_file.seek(0)
                while True:
                    chunk = uploaded_file.read(10 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                
            # If it's an archive, extract it
            if uploaded_file.name.endswith(('.zip', '.tar', '.tgz', '.tar.gz', '.gz')):
                archive_processor._extract_file(target_path, archive_processor.temp_dir)
                
        # Parse all extracted files
        archive_results = archive_processor.process_extracted_files(
            parser, zone, client, app, f"{version}/{sub_version}"
        )
    except Exception as e:
        archive_processor.clean_temp_dir()
        return None, f"Error processing uploaded files: {str(e)}"
    # NOTE: Do NOT clean_temp_dir here — the agent pipeline needs
    # the extracted files on disk. Cleanup is deferred to after agents run.
        
    return {
        "raw": "\n".join(archive_results["raw_logs_text"]),
        "structured": archive_results["structured_logs"],
        "file_count": len(archive_results.get("all_files_metadata", [])),
        "zone": zone,
        "client": client,
        "app": app,
        "version": f"{version}/{sub_version}",
        "source": "upload",
        "uploaded_files": [uploaded_file.name for uploaded_file in uploaded_files],
        "sql_context": archive_results["sql_context"],
        "pdf_context": archive_results["pdf_context"],
        "memory_context": archive_results["memory_context"],
        "inference_context": archive_results["inference_context"],
        "file_counts": archive_results["file_counts"],
        "all_files_metadata": archive_results.get("all_files_metadata", []),
        "_temp_extract_dir": archive_processor.temp_dir,
    }, None

# Page config
st.set_page_config(
    page_title="LogSentry AI - Enterprise RCA Analyzer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load config
with open("config.yaml", 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Initialize services
@st.cache_resource
def init_services():
    return LogReader(), RAGEngine(), KnowledgeBase(),TemplateRCA()

log_reader, rag_engine, kb, template_rca = init_services()

# DEBUG: Check KB load
st.sidebar.write("KB Entries Loaded:", len(kb.entries))


# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #374151;
        margin-top: 1rem;
    }
    .metric-card {
        background-color: #374151;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #3B82F6;
        margin: 0.5rem 0;
    }
    .log-line {
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
        padding: 0.2rem;
        border-radius: 0.2rem;
    }
    .log-error { background-color: #FEE2E2; color: #DC2626; }
    .log-warn { background-color: #FEF3C7; color: #D97706; }
    .log-info { background-color: #DBEAFE; color: #1D4ED8; }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #374151;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<h1 class="main-header">AI-Powered Log Analysis & RCA Assistant</h1>', unsafe_allow_html=True)


# Sidebar
with st.sidebar:
    st.header(" Analysis Parameters")

with st.sidebar:
    st.markdown("### 🤖 LLM Status")

    if st.session_state.get("llm_ready", False):
        st.success("LLM Connected")
    else:
        st.warning("LLM Not Connected")
        if st.session_state.get("llm_error"):
            st.caption(st.session_state["llm_error"])

    
    # Get available log structure
    log_structure = log_reader.get_available_logs()
    
    # Zone selection
    zones = list(log_structure.keys()) if log_structure else ["EMEA", "ASIA", "AMERICA"]
    zone = st.selectbox("Zone", zones, index=0 if zones else None)
    
    # Client selection
    clients = list(log_structure.get(zone, {}).keys()) if zone in log_structure else ["Barclays", "HSBC", "JPMorgan"]
    client = st.selectbox(" Client", clients, index=0 if clients else None)
    
    # Application selection
    apps = list(log_structure.get(zone, {}).get(client, {}).keys()) if zone in log_structure and client in log_structure[zone] else ["Unigy", "Pulse", "Touch"]
    app = st.selectbox(" Application", apps, index=0 if apps else None)
    
    # Version selection
    versions = log_structure.get(zone, {}).get(client, {}).get(app, []) if zone in log_structure and client in log_structure[zone] and app in log_structure[zone][client] else ["4.0", "3.0"]
    version = st.selectbox(" Version", versions, index=0 if versions else None)
    
    # Sub-version selection
    sub_versions = ["4.0.1", "3.0.1", "4.0.0", "3.0.0"]  # This could be dynamic
    sub_version = st.selectbox(" Sub-Version", sub_versions)

    # Log input source
    st.markdown("---")
    log_source = st.radio(
        "Log Input",
        ["Use selected log folder", "Scan custom local folder", "Upload log files/archives"],
        horizontal=False
    )
    uploaded_logs = []
    custom_folder_path = ""
    if log_source == "Upload log files/archives":
        uploaded_logs = st.file_uploader(
            "Upload log files, diagnostic archives, or IPC bundles",
            type=["log", "txt", "error", "info", "debug", "zip", "tar", "tgz", "gz",
                  "sql", "pdf", "pcap", "pcapng", "wav", "mp3", "ogg", "flac",
                  "properties", "conf", "cfg", "ini", "xml", "yaml", "yml",
                  "hprof"],
            accept_multiple_files=True
        )
    elif log_source == "Scan custom local folder":
        custom_folder_path = st.text_input("Enter local folder absolute path:", "")
    
    # Time range
    col1, col2 = st.columns(2)
    with col1:
        start_time = st.text_input("Start Time", "00:00")
    with col2:
        end_time = st.text_input("End Time", "23:59")
    
    # Query input
    st.markdown("---")
    query = st.text_area(
        " Enter your query or error description:",
        "Why did the system fail with timeout errors?",
        height=100
    )
    
    # Advanced options
    with st.expander(" Advanced Options"):
        top_k = st.slider("Top K results", 1, 10, 5)
        min_similarity = st.slider("Minimum similarity", 0.0, 1.0, 0.6)
        include_kb = st.checkbox("Include KB fixes", True)
        index_logs = st.checkbox("Index logs for future", True)
    
    # Action button
    analyze_btn = st.button(" Analyze Logs", type="primary", use_container_width=True)
    
    # Quick queries
    st.markdown("---")
    st.markdown("** Quick Queries:**")
    quick_queries = [
        "Find all timeout errors",
        "Show database connection issues",
        "Analyze 500 Internal Server Errors",
        "Check configuration mismatches"
    ]
    for q in quick_queries:
        if st.button(q, use_container_width=True):
            query = q
            st.rerun()

# Main content
if analyze_btn or 'results' in st.session_state:
    if analyze_btn:
        with st.spinner(" Reading logs..."):
            if log_source == "Upload log files/archives":
                if not uploaded_logs:
                    st.error("Please upload at least one log file or zip archive.")
                    st.stop()
                log_data, error = build_uploaded_log_data(
                    uploaded_logs,
                    zone,
                    client,
                    app,
                    version,
                    sub_version
                )
            elif log_source == "Scan custom local folder":
                if not custom_folder_path:
                    st.error("Please enter a custom local folder path.")
                    st.stop()
                if not os.path.exists(custom_folder_path):
                    log_data, error = None, f"Local path does not exist: {custom_folder_path}"
                else:
                    archive_processor = ArchiveProcessor()
                    archive_results = archive_processor.process_directory(
                        custom_folder_path,
                        log_reader.parser,
                        zone,
                        client,
                        app,
                        f"{version}/{sub_version}"
                    )
                    log_data = {
                        "raw": "\n".join(archive_results["raw_logs_text"]),
                        "structured": archive_results["structured_logs"],
                        "file_count": len(archive_results.get("all_files_metadata", [])),
                        "zone": zone,
                        "client": client,
                        "app": app,
                        "version": f"{version}/{sub_version}",
                        "source": "folder",
                        "sql_context": archive_results["sql_context"],
                        "pdf_context": archive_results["pdf_context"],
                        "memory_context": archive_results["memory_context"],
                        "inference_context": archive_results["inference_context"],
                        "file_counts": archive_results["file_counts"],
                        "all_files_metadata": archive_results.get("all_files_metadata", [])
                    }
                    error = None
            else:
                base_path = log_reader.get_log_path(zone, client, app, version, sub_version)
                if not os.path.exists(base_path):
                    log_data, error = None, f"Log path does not exist: {base_path}"
                else:
                    archive_processor = ArchiveProcessor()
                    archive_results = archive_processor.process_directory(
                        base_path,
                        log_reader.parser,
                        zone,
                        client,
                        app,
                        f"{version}/{sub_version}"
                    )
                    
                    log_data = {
                        "raw": "\n".join(archive_results["raw_logs_text"]),
                        "structured": archive_results["structured_logs"],
                        "file_count": len(archive_results.get("all_files_metadata", [])),
                        "zone": zone,
                        "client": client,
                        "app": app,
                        "version": f"{version}/{sub_version}",
                        "source": "folder",
                        "sql_context": archive_results["sql_context"],
                        "pdf_context": archive_results["pdf_context"],
                        "memory_context": archive_results["memory_context"],
                        "inference_context": archive_results["inference_context"],
                        "file_counts": archive_results["file_counts"],
                        "all_files_metadata": archive_results.get("all_files_metadata", [])
                    }
                    error = None
            
            if error:
                st.error(f"Error: {error}")
                st.stop()
            
            # ⚡ Phase 3: Distributed Agent Analysis
            with st.spinner("⚡ Running distributed agent analysis..."):
                agent_results_merged = None
                try:
                    # Determine the directory to scan for agents
                    agent_scan_dir = None
                    if log_source == "Upload log files/archives":
                        # Use the temp extraction dir that build_uploaded_log_data preserved
                        agent_scan_dir = log_data.get("_temp_extract_dir", "./temp_archive_extracted")
                    elif log_source == "Scan custom local folder" and custom_folder_path:
                        agent_scan_dir = custom_folder_path
                    else:
                        agent_scan_dir = log_reader.get_log_path(zone, client, app, version, sub_version)

                    if agent_scan_dir and os.path.exists(agent_scan_dir):
                        # Classify all files
                        classified_files = {}
                        for root, dirs, files in os.walk(agent_scan_dir):
                            for fname in files:
                                fpath = os.path.join(root, fname)
                                agent_type = FileClassifier.classify(fpath, fname)
                                if agent_type not in classified_files:
                                    classified_files[agent_type] = []
                                classified_files[agent_type].append((fpath, fname))

                        # Initialize orchestrator with all agents
                        agent_config = config.get("agents", {})
                        max_workers = agent_config.get("max_workers", 4)
                        orchestrator = AgentOrchestrator(max_workers=max_workers)
                        orchestrator.register_agent(AGENT_APP_LOG, AppLogAgent)
                        orchestrator.register_agent(AGENT_SQL, SQLAgent)
                        orchestrator.register_agent(AGENT_PDF, PDFAgent)
                        orchestrator.register_agent(AGENT_JVM, JVMAgent)
                        orchestrator.register_agent(AGENT_PCAP, PCAPAgent)
                        orchestrator.register_agent(AGENT_AUDIO, AudioAgent)
                        orchestrator.register_agent(AGENT_SRE_NOTES, SRENotesAgent)
                        orchestrator.register_agent(AGENT_CONFIG, ConfigAgent)

                        # Execute all agents in parallel
                        agent_kwargs = {
                            "zone": zone, "client": client,
                            "app": app, "version": f"{version}/{sub_version}"
                        }
                        agent_results = orchestrator.execute(
                            classified_files, **agent_kwargs
                        )

                        # Merge agent results
                        agent_results_merged = AgentResultMerger.merge(agent_results)

                        # Enrich log_data with agent context (backward compat)
                        if agent_results_merged:
                            # Merge structured logs from agents into existing log_data
                            existing_structured = log_data.get("structured", [])
                            agent_structured = agent_results_merged.get("structured_logs", [])
                            if agent_structured and not existing_structured:
                                log_data["structured"] = agent_structured

                            # Merge context buckets
                            for ctx_key in ["sql_context", "pdf_context", "memory_context",
                                            "inference_context", "pcap_context", "audio_context",
                                            "config_context"]:
                                existing_ctx = log_data.get(ctx_key, {})
                                agent_ctx = agent_results_merged.get(ctx_key, {})
                                if agent_ctx:
                                    existing_ctx.update(agent_ctx)
                                    log_data[ctx_key] = existing_ctx

                            # Merge file metadata
                            existing_meta = log_data.get("all_files_metadata", [])
                            agent_meta = agent_results_merged.get("all_files_metadata", [])
                            if agent_meta:
                                existing_meta.extend(agent_meta)
                                log_data["all_files_metadata"] = existing_meta

                            # Store agent results for UI rendering
                            log_data["agent_summaries"] = agent_results_merged.get("agent_summaries", {})
                            log_data["agent_timings"] = agent_results_merged.get("agent_timings", {})
                            log_data["overall_severity"] = agent_results_merged.get("overall_severity", "INFO")

                            # Update file counts
                            existing_counts = log_data.get("file_counts", {})
                            agent_counts = agent_results_merged.get("file_counts", {})
                            for k, v in agent_counts.items():
                                existing_counts[k] = existing_counts.get(k, 0) + v
                            log_data["file_counts"] = existing_counts

                except Exception as e:
                    st.warning(f"Agent analysis encountered an error (falling back to standard pipeline): {e}")
                finally:
                    # NOW clean up the temp extraction directory (agents are done)
                    temp_dir = log_data.get("_temp_extract_dir") if log_data else None
                    if temp_dir and os.path.exists(temp_dir):
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)

            with st.spinner(" Analyzing logs..."):
                # First, get basic analysis results
                results = analyze_logs(
                    log_data=log_data,
                    query=query,
                    rag_engine=rag_engine,
                    kb=kb
                )
                results["template_rca"] = template_rca.generate(
                    log_data.get("structured", [])
                )
                # 🔎 Phase 3 – Anomaly Detection
                anomaly_result = detect_error_anomaly(
                    structured_logs=log_data.get("structured", []),
                    threshold=5
                )

                results["anomaly"] = anomaly_result
                #  LLM Explanation — use agent-based pathway if available
                if anomaly_result.get("anomaly_detected"):
                    try:
                        sample_log = "\n".join(results.get("error_lines", [])[:5]) or "ERROR: Unknown issue"
                        results["error_type"] = classify_log(sample_log)

                        # Use agent-based LLM pathway if agent results available
                        if agent_results_merged:
                            llm_summary = AgentResultMerger.build_llm_prompt_context(agent_results_merged)
                            llm_output = bedrock_llm.generate_from_agent_results(llm_summary, query=query)
                        else:
                            # Fallback to legacy pathway
                            archive_ctx = {
                                "sql_context": log_data.get("sql_context", {}),
                                "pdf_context": log_data.get("pdf_context", {}),
                                "memory_context": log_data.get("memory_context", {}),
                                "inference_context": log_data.get("inference_context", {})
                            }
                            llm_output = analyze_log_with_llm(sample_log, archive_context=archive_ctx)

                        results["llm_explanation"] = llm_output
                        st.session_state["llm_ready"] = True
                    except Exception as e:
                        results["llm_explanation"] = f"LLM Error: {str(e)}"
                        st.session_state["llm_ready"] = False
                else:
                    results["error_type"] = classify_log(log_data.get("raw", ""))
                    results["llm_explanation"] = "No anomaly detected, so no AI explanation generated."
                
                # ⏱ Phase 3 – Time-Based Correlation
                time_corr = correlate_errors_by_time(
                    structured_logs=log_data.get("structured", []),
                    window_minutes=5,
                    threshold=3
                )

                results["time_correlation"] = time_corr

                # 🧠 Phase 3 – Automated RCA
                auto_rca = generate_automated_rca(
                    anomaly_result=results.get("anomaly", {}),
                    time_corr_result=results.get("time_correlation", {}),
                    total_errors=results.get("log_stats", {}).get("total_errors", 0)
                )

                results["automated_rca"] = auto_rca

                # Store agent analysis metadata in results for UI
                if agent_results_merged:
                    results["agent_summaries"] = agent_results_merged.get("agent_summaries", {})
                    results["agent_timings"] = agent_results_merged.get("agent_timings", {})
                    results["overall_severity"] = agent_results_merged.get("overall_severity", "INFO")
                    results["total_agent_findings"] = agent_results_merged.get("total_findings", 0)


                # Then, get RCA from RAG engine

                rca_result = rag_engine.process_query(
                    query=query,
                    log_data=log_data,
                    zone=zone,
                    client=client,
                    app=app
                )

            

                
                # Merge all results
                results.update({
                    'rca': rca_result.get('rca', 'No RCA generated'),
                    'semantic_matches': rca_result.get('semantic_matches', []),
                    'retrieval_filter': rca_result.get('retrieval_filter', {}),
                    'log_stats': {
                         **results.get('log_stats', {}),
                         'query_matches': rca_result.get('log_stats', {}).get('query_matches', 0)
                     }
                })

                # ✅ DO NOT overwrite KB fixes
                if not results.get('solutions'):
                  results['solutions'] = rca_result.get('solutions', [])

                
                st.session_state.results = results
                st.session_state.log_data = log_data
                
                source_label = "uploaded files" if log_data.get("source") == "upload" else "selected log folder"
                st.success(
                    f" Analysis complete! Found {len(log_data['structured'])} "

                    f"log entries across {log_data.get('file_count', 0)} {source_label}"
                )
    else:
        results = st.session_state.results
        log_data = st.session_state.log_data
    
    # Sidebar export button
    if 'results' in st.session_state and 'log_data' in st.session_state:
        report_md = generate_rca_markdown_report(st.session_state.results, query, st.session_state.log_data)
        st.sidebar.download_button(
            label="📥 Download RCA Report",
            data=report_md,
            file_name=f"RCA_Report_{st.session_state.log_data.get('app', 'App')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown",
            use_container_width=True
        )

    # Display results in tabs
    # --- Tabs definition ---

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs([
        "RCA Summary",
        "Analytics",
        "Evidence",
        "KB Fixes",
        "Log Details",
        "AI Explanation",
        "Extracted Diagnostics",
        "PCAP Analysis",
        "Audio Analysis",
        "Config Analysis",
        "Agent Timeline",
    ])

# --- Tab usage ---

    with tab6:
        st.subheader("🤖 AI Explanation")

        if results.get("llm_explanation"):
            st.success("LLM Reasoning Active")
            st.markdown(f"**Error Type:** {results.get('error_type', 'Other')}")
            st.markdown(results["llm_explanation"])
        else:
            st.info("Run analysis to generate AI explanation.")
   
    
    with tab1:
        st.subheader("🧠 Automated Root Cause Analysis")

        if results.get("rca"):
            st.success("Root Cause Identified")
            st.markdown("### Root Cause")
            st.write(results["rca"])

            impact = results["rca"].get("impact", "N/A") if isinstance(results["rca"], dict) else "N/A"
            affected = (
                ", ".join(results["rca"].get("affected_services", []))
                if isinstance(results["rca"], dict)
                else "N/A"
            )

            st.markdown(f"**Impact:** {impact}")
            st.markdown(f"**Affected Services:** {affected}")

        else:
            st.warning("No RCA generated")

    # RCA Summary
        
        # RCA Summary
        st.markdown("##  **Troubleshooting Results**")
        # ⏱ Time-Based Correlation Result
        if "time_correlation" in results:
            st.markdown("### ⏱ Time-Based Correlation")

            if results["time_correlation"]["correlated"]:
                st.warning(results["time_correlation"]["message"])
            else:
                st.success(results["time_correlation"]["message"])

        # 🤖 Automated RCA Summary
        if "automated_rca" in results:
                st.markdown("## 🤖 Automated RCA Summary")
                st.info(results["automated_rca"])

        # Query section
        st.markdown("###  What You Asked")
        st.info(f"**Query:** \"{query}\"")
        
        # What We Found section
        st.markdown("###  What We Found")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Error Lines", results['log_stats']['total_errors'])
        with col2:
            st.metric("Log Files", results['log_stats']['file_count'])
        with col3:
            st.metric("Unique Error Types", len(set(results.get('error_lines', []))))
        
        # 🚨 Anomaly Detection Result
        if "anomaly" in results:
            st.markdown("### 🚨 Anomaly Detection")

        if "anomaly" in results and results["anomaly"]:
            anomaly_data = results["anomaly"]
            st.markdown("### 🚨 Anomaly Detection")
            if anomaly_data.get("anomaly_detected"):
                st.error(anomaly_data.get("message", "Anomaly detected"))
            else:
                st.success(anomaly_data.get("message", "No anomaly detected"))
    

        if "anomaly" in results and results["anomaly"]:
            anomaly_data = results["anomaly"]
            
            if anomaly_data.get("spike_detected"):
                st.warning(
                    f"Error spike detected at {anomaly_data.get('spike_time')} "
                    f"({anomaly_data.get('spike_count')} errors in "
                    f"{anomaly_data.get('bucket_minutes')} minutes)"
                )

            st.write(
                f"Error Count: {anomaly_data.get('error_count', 0)} | "
                f"Threshold: {anomaly_data.get('threshold', 5)}"
            )

            if anomaly_data.get("error_frequency"):
                frequency_df = pd.DataFrame(anomaly_data["error_frequency"])
                if not frequency_df.empty:
                    st.bar_chart(frequency_df.set_index("time"))


    # Errors Found section - SCROLLABLE GREEN TEXT
    st.markdown("###  Errors Found")
    
    # Get error lines (prioritize exact matches, then similar errors)
    error_lines = []
    if 'exact_matches' in results and results['exact_matches']:
        error_lines = results['exact_matches']
        st.success(f" Found {len(error_lines)} exact matches")
    elif 'similar_errors' in results and results['similar_errors']:
        error_lines = results['similar_errors']
        st.warning(f" Found {len(error_lines)} similar errors")
    
    if error_lines:
        # Create a scrollable container for error lines
        max_height = 300  # Maximum height in pixels
        error_text = ""
        
        for i, line in enumerate(error_lines[:10], 1):  # Show first 10 errors
            # Truncate long lines for the display
            display_line = line
            if len(line) > 100:
                display_line = line[:100] + "..."
            error_text += f"{i}. {display_line}\n"
        
        # Create scrollable text area
        st.text_area(
            "Error Details",
            value=error_text,
            height=min(max_height, 30 + len(error_lines) * 25),  # Dynamic height
            key="error_display",
            disabled=True,  # Read-only
            label_visibility="collapsed"  # Hide the label
        )
        
        # Show full error details in expandable sections
        st.markdown("** Full Error Details:**")
        for i, line in enumerate(error_lines[:5], 1):  # Show first 5 full errors
            with st.expander(f"Error #{i}", expanded=False):
                st.code(line, language='text')
    else:
        st.info("No matching errors found")
    
    # Recommended Fix section
    st.markdown("###  Recommended Fix")
    
    if 'solutions' in results and results['solutions']:
        for i, sol in enumerate(results['solutions'][:2], 1):  # Show first 2 solutions
            with st.container():
                st.markdown(f"**{sol.get('error', 'Issue')}**")
                if sol.get('exact_match', False):
                    st.success(" **Exact match from Knowledge Base**")
                
                solution_text = sol.get('solution', '')
                if solution_text:
                    # Format as numbered list
                    lines = solution_text.split('\n')
                    for j, step in enumerate(lines, 1):
                        if step.strip():
                            st.write(f"{j}. {step.strip()}")
                st.markdown("---")
    else:
        st.info("No specific solution found in Knowledge Base")
        st.markdown("### 📄 Template RCA (Phase-3)")
        st.code(results.get("template_rca", "No RCA generated"))


    with tab2:
        st.subheader("📊 Log Analytics")

        # JVM Heap Memory & Threads Diagnostics Charts (Tailored for support/SRE teams)
        if 'log_data' in st.session_state and isinstance(st.session_state.log_data, dict):
            mem_ctx = st.session_state.log_data.get("memory_context", {})
            if mem_ctx:
                st.subheader("☕ JVM Heap Memory & Thread Analytics")
                for file, data in mem_ctx.items():
                    with st.expander(f"Diagnostics: {file}", expanded=True):
                        col_m1, col_m2 = st.columns(2)
                        
                        # 1. Heap Memory Chart
                        with col_m1:
                            heap_used = data.get("heap_used_mb")
                            heap_max = data.get("heap_max_mb")
                            heap_comm = data.get("heap_committed_mb") or heap_max
                            
                            if heap_used is not None:
                                labels = ['Used Heap', 'Free/Unallocated Heap']
                                values = [heap_used, max(0, (heap_max or heap_comm or (heap_used * 1.5)) - heap_used)]
                                
                                fig_heap = go.Figure(data=[go.Pie(
                                    labels=labels,
                                    values=values,
                                    hole=0.4,
                                    marker_colors=['#EF4444' if (heap_used/(heap_max or heap_comm or 1)) > 0.8 else '#3B82F6', '#10B981']
                                )])
                                fig_heap.update_layout(
                                    title=f"Heap Allocation (Max: {heap_max or 'N/A'} MB, Committed: {heap_comm or 'N/A'} MB)",
                                    height=300
                                )
                                st.plotly_chart(fig_heap, use_container_width=True)
                            else:
                                st.info("Heap memory sizes not explicitly found in this diagnostic file.")
                                
                        # 2. Thread State Counts Chart
                        with col_m2:
                            thread_states = data.get("thread_states")
                            if thread_states and any(v > 0 for v in thread_states.values()):
                                states = list(thread_states.keys())
                                counts = list(thread_states.values())
                                
                                fig_threads = px.bar(
                                    x=states,
                                    y=counts,
                                    title="JVM Thread State Distribution",
                                    labels={'x': 'Thread State', 'y': 'Count'},
                                    color=states,
                                    color_discrete_map={
                                        'RUNNABLE': '#10B981',
                                        'WAITING': '#3B82F6',
                                        'TIMED_WAITING': '#F59E0B',
                                        'BLOCKED': '#EF4444'
                                    }
                                )
                                fig_threads.update_layout(height=300, showlegend=False)
                                st.plotly_chart(fig_threads, use_container_width=True)
                            else:
                                st.info("Thread status metrics not found in this diagnostic file.")

        if results.get("structured_logs"):
            df = pd.DataFrame(results["structured_logs"])

            if "severity" in df.columns:
                severity_count = df["severity"].value_counts().reset_index()
                severity_count.columns = ["Severity", "Count"]

                fig = px.bar(
                    severity_count,
                    x="Severity",
                    y="Count",
                    title="Log Severity Distribution",
                    color="Severity"
                )
                st.plotly_chart(fig, use_container_width=True)

            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                time_series = df.groupby(df["timestamp"].dt.hour).size().reset_index(name="count")

                fig2 = px.line(
                    time_series,
                    x="timestamp",
                    y="count",
                    title="Logs Over Time (Hourly)"
                )
                st.plotly_chart(fig2, use_container_width=True)

        else:
            st.info("No analytics available")

    # Analytics Dashboard
        st.subheader(" **Log Analysis Dashboard**")
        
        if 'results' in st.session_state:
            results = st.session_state.results
            
            # Create metrics row - HANDLE BOTH OLD AND NEW FORMATS
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                # Log files
                if 'log_data' in st.session_state:
                    st.metric(" Files", st.session_state.log_data.get('file_count', 0))
                else:
                    st.metric(" Files", 0)
            
            with col2:
                # Total errors - handle both formats
                if 'log_stats' in results and 'total_errors' in results['log_stats']:
                    # Old format
                    st.metric(" Total Errors", results['log_stats']['total_errors'])
                elif 'error_lines' in results:
                    # New simplified format
                    st.metric(" Total Errors", len(results.get('error_lines', [])))
                else:
                    st.metric(" Total Errors", 0)
            
            with col3:
                import re
                # Components affected
                if 'log_stats' in results and 'unique_components' in results['log_stats']:
                    st.metric(" Components", results['log_stats']['unique_components'])
                else:
                    # Count from error lines if available
                    if 'exact_matches' in results and results['exact_matches']:
                        components = set()
                        for line in results['exact_matches']:
                            match = re.search(r'Component=([A-Za-z]+)', line)
                            if match:
                                components.add(match.group(1))
                        st.metric(" Components", len(components))
                    else:
                        st.metric(" Components", 0)
            
            with col4:
                # Confidence
                if 'exact_matches' in results and results['exact_matches']:
                    st.metric(" Confidence", "High")
                elif 'similar_errors' in results and results['similar_errors']:
                    st.metric(" Confidence", "Medium")
                else:
                    st.metric(" Confidence", "Low")
            
            # Visualization section
            st.subheader(" **Error Distribution**")
            
            if 'log_data' in st.session_state and 'structured' in st.session_state.log_data:
                df = pd.DataFrame([entry.to_dict() for entry in st.session_state.log_data['structured']])
                
                if not df.empty:
                    # Create two columns for charts - RESTORED PIE CHART
                    chart_col1, chart_col2 = st.columns(2)
                    
                    with chart_col1:
                        # Error types pie chart - RESTORED FROM OLD VERSION
                        if 'error_code' in df.columns and df['error_code'].notna().any():
                            error_counts = df['error_code'].value_counts().head(8)
                            if not error_counts.empty:
                                fig1 = go.Figure(data=[go.Pie(
                                    labels=error_counts.index,
                                    values=error_counts.values,
                                    hole=0.3,
                                    marker_colors=px.colors.sequential.RdBu
                                )])
                                fig1.update_layout(
                                    title="Top Error Types",
                                    showlegend=True,
                                    height=400
                                )
                                st.plotly_chart(fig1, use_container_width=True)
                            else:
                                st.info("No error codes found in logs")
                        else:
                            st.info("Error code data not available")
                    
                    with chart_col2:
                        # Component bar chart
                        if 'component' in df.columns:
                            comp_counts = df['component'].value_counts().head(10)
                            if not comp_counts.empty:
                                fig2 = px.bar(
                                    x=comp_counts.index,
                                    y=comp_counts.values,
                                    title="Most Affected Components",
                                    labels={'x': 'Component', 'y': 'Error Count'},
                                    color=comp_counts.values,
                                    color_continuous_scale='Viridis'
                                )
                                fig2.update_layout(height=400)
                                st.plotly_chart(fig2, use_container_width=True)
                            else:
                                st.info("No component data available")
                        else:
                            st.info("Component data not available")
                    
                    # ADD TIME SERIES SECTION BACK
                    st.subheader(" Error Timeline")
                    if 'timestamp' in df.columns and df['timestamp'].notna().any():
                        try:
                            # Convert timestamps
                            df['time_parsed'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
                            df = df.dropna(subset=['time_parsed'])
                            
                            if not df.empty:
                                # Group by hour
                                df['hour'] = df['time_parsed'].dt.floor('h')
                                hourly_counts = df.groupby('hour').size().reset_index(name='count')
                                
                                fig3 = px.line(
                                    hourly_counts,
                                    x='hour',
                                    y='count',
                                    title="Errors Over Time (Last 24 Hours)",
                                    markers=True
                                )
                                fig3.update_layout(
                                    xaxis_title="Time",
                                    yaxis_title="Error Count",
                                    hovermode='x unified'
                                )
                                st.plotly_chart(fig3, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Could not create timeline: {str(e)}")
                    
                    # Error Severity Breakdown
                    st.subheader(" Error Severity")
                    if 'log_level' in df.columns:
                        severity_counts = df['log_level'].value_counts()
                        if not severity_counts.empty:
                            col1, col2, col3 = st.columns(3)
                            levels = {'ERROR': '🔴', 'WARN': '🟡', 'INFO': '🟢'}
                            
                            for level, emoji in levels.items():
                                count = severity_counts.get(level, 0)
                                if level == 'ERROR':
                                    with col1:
                                        st.metric(f"{emoji} Critical Errors", count)
                                elif level == 'WARN':
                                    with col2:
                                        st.metric(f"{emoji} Warnings", count)
                                elif level == 'INFO':
                                    with col3:
                                        st.metric(f"{emoji} Info Messages", count)
                else:
                    st.info(" No structured log data available for visualization")
            else:
                st.info(" Load logs first using the Analyze button")
        else:
            st.info(" Run an analysis first to see dashboard data")

        
        
    with tab3:
       
    # Evidence
        st.subheader(" **What We Found in Logs**")
        
        if 'results' in st.session_state:
            results = st.session_state.results
            
            if 'exact_matches' in results:
                exact_matches = results['exact_matches']
                similar_errors = results.get('similar_errors', [])
                semantic_matches = results.get('semantic_matches', [])
                retrieval_filter = results.get('retrieval_filter', {})

                if retrieval_filter.get("app"):
                    st.markdown(f"**RAG Filter:** App = `{retrieval_filter['app']}`")

                if semantic_matches:
                    st.subheader(" **App-Filtered Semantic Matches**")
                    for i, match in enumerate(semantic_matches[:3], 1):
                        label = f"Semantic match #{i} | {match.get('app', 'Unknown')} | score {match.get('similarity', 'N/A')}"
                        with st.expander(label, expanded=(i == 1)):
                            st.code(match.get("message", ""))
                
                if exact_matches:
                    st.success(f" Found {len(exact_matches)} EXACT matches for your query")
                    st.subheader(" **Exact Matches**")
                    for i, line in enumerate(exact_matches[:3], 1):
                        with st.expander(f"Match #{i}", expanded=(i==1)):
                            st.code(line)
                elif similar_errors:
                    st.warning(f" No exact matches. Found {len(similar_errors)} similar errors")
                    st.subheader(" **Similar Errors Found**")
                    for i, line in enumerate(similar_errors[:3], 1):
                        with st.expander(f"Similar error #{i}", expanded=(i==1)):
                            st.code(line)
                else:
                    st.info(" No matching errors found")
            
            # Solutions
            if 'solutions' in results and results['solutions']:
                st.subheader(" **Recommended Solution**")
                for sol in results['solutions'][:2]:  # Show max 2 solutions
                    with st.container():
                        st.markdown(f"### **{sol.get('error', 'Issue')}**")
                        if sol.get('exact_match', False):
                            st.success(" **Exact match from Knowledge Base**")
                        
                        solution_text = sol.get('solution', '')
                        if solution_text:
                            steps = solution_text.split('\n')
                            for step in steps:
                                if step.strip():
                                    st.write(f"• {step.strip()}")
                        
                        st.markdown("---")



    with tab4:
        # KB Fixed Log Details
        st.subheader(" **Knowledge Base Solutions**")
        
        if 'results' in st.session_state:
            results = st.session_state.results
            
            # Check if we have solutions in results
            if 'kb_solutions' in results and results['kb_solutions']:
                st.success(f" Found {len(results['kb_solutions'])} solutions in Knowledge Base")
                
                # Display each solution
                for i, solution in enumerate(results['kb_solutions'], 1):
                    with st.expander(f"Solution #{i}: {solution.get('error_type', 'Unknown Error')}"):
                        # Solution details
                        st.write(f"**Error Type:** {solution.get('error_type', 'N/A')}")
                        st.write(f"**Component:** {solution.get('component', 'N/A')}")
                        st.write(f"**Confidence:** {solution.get('confidence', 'N/A')}")
                        
                        # Root cause
                        st.write("**Root Cause:**")
                        st.write(solution.get('root_cause', 'No root cause analysis available'))
                        
                        # Solution steps
                        st.write("**Solution Steps:**")
                        solution_steps = solution.get('solution_steps', [])
                        if solution_steps:
                            for j, step in enumerate(solution_steps, 1):
                                st.write(f"{j}. {step}")
                        else:
                            st.write("No specific steps provided")
                        
                        # Prevention
                        if solution.get('prevention'):
                            st.write("**Prevention Tips:**")
                            st.write(solution.get('prevention'))
                        
                        # Related resources
                        if solution.get('resources'):
                            st.write("**Related Resources:**")
                            for resource in solution.get('resources', []):
                                st.write(f"- {resource}")
            
            elif 'exact_matches' in results and results['exact_matches']:
                # If we have exact matches but no KB solutions, search for them
                st.info(" Searching for solutions in Knowledge Base...")
                
                # Placeholder for KB search logic
                # In a real implementation, you would:
                # 1. Extract error patterns
                # 2. Query your knowledge base
                # 3. Display matching solutions
                
                # Example mock data
                with st.expander("Potential Solution: Connection Timeout Error"):
                    st.write("**Error Type:** Database Connection Timeout")
                    st.write("**Root Cause:** Connection pool exhaustion")
                    st.write("**Solution:** Increase connection pool size and add connection validation")
                    st.write("1. Check current connection pool settings")
                    st.write("2. Increase max pool size to 50")
                    st.write("3. Add validation query to connection pool")
                    st.write("4. Monitor connection usage metrics")
            else:
                st.info(" No errors found to search for solutions. Run an analysis first.")
        else:
            st.info(" Run an analysis first to see solutions")



    with tab5:
        if 'log_data' not in st.session_state:
            st.info("Run analysis first.")
        else:
            log_data = st.session_state.log_data
            # Raw Log Details
            st.subheader(" Raw Log Contents")
        
            # Log level filter
            log_levels = ["ALL", "ERROR", "WARN", "INFO", "DEBUG"]
            selected_level = st.selectbox("Filter by log level", log_levels)
        
            # Display logs with syntax highlighting
            raw_logs = log_data['raw']
            lines = raw_logs.split('\n')
        
            # Create a scrollable log viewer
            log_container = st.container()
            with log_container:
                for line in lines[:config['ui']['max_log_display']]:
                    if selected_level == "ALL" or selected_level in line:
                        line_lower = line.lower()
                        if 'error' in line_lower:
                            st.markdown(f'<div class="log-line log-error">{line}</div>', unsafe_allow_html=True)
                        elif 'warn' in line_lower:
                            st.markdown(f'<div class="log-line log-warn">{line}</div>', unsafe_allow_html=True)
                        elif 'info' in line_lower:
                            st.markdown(f'<div class="log-line log-info">{line}</div>', unsafe_allow_html=True)
                        else:
                            st.code(line, language='bash')
        
            if len(lines) > config['ui']['max_log_display']:
                st.warning(f"Showing first {config['ui']['max_log_display']} lines. Total lines: {len(lines)}")

    with tab7:
        st.subheader("📦 Extracted Archive Diagnostics")
        if 'log_data' in st.session_state and isinstance(st.session_state.log_data, dict):
            log_data = st.session_state.log_data
            sql_ctx = log_data.get("sql_context", {})
            pdf_ctx = log_data.get("pdf_context", {})
            mem_ctx = log_data.get("memory_context", {})
            inf_ctx = log_data.get("inference_context", {})
            files_meta = log_data.get("all_files_metadata", [])
            
            has_data = any([sql_ctx, pdf_ctx, mem_ctx, inf_ctx, files_meta])
            
            if not has_data:
                st.info("No archive diagnostics found in the loaded context. Upload a zip archive to extract SQL, PDF reports, JVM dumps, or notes.")
            else:
                # 0. Parsed Files Inventory Table
                if files_meta:
                    st.markdown("### 📋 Parsed Files Inventory")
                    df_files = pd.DataFrame(files_meta)
                    df_files.columns = ["File Name", "Relative Path", "Detected File Type", "Size", "Highlights/Summary"]
                    st.dataframe(df_files, use_container_width=True, hide_index=True)
                    st.markdown("---")
                # 1. SQL
                if sql_ctx:
                    st.markdown("### 🗄️ Database (SQL) Context")
                    for file, data in sql_ctx.items():
                        with st.expander(f"SQL Schema/Dump: {file}", expanded=False):
                            col_s1, col_s2 = st.columns(2)
                            with col_s1:
                                st.write(f"**Total Queries/Lines:** {data.get('total_lines', 'N/A')} lines")
                                if data.get("tables_found"):
                                    st.write("**Tables Discovered:**")
                                    for t in data["tables_found"]:
                                        st.write(f"- `{t}`")
                                else:
                                    st.write("No CREATE TABLE statements found.")
                            with col_s2:
                                if data.get("errors_found"):
                                    st.write("**Database Errors Found:**")
                                    for e in data["errors_found"][:5]:
                                        st.error(e)
                                else:
                                    st.success("No SQL syntax or runtime errors found in preview.")
                            
                            st.write("**SQL Content Preview:**")
                            st.code(data.get("preview", ""), language="sql")
                
                # 2. PDF Reports
                if pdf_ctx:
                    st.markdown("### 📄 PDF Health Checks")
                    for file, data in pdf_ctx.items():
                        with st.expander(f"PDF Report: {file}", expanded=False):
                            st.write(f"**Pages:** {data.get('total_pages', 'N/A')}")
                            
                            # Show failures
                            failures = data.get("failures", [])
                            warnings = data.get("warnings", [])
                            
                            if failures:
                                st.write("**Critical Failures Detected:**")
                                for f in failures:
                                    st.error(f)
                            if warnings:
                                st.write("**Warnings/Degradations Detected:**")
                                for w in warnings:
                                    st.warning(w)
                                    
                            if not failures and not warnings:
                                st.success("No failures or warnings found in health check report.")
                                
                            st.write("**PDF Extracted Text (First 2000 chars):**")
                            st.code(data.get("extracted_text", "")[:2000] + "\n...", language="text")

                # 3. Memory
                if mem_ctx:
                    st.markdown("### ☕ JVM & Memory Dumps")
                    for file, data in mem_ctx.items():
                        with st.expander(f"JVM Memory Diagnostics: {file}", expanded=False):
                            st.write(f"**Max Heap:** {data.get('heap_max_mb', 'N/A')} MB")
                            st.write(f"**Committed Heap:** {data.get('heap_committed_mb', 'N/A')} MB")
                            st.write(f"**Used Heap:** {data.get('heap_used_mb', 'N/A')} MB")
                            
                            if data.get("gc_pauses"):
                                st.write("**GC events detected in file:**")
                                for pause in data["gc_pauses"][:5]:
                                    st.write(f"- `{pause}`")
                                    
                            st.write("**Memory Report Preview:**")
                            st.code(data.get("raw_preview", ""), language="text")

                # 4. Inferences
                if inf_ctx:
                    st.markdown("### 📝 Incident Inferences & Investigation Notes")
                    for file, data in inf_ctx.items():
                        with st.expander(f"Incident Notes: {file}", expanded=True):
                            st.markdown(data.get("content", ""))
        else:
            st.info("Run analysis to view extracted archive diagnostics.")

    # ===== TAB 8: PCAP Analysis =====
    with tab8:
        st.subheader("🌐 PCAP / Network Analysis")
        if 'log_data' in st.session_state and isinstance(st.session_state.log_data, dict):
            pcap_ctx = st.session_state.log_data.get("pcap_context", {})
            if pcap_ctx:
                for file, data in pcap_ctx.items():
                    with st.expander(f"📡 {file}", expanded=True):
                        if data.get("packet_count"):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Packets", f"{data.get('packet_count', 0):,}")
                            with col2:
                                st.metric("Duration", f"{data.get('duration_seconds', 0)}s")
                            with col3:
                                st.metric("Unique Sources", data.get("unique_sources", "N/A"))

                            # Protocol distribution chart
                            protocols = data.get("protocols", {})
                            if protocols:
                                proto_df = pd.DataFrame(
                                    [{"Protocol": k, "Count": v} for k, v in protocols.items()]
                                )
                                fig = px.bar(proto_df, x="Protocol", y="Count",
                                            title="Protocol Distribution", color="Protocol")
                                fig.update_layout(height=300, showlegend=False)
                                st.plotly_chart(fig, use_container_width=True)

                            # Source/Dest IPs
                            if data.get("top_sources"):
                                st.write("**Top Source IPs:**")
                                st.write(", ".join(data["top_sources"][:10]))
                            if data.get("top_destinations"):
                                st.write("**Top Destination IPs:**")
                                st.write(", ".join(data["top_destinations"][:10]))
                        elif data.get("format") == "pcapng":
                            st.info("PCAPNG format detected. Install tshark for deeper analysis.")
                        elif data.get("type") == "pcap_am_metadata":
                            st.info("PCAP-AM metadata file — proprietary IPC format.")
                            if data.get("content_preview"):
                                st.code(data["content_preview"][:2000], language="text")
                        else:
                            st.info(f"PCAP file registered: {file}")
                            if data.get("error"):
                                st.warning(data["error"])
            else:
                st.info("No PCAP/network capture files detected. Upload .pcap or .pcapng files to analyze network traffic.")
        else:
            st.info("Run analysis to view PCAP diagnostics.")

    # ===== TAB 9: Audio Analysis =====
    with tab9:
        st.subheader("🔊 Audio / CDR Analysis")
        if 'log_data' in st.session_state and isinstance(st.session_state.log_data, dict):
            audio_ctx = st.session_state.log_data.get("audio_context", {})
            if audio_ctx:
                for file, data in audio_ctx.items():
                    with st.expander(f"🎵 {file}", expanded=True):
                        file_type = data.get("type", "unknown")

                        if file_type == "cdr_text":
                            # CDR analysis
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Total Calls", data.get("total_calls", 0))
                            with col2:
                                st.metric("Failed Calls", data.get("failed_calls", 0))
                            with col3:
                                st.metric("Endpoints", data.get("endpoints_count", 0))

                            if data.get("codecs"):
                                st.write(f"**Codecs Detected:** {', '.join(data['codecs'])}")
                            if data.get("total_duration_formatted"):
                                st.write(f"**Total Duration:** {data['total_duration_formatted']}")
                            if data.get("preview"):
                                st.write("**CDR Preview:**")
                                st.code(data["preview"][:2000], language="text")

                        elif file_type in ("wav", "mp3", "ogg", "flac"):
                            # Audio file metadata
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Duration", data.get("duration_formatted", "N/A"))
                            with col2:
                                st.metric("Sample Rate", f"{data.get('sample_rate', 'N/A')} Hz")
                            with col3:
                                st.metric("Codec", data.get("codec", "N/A"))

                            if data.get("channels"):
                                st.write(f"**Channels:** {data['channels']}")
                            if data.get("bitrate"):
                                st.write(f"**Bitrate:** {data['bitrate']}")
                        else:
                            st.info(f"Audio/CDR file: {file}")
            else:
                st.info("No audio/CDR files detected. Upload .wav, .mp3, or CDR text files to analyze call records.")
        else:
            st.info("Run analysis to view audio diagnostics.")

    # ===== TAB 10: Config Analysis =====
    with tab10:
        st.subheader("⚙️ Configuration Analysis")
        if 'log_data' in st.session_state and isinstance(st.session_state.log_data, dict):
            config_ctx = st.session_state.log_data.get("config_context", {})
            if config_ctx:
                for file, data in config_ctx.items():
                    with st.expander(f"📋 {file} ({data.get('format', 'config')})", expanded=True):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Params", data.get("total_params", 0))
                        with col2:
                            st.metric("Critical Params", len(data.get("critical_params", {})))
                        with col3:
                            st.metric("Issues", len(data.get("misconfigurations", [])))

                        # Critical parameters
                        critical = data.get("critical_params", {})
                        if critical:
                            st.write("**Critical Configuration Parameters:**")
                            for desc, info in critical.items():
                                st.write(f"  - **{desc}:** `{info.get('key')}` = `{info.get('value')}`")

                        # Misconfigurations
                        misconfigs = data.get("misconfigurations", [])
                        if misconfigs:
                            st.write("**⚠️ Detected Issues:**")
                            for mc in misconfigs:
                                if mc.get("severity") == "WARN":
                                    st.warning(mc.get("message", ""))
                                else:
                                    st.info(mc.get("message", ""))

                        # Show some params
                        all_params = data.get("all_params", {})
                        if all_params:
                            st.write("**Configuration Preview (first 30 params):**")
                            param_df = pd.DataFrame(
                                [{"Key": k, "Value": str(v)[:100]} for k, v in list(all_params.items())[:30]]
                            )
                            st.dataframe(param_df, use_container_width=True, hide_index=True)
            else:
                st.info("No configuration files detected. Upload .properties, .conf, .yaml, or .xml files.")
        else:
            st.info("Run analysis to view configuration analysis.")

    # ===== TAB 11: Agent Execution Timeline =====
    with tab11:
        st.subheader("⚡ Agent Execution Timeline")
        if 'results' in st.session_state and st.session_state.results.get("agent_summaries"):
            results = st.session_state.results
            summaries = results.get("agent_summaries", {})
            timings = results.get("agent_timings", {})

            # Overall severity badge
            severity = results.get("overall_severity", "INFO")
            severity_colors = {"INFO": "🟢", "WARN": "🟡", "ERROR": "🔴", "CRITICAL": "🔴"}
            st.markdown(f"### Overall Severity: {severity_colors.get(severity, '⚪')} **{severity}**")
            st.write(f"**Total Findings:** {results.get('total_agent_findings', 0)}")

            st.markdown("---")

            # Agent execution table
            agent_data = []
            for agent_type, summary in summaries.items():
                duration = timings.get(agent_type, 0)
                agent_data.append({
                    "Agent": agent_type.replace("_", " ").title(),
                    "Duration (ms)": f"{duration:.0f}",
                    "Summary": summary[:150],
                })

            if agent_data:
                st.dataframe(
                    pd.DataFrame(agent_data),
                    use_container_width=True,
                    hide_index=True
                )

            # Timing chart
            if timings:
                timing_df = pd.DataFrame([
                    {"Agent": k.replace("_", " ").title(), "Duration (ms)": v}
                    for k, v in timings.items()
                ])
                fig = px.bar(timing_df, x="Agent", y="Duration (ms)",
                            title="Agent Execution Duration",
                            color="Agent")
                fig.update_layout(height=350, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            # Individual agent summaries
            st.markdown("### Agent Details")
            for agent_type, summary in summaries.items():
                with st.expander(f"🤖 {agent_type.replace('_', ' ').title()} Agent", expanded=False):
                    st.write(summary)
                    duration = timings.get(agent_type, 0)
                    st.caption(f"Execution time: {duration:.0f}ms")
        else:
            st.info("Run analysis with the distributed agent pipeline to see the execution timeline. "
                    "The agent pipeline runs automatically when you analyze logs.")

else:
    # Landing page
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div class="metric-card">
            <h3> Fast Analysis</h3>
            <p>Get RCA in seconds using semantic search</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="metric-card">
            <h3> AI-Powered</h3>
            <p>RAG architecture with local embeddings</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="metric-card">
            <h3> Enterprise Ready</h3>
            <p>Multi-zone, multi-client support</p>
        </div>
        """, unsafe_allow_html=True)



   
    # Quick start guide
    st.markdown("---")
    st.markdown("###  Quick Start Guide")
    
    guide_col1, guide_col2 = st.columns(2)
    
    with guide_col1:
        st.markdown("""
        1. **Select parameters** from sidebar
        2. **Enter your query** about the issue
        3. **Click 'Analyze Logs'** button
        4. **Review RCA** in the summary tab
        5. **Check evidence** and KB fixes
        
        **Supported Query Types:**
        - Why did [component] fail?
        - Find all [error type] errors
        - What caused the timeout?
        - Analyze configuration issues
        """)
    
    with guide_col2:
        st.markdown("""
        ** Expected Log Structure:**
        ```
        E:/LogSpace/
        ├── ZONE/
        │   ├── CLIENT/
        │   │   ├── APP/
        │   │   │   ├── VERSION/
        │   │   │   │   ├── SUB_VERSION/
        │   │   │   │   │   ├── *.error
        │   │   │   │   │   └── *.info
        ```
        
        **🔧 Features:**
        - Semantic log search
        - Automatic RCA generation
        - Knowledge base integration
        - Visual analytics
        - Real-time indexing
        """)
    
    # System stats
    st.markdown("---")
    st.markdown("###  System Statistics")
    
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    with stat_col1:
        if hasattr(rag_engine, "vector_store"):
            st.metric("Vector Store Size", f"{rag_engine.vector_store.size()} chunks")
        else:
            st.metric("Vector Store Size", "FAISS / Embeddings Active")
    with stat_col2:
        st.metric("KB Entries", f"{len(kb.entries)} fixes")
    with stat_col3:
        st.metric("Embedding Model", config['embedding']['model_name'])


# Footer
st.markdown("---")
st.markdown("*LogSentry AI v2.0 | RAG-powered Troubleshooting Assistant | Phase 2 Implementation*")
