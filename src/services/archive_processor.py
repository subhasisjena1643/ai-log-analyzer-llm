import os
import re
import shutil
import zipfile
import tarfile
import pypdf
from typing import Dict, List, Tuple, Any, Optional

class ArchiveProcessor:
    def __init__(self, temp_dir="./temp_archive_extracted"):
        # Make sure the temp directory is absolute and inside the workspace
        self.temp_dir = os.path.abspath(temp_dir)
        self.parser = None # Will be set or imported as needed
        
    def clean_temp_dir(self):
        """Clean up the temporary extraction directory"""
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"Error cleaning temp directory: {e}")

    def extract_recursively(self, file_path_or_bytes, is_bytes=False, filename=None) -> str:
        """
        Extracts zip/tar file recursively to temp_dir.
        Returns the root path of the extracted files.
        """
        self.clean_temp_dir()
        os.makedirs(self.temp_dir, exist_ok=True)
        
        target_path = os.path.join(self.temp_dir, filename or "uploaded_archive.zip")
        
        if is_bytes:
            with open(target_path, "wb") as f:
                f.write(file_path_or_bytes)
        else:
            shutil.copy(file_path_or_bytes, target_path)
            
        self._extract_file(target_path, self.temp_dir)
        return self.temp_dir

    def _extract_file(self, filepath: str, extract_to: str):
        """Helper to extract a single zip/tar/gz file and recursively check for inner archives"""
        import gzip

        if zipfile.is_zipfile(filepath):
            try:
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
                os.remove(filepath)
            except Exception as e:
                print(f"Failed to extract zip {filepath}: {e}")
                return

        elif filepath.endswith(('.tar', '.tgz', '.tar.gz', '.gz')):
            # First try as a tarball (covers .tar, .tgz, .tar.gz, and gzip-wrapped tars)
            is_tar = False
            try:
                is_tar = tarfile.is_tarfile(filepath)
            except Exception:
                is_tar = False

            if is_tar:
                try:
                    with tarfile.open(filepath, 'r:*') as tar_ref:
                        tar_ref.extractall(extract_to)
                    os.remove(filepath)
                except Exception as e:
                    print(f"Failed to extract tar {filepath}: {e}")
                    return

            elif filepath.endswith('.gz'):
                # Raw gzip file (e.g. app.log.gz) — decompress using gzip module
                base_name = os.path.basename(filepath)
                # Strip .gz to get the inner filename (e.g. "app.log.gz" → "app.log")
                inner_name = base_name[:-3] if base_name.endswith('.gz') else base_name + ".decompressed"
                out_path = os.path.join(extract_to, inner_name)
                try:
                    with gzip.open(filepath, 'rb') as gz_in, open(out_path, 'wb') as f_out:
                        while True:
                            chunk = gz_in.read(10 * 1024 * 1024)  # 10 MB chunks
                            if not chunk:
                                break
                            f_out.write(chunk)
                    os.remove(filepath)
                    print(f"[INFO] Decompressed raw gzip: {base_name} → {inner_name}")
                except Exception as e:
                    print(f"Failed to decompress raw gzip {filepath}: {e}")
                    return
            else:
                # .tar or .tgz that is_tarfile said wasn't valid — skip
                return

        else:
            return

        # Check for nested archives recursively
        for root, dirs, files in os.walk(extract_to):
            for file in files:
                full_path = os.path.join(root, file)
                if file.endswith(('.zip', '.tar', '.tgz', '.tar.gz', '.gz')):
                    # Extract nested archive in its current folder
                    nested_extract_to = os.path.join(root, f"{file}_extracted")
                    os.makedirs(nested_extract_to, exist_ok=True)
                    self._extract_file(full_path, nested_extract_to)

    def process_extracted_files(self, log_parser, zone: str, client: str, app: str, version: str) -> Dict[str, Any]:
        """Wrapper to process the temporary extracted archive folder"""
        return self.process_directory(self.temp_dir, log_parser, zone, client, app, version)

    def process_directory(self, dir_path: str, log_parser, zone: str, client: str, app: str, version: str, parent_rel_path: str = "", max_structured_entries: Optional[int] = None) -> Dict[str, Any]:
        """
        Walks the specified directory and parses each file.
        Dynamically analyzes content to classify files, extracts archive logs recursively,
        and returns detailed file metadata.

        max_structured_entries: optional cap on retained parsed log entries. Default
        None preserves the original unbounded behavior; when set, parsing stops
        accumulating structured logs once the cap is reached (files are still counted).
        This bounds memory for very large (multi-GB) bundles.
        """
        results = {
            "structured_logs": [],
            "raw_logs_text": [],
            "sql_context": {},
            "pdf_context": {},
            "memory_context": {},
            "inference_context": {},
            "file_counts": {
                "logs": 0,
                "sql": 0,
                "pdf": 0,
                "memory": 0,
                "inference": 0
            },
            "all_files_metadata": []
        }
        
        if not os.path.exists(dir_path):
            return results

        # Create temporary extraction space if needed for folder scans
        os.makedirs(self.temp_dir, exist_ok=True)

        for root, dirs, files in os.walk(dir_path):
            # Skip temp_dir if walking a folder that contains the temp_dir, but we are not inside temp_dir ourselves
            if not os.path.abspath(dir_path).startswith(self.temp_dir) and os.path.abspath(root).startswith(self.temp_dir):
                continue

            for file in files:
                filepath = os.path.join(root, file)
                filename_lower = file.lower()
                rel_path = os.path.normpath(os.path.join(parent_rel_path, os.path.relpath(filepath, dir_path))).replace("\\", "/")

                # Get file size safely
                try:
                    size_bytes = os.path.getsize(filepath)
                except Exception:
                    size_bytes = 0
                size_str = self._format_size(size_bytes)

                # 1. Process Archive Files (Dynamic recursive extraction for folder scans)
                if file.endswith(('.zip', '.tar', '.tgz', '.tar.gz', '.gz')):
                    results["all_files_metadata"].append({
                        "filename": file,
                        "relative_path": rel_path,
                        "file_type": "Archive File",
                        "size": size_str,
                        "highlights": "Extracting archive content..."
                    })
                    
                    # Create a unique extraction folder inside self.temp_dir to avoid collision
                    nested_folder_name = f"{file}_extracted"
                    nested_extract_to = os.path.join(self.temp_dir, nested_folder_name)
                    os.makedirs(nested_extract_to, exist_ok=True)
                    
                    try:
                        # Copy the archive locally to avoid deleting original files
                        local_archive_copy = os.path.join(nested_extract_to, file)
                        shutil.copy2(filepath, local_archive_copy)
                        
                        # Extract it
                        self._extract_file(local_archive_copy, nested_extract_to)
                        
                        # Process files inside it recursively (propagate the memory cap)
                        remaining_cap = None
                        if max_structured_entries is not None:
                            remaining_cap = max(0, max_structured_entries - len(results["structured_logs"]))
                        sub_results = self.process_directory(
                            nested_extract_to, log_parser, zone, client, app, version,
                            parent_rel_path=os.path.join(parent_rel_path, file),
                            max_structured_entries=remaining_cap,
                        )
                        
                        # Merge sub-results
                        results["structured_logs"].extend(sub_results["structured_logs"])
                        results["raw_logs_text"].extend(sub_results["raw_logs_text"])
                        results["sql_context"].update(sub_results["sql_context"])
                        results["pdf_context"].update(sub_results["pdf_context"])
                        results["memory_context"].update(sub_results["memory_context"])
                        results["inference_context"].update(sub_results["inference_context"])
                        
                        # Add counts
                        for key in results["file_counts"]:
                            results["file_counts"][key] += sub_results["file_counts"].get(key, 0)
                            
                        # Add sub-metadata
                        results["all_files_metadata"].extend(sub_results["all_files_metadata"])
                        
                    except Exception as e:
                        print(f"Failed to recursively process archive {file}: {e}")
                    finally:
                        # Cleanup temp subdirectory
                        if os.path.exists(nested_extract_to):
                            try:
                                shutil.rmtree(nested_extract_to)
                            except Exception:
                                pass
                    continue

                # 2. Dynamic Content Analysis & Classification
                file_type, highlights, parsed_data = self._detect_file_type_and_analyze(
                    filepath, file, rel_path, log_parser, zone, client, app, version
                )

                # Store metadata
                results["all_files_metadata"].append({
                    "filename": file,
                    "relative_path": rel_path,
                    "file_type": file_type,
                    "size": size_str,
                    "highlights": highlights
                })

                # Merge parsed contexts
                if file_type == "PDF Report" and "pdf" in parsed_data:
                    results["pdf_context"][file] = parsed_data["pdf"]
                    results["file_counts"]["pdf"] += 1
                    
                elif file_type == "SQL Schema/Dump" and "sql" in parsed_data:
                    results["sql_context"][file] = parsed_data["sql"]
                    results["file_counts"]["sql"] += 1
                    
                elif file_type in ["JVM Thread Dump", "JVM Heap Histogram", "JVM Memory Dump", "GC Log"] and "memory" in parsed_data:
                    results["memory_context"][file] = parsed_data["memory"]
                    results["file_counts"]["memory"] += 1
                    
                elif file_type == "SRE Notes" and "inference" in parsed_data:
                    results["inference_context"][file] = parsed_data["inference"]
                    results["file_counts"]["inference"] += 1
                    
                elif file_type == "App Log" and "logs" in parsed_data:
                    parsed_logs = parsed_data["logs"]
                    if max_structured_entries is not None:
                        remaining = max_structured_entries - len(results["structured_logs"])
                        if remaining > 0:
                            results["structured_logs"].extend(parsed_logs[:remaining])
                        # else: cap reached — keep counting the file but stop retaining entries
                    else:
                        results["structured_logs"].extend(parsed_logs)
                    results["file_counts"]["logs"] += 1
                    
                    # Store Raw log text for preview
                    try:
                        preview_lines = []
                        max_preview = 1000
                        line_count = 0
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            for line in f:
                                line_count += 1
                                if line_count <= max_preview:
                                    preview_lines.append(line)
                        preview_text = "".join(preview_lines)
                        if line_count > max_preview:
                            preview_text += f"\n... [Truncated raw logs, total lines parsed: {line_count}] ..."
                        results["raw_logs_text"].append(f"=== File: {file} ===\n{preview_text}")
                    except Exception as e:
                        results["raw_logs_text"].append(f"Error reading log file {file}: {str(e)}")

        return results

    def _detect_file_type_and_analyze(
        self, filepath: str, filename: str, relative_path: str, log_parser, zone: str, client: str, app: str, version: str
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Classify and parse file contents dynamically without hardcoded filename filters"""
        filename_lower = filename.lower()

        # 1. Check extensions first
        if filename_lower.endswith('.pdf'):
            pdf_data = self._parse_pdf_file(filepath, filename)
            if "error" in pdf_data:
                return "PDF Report", f"Failed to parse PDF: {pdf_data['error']}", {}
            failures = len(pdf_data.get("failures", []))
            warnings = len(pdf_data.get("warnings", []))
            highlights = f"Pages: {pdf_data.get('total_pages', 0)} | Failures: {failures} | Warnings: {warnings}"
            return "PDF Report", highlights, {"pdf": pdf_data}

        if filename_lower.endswith('.sql'):
            sql_data = self._parse_sql_file(filepath, filename)
            if "error" in sql_data:
                return "SQL Schema/Dump", f"Failed to parse SQL: {sql_data['error']}", {}
            tables = len(sql_data.get("tables_found", []))
            errors = len(sql_data.get("errors_found", []))
            highlights = f"Queries: {sql_data.get('queries_count', 0)} | Tables: {tables} | Errors: {errors}"
            return "SQL Schema/Dump", highlights, {"sql": sql_data}

        # 2. Check if text file
        if not self._is_text_file(filepath):
            return "Binary/Unknown", "Binary file skipped", {}

        # 3. Read content sample
        sample_content = ""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                sample_content = f.read(4000)
        except Exception as e:
            return "Error", f"Read error: {str(e)}", {}

        sample_lower = sample_content.lower()

        # 4. SRE / Incident Inference Notes Heuristic (Check first to avoid overlaps)
        if any(k in sample_lower for k in ["pbi", "problem investigation", "root cause analysis notes", "incident", "remediation"]):
            inf_data = self._parse_inference_file(filepath, filename)
            content_len = len(inf_data.get("content", ""))
            highlights = f"Incident notes ({content_len} chars)"
            return "SRE Notes", highlights, {"inference": inf_data}

        # 5. JVM Thread Dump Heuristic
        if "java.lang.thread.state" in sample_lower or "full thread dump" in sample_lower or "prio=" in sample_lower:
            mem_data = self._parse_memory_diagnostics(filepath, filename)
            thread_states = mem_data.get("thread_states")
            if thread_states:
                states_str = ", ".join([f"{k}: {v}" for k, v in thread_states.items() if v > 0])
                highlights = f"JVM Threads: {states_str}" if states_str else "JVM Threads (All states 0)"
            else:
                highlights = "JVM Thread Dump parsed"
            return "JVM Thread Dump", highlights, {"memory": mem_data}

        # 6. JVM Object Histogram Heuristic
        if "heap object histogram" in sample_lower or ("instances" in sample_lower and "bytes" in sample_lower and "class name" in sample_lower):
            mem_data = self._parse_memory_diagnostics(filepath, filename)
            highlights = "JVM Heap Object Summary Histogram"
            return "JVM Heap Histogram", highlights, {"memory": mem_data}

        # 7. JVM Memory Usage Heuristic
        if any(k in sample_lower for k in ["max heap:", "heap committed:", "heap used:", "memory max size", "xmx"]):
            mem_data = self._parse_memory_diagnostics(filepath, filename)
            heap_max = mem_data.get("heap_max_mb")
            heap_used = mem_data.get("heap_used_mb")
            highlights = f"JVM Heap Used: {heap_used or 'N/A'} MB / Max: {heap_max or 'N/A'} MB"
            return "JVM Memory Dump", highlights, {"memory": mem_data}

        # 8. GC Log Heuristic
        if "gc pause" in sample_lower or "full gc" in sample_lower or "evacuation pause" in sample_lower:
            mem_data = self._parse_memory_diagnostics(filepath, filename)
            gc_pauses = mem_data.get("gc_pauses", [])
            highlights = f"GC Log: {len(gc_pauses)} pause events detected"
            return "GC Log", highlights, {"memory": mem_data}

        # 9. standard logs
        if any(level in sample_content for level in ["INFO", "WARN", "ERROR", "DEBUG", "TRACE"]):
            parsed_logs = []
            total_lines = 0
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    if line.strip():
                        parsed = log_parser.parse_line(line, zone, client, app, version)
                        if parsed:
                            parsed_logs.append(parsed)
            highlights = f"App Log: {total_lines} lines parsed | {len(parsed_logs)} error/warning flags"
            return "App Log", highlights, {"logs": parsed_logs, "total_lines": total_lines}

        # Default fallback: Generic App Log
        parsed_logs = []
        total_lines = 0
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                total_lines += 1
                if line.strip():
                    parsed = log_parser.parse_line(line, zone, client, app, version)
                    if parsed:
                        parsed_logs.append(parsed)
        highlights = f"Text File: {total_lines} lines parsed"
        return "App Log", highlights, {"logs": parsed_logs, "total_lines": total_lines}

    def _is_text_file(self, filepath: str) -> bool:
        """Determines if a file is plain text by reading the first block"""
        try:
            with open(filepath, 'tr', encoding='utf-8', errors='ignore') as f:
                f.read(1024)
                return True
        except Exception:
            return False
            
    def _format_size(self, bytes_val: int) -> str:
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


    def _parse_sql_file(self, filepath: str, filename: str) -> Dict[str, Any]:
        """Parses a SQL dump/log memory-efficiently line-by-line"""
        try:
            tables = []
            errors = []
            queries_count = 0
            preview_lines = []
            max_preview_lines = 100
            total_lines = 0
            
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    if total_lines <= max_preview_lines:
                        preview_lines.append(line)
                        
                    line_strip = line.strip()
                    # Find tables created
                    table_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_\`\"\.]+)', line, re.IGNORECASE)
                    if table_match:
                        tables.append(table_match.group(1).replace('`', '').replace('"', ''))
                    
                    # Check for query errors or database exceptions in logs
                    if any(k in line_strip.lower() for k in ["error", "fail", "rollback", "deadlock", "foreign key", "exception"]):
                        if len(errors) < 20: # limit to first 20 errors
                            errors.append(line_strip[:150])
                    
                    if line_strip.endswith(';'):
                        queries_count += 1
                        
            preview = "".join(preview_lines)
            if total_lines > max_preview_lines:
                preview += f"\n... [Truncated {total_lines - max_preview_lines} lines for memory efficiency] ..."
                
            return {
                "filename": filename,
                "tables_found": list(set(tables)),
                "errors_found": errors,
                "queries_count": queries_count,
                "preview": preview,
                "total_lines": total_lines
            }
        except Exception as e:
            return {"filename": filename, "error": f"Error parsing SQL file: {str(e)}"}

    def _parse_pdf_file(self, filepath: str, filename: str) -> Dict[str, Any]:
        """Parses a PDF report and searches for critical keywords or failed checkmarks"""
        try:
            text_pages = []
            with open(filepath, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages:
                    text_pages.append(page.extract_text() or "")
            
            full_text = "\n".join(text_pages)
            
            # Look for failure keywords
            failures = []
            warnings = []
            lines = full_text.splitlines()
            for line in lines:
                line_lower = line.lower()
                if any(kw in line_lower for kw in ["fail", "failed", "critical", "error", "unreachable", "offline"]):
                    failures.append(line.strip())
                elif any(kw in line_lower for kw in ["warn", "warning", "degraded", "restarting"]):
                    warnings.append(line.strip())
                    
            return {
                "filename": filename,
                "total_pages": len(reader.pages),
                "failures": list(set(failures))[:15], # limit list
                "warnings": list(set(warnings))[:15],
                "extracted_text": full_text[:4000] # preview first 4000 chars for context
            }
        except Exception as e:
            return {"filename": filename, "error": f"Error parsing PDF file: {str(e)}"}

    def _parse_memory_diagnostics(self, filepath: str, filename: str) -> Dict[str, Any]:
        """
        Parses Heap memory usage diagnostics files memory-efficiently line-by-line.
        """
        try:
            heap_committed_mb = None
            heap_used_mb = None
            heap_max_mb = None
            
            thread_runnable = 0
            thread_waiting = 0
            thread_timed_waiting = 0
            thread_blocked = 0
            
            gc_pauses = []
            preview_lines = []
            max_preview_lines = 100
            total_lines = 0
            
            mem_keywords = ["max", "committed", "used", "heap", "memory", "usage", "xmx"]
            
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    if total_lines <= max_preview_lines:
                        preview_lines.append(line)
                        
                    line_lower = line.lower()
                    
                    if any(k in line_lower for k in mem_keywords):
                        if "non-heap" in line_lower or "nonheap" in line_lower:
                            continue
                        if "max" in line_lower and ("heap" in line_lower or "memory" in line_lower or "xmx" in line_lower or "size" in line_lower):
                            val = self._extract_mb_value(line)
                            if val: heap_max_mb = val
                        
                        if "committed" in line_lower and ("heap" in line_lower or "memory" in line_lower):
                            val = self._extract_mb_value(line)
                            if val: heap_committed_mb = val
                            
                        if "used" in line_lower and ("heap" in line_lower or "memory" in line_lower or "usage" in line_lower or "size" in line_lower):
                            val = self._extract_mb_value(line)
                            if val: heap_used_mb = val

                    if "java.lang.thread.state" in line_lower:
                        if "runnable" in line_lower:
                            thread_runnable += 1
                        elif "timed_waiting" in line_lower:
                            thread_timed_waiting += 1
                        elif "waiting" in line_lower:
                            thread_waiting += 1
                        elif "blocked" in line_lower:
                            thread_blocked += 1
                    else:
                        # Summary check on each line, e.g. "Runnable: 45" or "Blocked: 4"
                        for state_name in ["RUNNABLE", "WAITING", "TIMED_WAITING", "BLOCKED"]:
                            match = re.search(rf'\b{state_name.lower()}\s*[:=]\s*(\d+)', line_lower)
                            if match:
                                val = int(match.group(1))
                                if state_name == "RUNNABLE": thread_runnable += val
                                elif state_name == "WAITING": thread_waiting += val
                                elif state_name == "TIMED_WAITING": thread_timed_waiting += val
                                elif state_name == "BLOCKED": thread_blocked += val

                    if "gc" in line_lower and any(k in line_lower for k in ["pause", "stop-the-world", "duration", "ms", "sec"]):
                        if len(gc_pauses) < 10:
                            gc_pauses.append(line.strip()[:120])

            if not heap_used_mb:
                preview_content = "".join(preview_lines)
                match = re.search(r'(?:heap|memory|usage)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mb|m|gb|g|kb|k)', preview_content, re.IGNORECASE)
                if match:
                    heap_used_mb = self._convert_to_mb(float(match.group(1)), match.group(0))

            thread_states = {
                "RUNNABLE": thread_runnable,
                "WAITING": thread_waiting,
                "TIMED_WAITING": thread_timed_waiting,
                "BLOCKED": thread_blocked
            }
            
            for state in thread_states:
                if thread_states[state] == 0:
                    preview_content = "".join(preview_lines)
                    match = re.search(rf'{state.lower()}\s*:\s*(\d+)', preview_content, re.IGNORECASE)
                    if match:
                        thread_states[state] = int(match.group(1))

            return {
                "filename": filename,
                "heap_max_mb": heap_max_mb,
                "heap_committed_mb": heap_committed_mb or heap_max_mb,
                "heap_used_mb": heap_used_mb,
                "thread_states": thread_states if any(v > 0 for v in thread_states.values()) else None,
                "gc_pauses": gc_pauses,
                "raw_preview": "".join(preview_lines) + (f"\n... [Truncated {total_lines - max_preview_lines} lines for memory efficiency] ..." if total_lines > max_preview_lines else "")
            }
        except Exception as e:
            return {"filename": filename, "error": f"Error parsing Memory file: {str(e)}"}

    def _extract_mb_value(self, text: str) -> Optional[float]:
        """Extracts a numeric value from text and converts to Megabytes (MB)"""
        match = re.search(r'(\d+(?:\.\d+)?)\s*(mb|m|gb|g|kb|k|b)', text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            unit = match.group(2).lower()
            return self._convert_to_mb(val, unit)
        
        # Plain number without units (assume bytes or kb)
        match_num = re.search(r'[:=]\s*(\d+(?:\.\d+)?)', text)
        if match_num:
            return float(match_num.group(1)) / (1024 * 1024) # Assume bytes as default
        return None

    def _convert_to_mb(self, val: float, unit: str) -> float:
        unit = unit.lower()
        if 'gb' in unit or 'g' == unit:
            return val * 1024
        elif 'kb' in unit or 'k' == unit:
            return val / 1024
        elif 'mb' in unit or 'm' == unit:
            return val
        elif 'b' == unit:
            return val / (1024 * 1024)
        return val

    def _parse_inference_file(self, filepath: str, filename: str) -> Dict[str, Any]:
        """Parses a prior inference text file or incidents document"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return {
                "filename": filename,
                "content": content
            }
        except Exception as e:
            return {"filename": filename, "error": f"Error reading inference notes: {str(e)}"}
