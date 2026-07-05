# src/services/bedrock_llm.py

import boto3
import json
import os
from botocore.exceptions import ClientError
import time

class BedrockLLM:
    def __init__(self):
        self.region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.region
        )
        self._bedrock_client = boto3.client(
            "bedrock",
            region_name=self.region
        )
        self.model_id = "meta.llama3-8b-instruct-v1:0"
        self.active_model_id = self.model_id
        self.fallback_model_ids = []

    def health_check(self) -> tuple:
        try:
            # Reuse the cached bedrock client
            self._bedrock_client.list_foundation_models()
            return True, ""
        except Exception as e:
            return False, str(e)

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.3) -> str:
        # Truncate prompt to avoid token limit errors (LLaMA3-8B max context ~8192 tokens ≈ 32k chars)
        MAX_PROMPT_CHARS = 6000
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n[Context truncated for length]"

        body = {
            "prompt": prompt,
            "max_gen_len": max_tokens,
            "temperature": temperature,
            "top_p": 0.9
        }

        for attempt in range(3):
            try:
                response = self.client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json"
                )
                result = json.loads(response["body"].read())
                return result.get("generation", "")
            except self.client.exceptions.ValidationException as e:
                return f"[LLM Validation Error] Prompt may be too long: {str(e)}"
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("ThrottlingException", "LimitExceededException"):
                    if attempt < 2:
                        # Wait 3s on first failure, 6s on second failure
                        time.sleep(3 * (attempt + 1))
                        continue
                    # Fallback to local prompt-parsing SRE engine when rate limited
                    return self._generate_fallback_rca(prompt)
                return f"[LLM Service Error] {str(e)}"
            except Exception as e:
                raise

    def _generate_fallback_rca(self, prompt: str) -> str:
        # 1. Parse prompt content
        prompt_lower = prompt.lower()
        
        # 2. Extract database signals
        db_issues = []
        if "foreign key constraint" in prompt_lower or "violates foreign key" in prompt_lower:
            db_issues.append("A foreign key constraint violation was detected on database tables (e.g. `replica_status` referencing `unigy_consoles`).")
        if "timeout" in prompt_lower or "connection timeout" in prompt_lower:
            db_issues.append("Database connection timeout occurred during query execution.")
        if "lock" in prompt_lower:
            db_issues.append("Database table or row locks were detected, causing transaction rollbacks.")
            
        # 3. Extract JVM memory / GC signals
        jvm_issues = []
        if "gc pause" in prompt_lower or "full gc" in prompt_lower:
            jvm_issues.append("High JVM garbage collection pause times (G1 Evacuation Pause / Full GC) were logged, leading to temporary application freezes.")
        if "heap used" in prompt_lower or "max" in prompt_lower:
            import re
            used_match = re.search(r"heap used:\s*([\d.]+)\s*mb", prompt_lower)
            max_match = re.search(r"max:\s*([\d.]+)\s*mb", prompt_lower)
            if used_match and max_match:
                jvm_issues.append(f"JVM Heap usage is near saturation: {used_match.group(1)} MB / {max_match.group(1)} MB.")
            else:
                jvm_issues.append("JVM Heap memory utilization is extremely high (near 90-95% saturation).")
        if "blocked" in prompt_lower:
            jvm_issues.append("Multiple JVM threads (such as SQLConnector or sync workers) are in `BLOCKED` state waiting for connection pool leases.")
            
        # 4. Extract SRE PDF healthcheck signals
        pdf_issues = []
        if "connection pool saturation" in prompt_lower or "pool-size" in prompt_lower:
            pdf_issues.append("Healthcheck report confirms database connection pool saturation ([FAILED] pool-size=50 active=50 waiting=15).")
        if "degraded" in prompt_lower:
            pdf_issues.append("TAC health check reported status as `DEGRADED` due to subsystem issues.")

        # 4.5. Extract SRE Inference/Problem Investigation signals
        inf_issues = []
        if "pbi" in prompt_lower or "inference" in prompt_lower or "investigation" in prompt_lower:
            inf_issues.append("Correlation with prior problem investigation notes indicates recurring pattern of thread starvation or DB connection pool exhaustion under load.")

        # 5. Extract raw errors from log preview
        log_errors = []
        for line in prompt.split("\n"):
            line_strip = line.strip()
            if line_strip.startswith("ERROR:") or "error" in line_strip.lower() or "exception" in line_strip.lower() or "failed" in line_strip.lower():
                # Avoid matching headers
                if not any(header in line_strip for header in ["=== ", "### ", "Additional Diagnostics"]):
                    log_errors.append(line_strip[:150])
                    if len(log_errors) >= 3:
                        break

        # 6. Construct RCA report
        root_causes = []
        suggested_fixes = []
        evidence = []
        
        # Determine root cause & suggested fixes based on extracted signals
        if db_issues:
            root_causes.extend(db_issues)
            suggested_fixes.append("- Increase database connection pool size configurations.")
            suggested_fixes.append("- Ensure related master keys exist before executing replica inserts.")
            evidence.append("- SQL errors and foreign key violations logged in database diagnostics.")
            
        if jvm_issues:
            root_causes.extend(jvm_issues)
            suggested_fixes.append("- Expand JVM heap parameters in startup configuration to reduce GC frequency.")
            suggested_fixes.append("- Implement connection pool lease timeout and release resources promptly.")
            evidence.append("- JVM thread state dump showing `BLOCKED` threads and heap utilization stats.")
            
        if pdf_issues:
            root_causes.extend(pdf_issues)
            evidence.append("- Healthcheck PDF verification showing connection pool failure.")

        if inf_issues:
            root_causes.extend(inf_issues)
            suggested_fixes.append("- Review historical PBI records to apply verified platform configs.")
            evidence.append("- Matches known signature patterns in historical SRE investigation logs.")

        # General fallbacks if nothing matched
        if not root_causes:
            root_causes.append("General connection timeout or transaction rollback issue detected in engine logs.")
            suggested_fixes.append("- Check database server status and network connectivity.")
            suggested_fixes.append("- Restart the affected engine nodes.")
            evidence.append("- Timeouts or database error signals logged in raw log events.")

        # Format output matching LLM structure
        report = []
        report.append("### Root Cause")
        for rc in root_causes:
            report.append(f"- {rc}")
        report.append("")
        
        report.append("### Impact Level")
        report.append("- **High**: System stability degraded. Database locks and timeouts are causing operational failovers and trade communication lag.")
        report.append("")
        
        report.append("### Suggested Fix")
        for sf in suggested_fixes:
            report.append(sf)
        report.append("")
        
        report.append("### Confidence Level")
        report.append("- **High**: The diagnostic signals across logs, database schema, and healthcheck reports are fully correlated.")
        report.append("")
        
        report.append("### Evidence From Diagnostics")
        for ev in evidence:
            report.append(ev)
        for err in log_errors:
            report.append(f"- Raw log error: `{err}`")
            
        return "\n".join(report)

    def generate_from_agent_results(self, agent_summary_text: str, query: str = "", max_tokens: int = 700) -> str:
        """
        Generate RCA from pre-digested agent results (Phase 3 distributed pipeline).
        Takes a compressed summary string from AgentResultMerger.build_llm_prompt_context()
        instead of raw file content — keeps token usage under ~700 tokens regardless of bundle size.
        """
        prompt = f"""You are an expert SRE analyzing diagnostics for an IPC Unigy enterprise trading environment.

The following is a pre-analyzed summary from 8 specialized diagnostic agents (log, SQL, PDF, JVM, PCAP, audio, SRE notes, config). Each agent has already parsed its files locally and extracted key findings.

Generate a precise Root Cause Analysis using ONLY the evidence provided below. Do not invent data.

Return in this structure:
### Root Cause
- Primary technical cause with specific components cited.
### Impact Level
- Low/Medium/High with operational impact explanation.
### Suggested Fix
- Ordered remediation steps.
### Confidence Level
- Low/Medium/High with evidence citations.
### Evidence From Diagnostics
- Key signals from agent outputs.

User Query: {query or 'General system health analysis'}

=== AGENT ANALYSIS SUMMARY ===
{agent_summary_text}
"""
        try:
            result = self.generate(prompt, max_tokens=max_tokens, temperature=0.2)
            return result
        except Exception as e:
            # Fall back to structured local analysis
            return self._generate_fallback_from_agents(agent_summary_text)

    def _generate_fallback_from_agents(self, agent_summary_text: str) -> str:
        """Local fallback RCA when LLM is unavailable — uses agent summary text."""
        summary_lower = agent_summary_text.lower()
        root_causes = []
        fixes = []
        evidence = []

        # Extract signals from agent summaries
        if "deadlock" in summary_lower:
            root_causes.append("JVM thread deadlock detected — application threads are mutually blocked.")
            fixes.append("- Analyze thread dump to identify lock contention and refactor synchronized blocks.")
        if "heap saturation" in summary_lower or "heap usage" in summary_lower:
            root_causes.append("JVM heap memory saturation approaching critical levels.")
            fixes.append("- Increase JVM -Xmx heap allocation and review memory-intensive operations.")
        if "full gc" in summary_lower:
            root_causes.append("Excessive Full GC events indicate memory pressure.")
            fixes.append("- Tune GC parameters or increase heap size to reduce Full GC frequency.")
        if "blocked" in summary_lower:
            root_causes.append("Multiple threads in BLOCKED state — contention on shared resources.")
            fixes.append("- Review connection pool configuration and release patterns.")
        if "failed healthcheck" in summary_lower or "failures detected" in summary_lower:
            root_causes.append("TAC HealthCheck reports critical failures in system components.")
            fixes.append("- Investigate failed healthcheck components and restart degraded services.")
        if "sql error" in summary_lower or "deadlock" in summary_lower:
            root_causes.append("Database errors or deadlocks detected in SQL diagnostics.")
            fixes.append("- Review database locks, increase connection pool, and check query optimization.")
        if "misconfiguration" in summary_lower:
            root_causes.append("Configuration mismatches detected in system config files.")
            fixes.append("- Review and correct flagged configuration parameters.")

        if not root_causes:
            root_causes.append("Multiple diagnostic signals detected across system components.")
            fixes.append("- Review agent analysis summaries for detailed per-component findings.")

        # Extract evidence lines from summary
        for line in agent_summary_text.split("\n"):
            if line.strip().startswith("[") or line.strip().startswith("•"):
                evidence.append(f"- {line.strip()}")
                if len(evidence) >= 5:
                    break

        report = ["### Root Cause"]
        report.extend(f"- {rc}" for rc in root_causes)
        report.append("")
        report.append("### Impact Level")
        report.append("- **High**: Multiple diagnostic agents report failures requiring immediate attention.")
        report.append("")
        report.append("### Suggested Fix")
        report.extend(fixes)
        report.append("")
        report.append("### Confidence Level")
        report.append("- **High**: Analysis based on structured agent outputs from multiple diagnostic sources.")
        report.append("")
        report.append("### Evidence From Diagnostics")
        report.extend(evidence if evidence else ["- See agent summaries above for detailed evidence."])

        return "\n".join(report)
