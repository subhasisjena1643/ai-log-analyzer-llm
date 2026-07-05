# src/services/knowledge_base.py

import json
import os
from typing import List, Dict
from src.models.knowledge_entry import KnowledgeEntry
# FIX: use the flexible vector store (same as rag_engine.py uses)
from src.services.vector_store_flexible import FlexibleVectorStore as VectorStore
from src.utils.chunker import LogChunker
from src.services.kb_excel_loader import load_kb_from_excel


class KnowledgeBase:
    def __init__(self, kb_path: str = None, config_path="config.yaml"):
        self.kb_path = kb_path or "./data/kb/fixes.json"
        self.entries: List[KnowledgeEntry] = []
        self.vector_store = VectorStore(index_name="kb_index", config_path=config_path)
        self.chunker = LogChunker()

        self.load_kb()
        self.index_kb()

    def load_kb(self):
        excel_path = "./data/kb/kb_fixes.csv"
        if os.path.exists(excel_path):
            self.entries = load_kb_from_excel(excel_path)
            self.save_kb()
        else:
            self.entries = []

    def save_kb(self):
        os.makedirs(os.path.dirname(self.kb_path), exist_ok=True)
        # FIX: add utf-8 encoding to prevent UnicodeEncodeError on Windows
        with open(self.kb_path, "w", encoding="utf-8") as f:
            json.dump([entry.__dict__ for entry in self.entries], f, indent=2, ensure_ascii=False)

    def index_kb(self):
        texts = []
        metadatas = []
        for i, entry in enumerate(self.entries):
            text = (
                f"Issue: {entry.issue}\n"
                f"Root Cause: {entry.root_cause}\n"
                f"Solution: {entry.solution}\n"
                f"Tags: {', '.join(entry.tags)}"
            )
            texts.append(text)
            metadatas.append({
                "id": i,
                "issue": entry.issue,
                "root_cause": entry.root_cause,
                "solution": entry.solution,
                "affected_components": entry.affected_components,
                "tags": entry.tags,
                "type": "kb_fix"
            })
        if texts:
            self.vector_store.add_documents(texts, metadatas)

    def search_similar_issues(self, query: str, top_k: int = 3) -> List[Dict]:
        results = self.vector_store.search(query, top_k)
        formatted = []
        for similarity, metadata in results:
            if similarity < 0.35:
                continue
            formatted.append({
                "similarity": round(similarity, 3),
                "issue": metadata["issue"],
                "root_cause": metadata["root_cause"],
                "solution": metadata["solution"],
                "affected_components": metadata["affected_components"],
                "confidence": (
                    "High" if similarity >= 0.75
                    else "Medium" if similarity >= 0.55
                    else "Low"
                )
            })
        return formatted

    def search_solutions(self, query: str) -> List[Dict]:
        results = self.search_similar_issues(query, top_k=2)
        solutions = []
        for result in results:
            solutions.append({
                "error_type": result["issue"],
                "component": (
                    result["affected_components"][0]
                    if result["affected_components"]
                    else "Unknown"
                ),
                "confidence": result["confidence"],
                "root_cause": result["root_cause"],
                "solution_steps": [
                    step.strip()
                    for step in result["solution"].split(".")
                    if step.strip()
                ],
                "prevention": "Regular monitoring and proactive maintenance",
                "resources": ["Knowledge Base"]
            })
        return solutions

    def search_by_component(self, component: str) -> List[Dict]:
        results = []
        for entry in self.entries:
            if entry.affected_components:
                for comp in entry.affected_components:
                    if component.lower() in comp.lower():
                        results.append({
                            "error_type": entry.issue,
                            "component": comp,
                            "confidence": "High",
                            "root_cause": entry.root_cause,
                            "solution_steps": [
                                step.strip()
                                for step in entry.solution.split(".")
                                if step.strip()
                            ],
                            "prevention": "Regular monitoring and validation",
                            "resources": ["Knowledge Base"]
                        })
                        break
        return results


    def load_kb(self):
        excel_path = "./data/kb/kb_fixes.csv"

        if os.path.exists(excel_path):
            self.entries = load_kb_from_excel(excel_path)
            self.save_kb()  # optional backup to JSON
        else:
            self.entries = []


    def save_kb(self):
        os.makedirs(os.path.dirname(self.kb_path), exist_ok=True)
        with open(self.kb_path, "w") as f:
            json.dump([entry.__dict__ for entry in self.entries], f, indent=2)

    # -------------------------
    # INDEXING
    # -------------------------

    def index_kb(self):
        texts = []
        metadatas = []

        for i, entry in enumerate(self.entries):
            text = (
                f"Issue: {entry.issue}\n"
                f"Root Cause: {entry.root_cause}\n"
                f"Solution: {entry.solution}\n"
                f"Tags: {', '.join(entry.tags)}"
            )
            texts.append(text)

            metadatas.append({
                "id": i,
                "issue": entry.issue,
                "root_cause": entry.root_cause,
                "solution": entry.solution,
                "affected_components": entry.affected_components,
                "tags": entry.tags,
                "type": "kb_fix"
            })

        if texts:
            self.vector_store.add_documents(texts, metadatas)

    # -------------------------
    # VECTOR SEARCH
    # -------------------------

    def search_similar_issues(self, query: str, top_k: int = 3) -> List[Dict]:
        results = self.vector_store.search(query, top_k)

        formatted = []
        for similarity, metadata in results:
            if similarity < 0.35:  # relaxed threshold
                continue

            formatted.append({
                "similarity": round(similarity, 3),
                "issue": metadata["issue"],
                "root_cause": metadata["root_cause"],
                "solution": metadata["solution"],
                "affected_components": metadata["affected_components"],
                "confidence": (
                    "High" if similarity >= 0.75
                    else "Medium" if similarity >= 0.55
                    else "Low"
                )
            })

        return formatted

    # -------------------------
    # MAIN SOLUTION PIPELINE (USED BY UI)
    # -------------------------

    def search_solutions(self, query: str) -> List[Dict]:
        """
        Used by Recommended Fix section
        """
        results = self.search_similar_issues(query, top_k=2)

        solutions = []
        for result in results:
            solutions.append({
                "error_type": result["issue"],
                "component": (
                    result["affected_components"][0]
                    if result["affected_components"]
                    else "Unknown"
                ),
                "confidence": result["confidence"],
                "root_cause": result["root_cause"],
                "solution_steps": [
                    step.strip()
                    for step in result["solution"].split(".")
                    if step.strip()
                ],
                "prevention": "Regular monitoring and proactive maintenance",
                "resources": ["Knowledge Base"]
            })

        return solutions

    # -------------------------
    # ✅ FIX FOR YOUR ERROR
    # -------------------------

    def search_by_component(self, component: str) -> List[Dict]:
        """
        Search KB by affected component (used by analyze_logs)
        """
        results = []

        for entry in self.entries:
            if entry.affected_components:
                for comp in entry.affected_components:
                    if component.lower() in comp.lower():
                        results.append({
                            "error_type": entry.issue,
                            "component": comp,
                            "confidence": "High",
                            "root_cause": entry.root_cause,
                            "solution_steps": [
                                step.strip()
                                for step in entry.solution.split(".")
                                if step.strip()
                            ],
                            "prevention": "Regular monitoring and validation",
                            "resources": ["Knowledge Base"]
                        })
                        break

        return results
