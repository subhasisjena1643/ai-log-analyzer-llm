# src/services/rag_engine.py
from typing import List, Dict
import yaml
import re


from src.services.vector_store_flexible import FlexibleVectorStore as VectorStore
from src.services.knowledge_base import KnowledgeBase
from src.utils.parser import LogParser


class RAGEngine:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.vector_store = VectorStore(config_path=config_path)
        self.knowledge_base = KnowledgeBase(config_path=config_path)
        self.parser = LogParser()
        

        print("[INFO] RAG Engine initialized")

    # -------------------------------------------------
    # LOG SEARCH
    # -------------------------------------------------

    def find_exact_matches(self, query: str, log_text: str) -> List[str]:
        return [
            line for line in log_text.split("\n")
            if query.lower() in line.lower() and "ERROR" in line
        ]

    def find_similar_errors(self, query: str, log_text: str) -> List[str]:
        keywords = ["timeout", "failed", "error", "crash", "connection", "latency"]
        results = set()

        for line in log_text.split("\n"):
            if "ERROR" not in line:
                continue
            for word in keywords + query.lower().split():
                if len(word) > 3 and word in line.lower():
                    results.add(line)
                    break

        return list(results)

    # -------------------------------------------------
    # KB SOLUTIONS
    # -------------------------------------------------

    def get_relevant_solutions(self, error_lines: List[str]) -> List[Dict]:
        solutions = []
        for line in error_lines[:5]:
            kb_results = self.knowledge_base.search_solutions(line)
            for kb in kb_results[:1]:
                solutions.append({
                    "error": kb.get("error_type", "Known Issue"),
                    "solution": "\n".join(kb.get("solution_steps", [])),
                    "confidence": kb.get("confidence", "Medium")
                })
        return solutions

    # -------------------------------------------------
    # MAIN PIPELINE (THIS MATCHES app.py)
    # -------------------------------------------------

    def process_query(
        self,
        query: str,
        log_data: Dict,
        zone: str = None,
        client: str = None,
        app: str = None
    ) -> Dict:

        log_text = log_data.get("raw", "")
        exact_matches = self.find_exact_matches(query, log_text)
        error_lines = exact_matches or self.find_similar_errors(query, log_text)

        solutions = self.get_relevant_solutions(error_lines)

        # Rule-based RCA
        rca = self._generate_simple_rca(query, log_data, error_lines, solutions)

        # LLM-based RCA
        llm_explanation = self.generate_local_ai_explanation(
            query, error_lines, solutions, log_data
        )


        return {
            "rca": rca,
            "llm_explanation": llm_explanation,
            "exact_matches": exact_matches,
            "similar_errors": error_lines,
            "solutions": solutions,
            "retrieval_filter": {
                "zone": zone,
                "client": client,
                "app": app
            }
        }

    # -------------------------------------------------
    # RULE-BASED RCA
    # -------------------------------------------------

    def _generate_simple_rca(self, query, log_data, error_lines, solutions) -> str:
        sql_ctx = log_data.get("sql_context", {})
        pdf_ctx = log_data.get("pdf_context", {})
        mem_ctx = log_data.get("memory_context", {})
        inf_ctx = log_data.get("inference_context", {})
        
        diagnostics = []
        if sql_ctx:
            diagnostics.append(f"SQL files parsed: {len(sql_ctx)}")
        if pdf_ctx:
            diagnostics.append(f"Healthcheck reports parsed: {len(pdf_ctx)}")
        if mem_ctx:
            diagnostics.append(f"JVM Heap diagnostics parsed: {len(mem_ctx)}")
        if inf_ctx:
            diagnostics.append(f"Incident notes parsed: {len(inf_ctx)}")
            
        diag_str = f" with {', '.join(diagnostics)}" if diagnostics else ""
        
        if not error_lines:
            return f"No errors found for query: {query}{diag_str}."
        return f"Errors found: {len(error_lines)}{diag_str}."

    # -------------------------------------------------
    # LLM-BASED RCA (AI TAB)
    # -------------------------------------------------

    # In rag_engine.py — replace the broken generate_llm_rca
    def generate_llm_rca(self, query: str, error_lines: list, kb_solutions: list) -> str:
        """Placeholder — real LLM call is done in app.py via BedrockLLM"""
        logs = "\n".join(error_lines[:5])
        return f"LLM RCA not available in local mode. Query: {query}\nErrors:\n{logs}"

    
    def generate_local_ai_explanation(self, query, error_lines, solutions, log_data=None):
        explanation = f"""
    ### 🤖 AI Explanation (Simulated)

    **Query:** {query}

    **What happened**
    The system logs indicate repeated error patterns related to service failures and operational instability.
"""
        if log_data:
            sql_ctx = log_data.get("sql_context", {})
            pdf_ctx = log_data.get("pdf_context", {})
            mem_ctx = log_data.get("memory_context", {})
            
            extra_signals = []
            if sql_ctx:
                for f, d in sql_ctx.items():
                    if d.get("errors_found"):
                        extra_signals.append(f"SQL error in {f}: {d['errors_found'][0]}")
            if pdf_ctx:
                for f, d in pdf_ctx.items():
                    if d.get("failures"):
                        extra_signals.append(f"PDF Healthcheck failure in {f}: {d['failures'][0]}")
            if mem_ctx:
                for f, d in mem_ctx.items():
                    if d.get("heap_used_mb"):
                        extra_signals.append(f"JVM Heap usage in {f}: {d['heap_used_mb']:.1f} MB / {d.get('heap_max_mb', 'N/A')} MB")
                        
            if extra_signals:
                explanation += "\n    **Correlated Diagnostic Signals:**\n"
                for sig in extra_signals[:4]:
                    explanation += f"    - {sig}\n"

        explanation += """
    **Possible root cause**
"""

        for line in error_lines[:3]:
            explanation += f"    - {line[:120]}\n"

        explanation += "\n    **Recommended fix**\n"

        if solutions:
            for sol in solutions:
                explanation += f"    - {sol['solution']}\n"
        else:
            explanation += "    - Review service configuration and retry the operation.\n"

        explanation += "\n    **Prevention**\n    - Improve monitoring and alerting\n    - Validate configs before deployment\n"

        return explanation
