# src/services/log_reader.py

import os
from typing import Dict, Optional, List
import yaml
from src.utils.parser import LogParser

LOG_EXTENSIONS = ('.log', '.error', '.info', '.debug', '.txt', '.out', '.trace')

class LogReader:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        self.root_dir = config['paths']['log_root']
        self.parser = LogParser()

    def get_log_path(self, zone: str, client: str, app: str, version: str, sub_version: str) -> str:
        return os.path.join(self.root_dir, zone, client, app, version, sub_version)

    def read_logs(self, zone: str, client: str, app: str, version: str, sub_version: str) -> tuple:
        base_path = self.get_log_path(zone, client, app, version, sub_version)

        if not os.path.exists(base_path):
            return None, f"Log path does not exist: {base_path}"

        log_files = []
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file.lower().endswith(LOG_EXTENSIONS):
                    log_files.append(os.path.join(root, file))

        if not log_files:
            return None, f"No log files found in {base_path}"

        all_logs = []
        structured_logs = []
        MAX_PREVIEW_LINES = 2000  # avoid OOM for large files

        for log_file in log_files:
            try:
                preview_lines = []
                line_count = 0
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line_count += 1
                        if line_count <= MAX_PREVIEW_LINES:
                            preview_lines.append(line)
                        if line.strip():
                            parsed = self.parser.parse_line(
                                line, zone, client, app, f"{version}/{sub_version}"
                            )
                            if parsed:
                                structured_logs.append(parsed)

                preview = "".join(preview_lines)
                if line_count > MAX_PREVIEW_LINES:
                    preview += f"\n... [Showing first {MAX_PREVIEW_LINES} of {line_count} lines] ..."
                all_logs.append(f"=== File: {os.path.basename(log_file)} ===\n{preview}")
            except Exception as e:
                all_logs.append(f"Error reading {log_file}: {str(e)}")

        return {
            "raw": "\n".join(all_logs),
            "structured": structured_logs,
            "file_count": len(log_files),
            "zone": zone,
            "client": client,
            "app": app,
            "version": f"{version}/{sub_version}"
        }, None

    def get_available_logs(self) -> Dict:
        structure = {}
        if not os.path.exists(self.root_dir):
            return structure
        for zone in os.listdir(self.root_dir):
            zone_path = os.path.join(self.root_dir, zone)
            if os.path.isdir(zone_path):
                structure[zone] = {}
                for client in os.listdir(zone_path):
                    client_path = os.path.join(zone_path, client)
                    if os.path.isdir(client_path):
                        structure[zone][client] = {}
                        for app in os.listdir(client_path):
                            app_path = os.path.join(client_path, app)
                            if os.path.isdir(app_path):
                                structure[zone][client][app] = []
                                for version in os.listdir(app_path):
                                    version_path = os.path.join(app_path, version)
                                    if os.path.isdir(version_path):
                                        structure[zone][client][app].append(version)
        return structure
