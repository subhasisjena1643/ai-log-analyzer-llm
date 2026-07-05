from dataclasses import dataclass

@dataclass
# src/models/knowledge_entry.py

class KnowledgeEntry:
    def __init__(
        self,
        issue: str,
        root_cause: str,
        solution: str,
        affected_components=None,
        tags=None,
        severity: str = "Medium",
        resolution_time: str = "1 hour",
        confidence: float = 1.0
    ):
        self.issue = issue
        self.root_cause = root_cause
        self.solution = solution
        self.affected_components = affected_components or []
        self.tags = tags or []
        self.severity = severity
        self.resolution_time = resolution_time
        self.confidence = confidence

