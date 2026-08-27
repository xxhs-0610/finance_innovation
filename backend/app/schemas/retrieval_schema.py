from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.schemas.chunk_schema import ChunkType, SearchResult
from app.schemas.task_plan_schema import TaskPlan


QueryType = Literal[
    "regulation_fact",
    "clause_threshold",
    "business_procedure",
    "table_lookup",
    "cross_document",
    "ambiguous",
    "unsupported",
]
RetrievalStatus = Literal[
    "answerable",
    "no_evidence",
    "needs_clarification",
    "degraded",
]


@dataclass(slots=True)
class QueryAnalysis:
    question: str
    query_type: QueryType
    keywords: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    entities: dict[str, str] = field(default_factory=dict)
    preferred_chunk_type: ChunkType | None = None
    # Enhanced Query Analyzer Structured Fields
    topic: str | None = None
    institution_type: str | None = None
    regulator: str | None = None
    document_name: str | None = None
    article_number: str | None = None
    indicator: str | None = None
    time_period: str | None = None
    rule_type: str | None = None
    # Task Planner Execution Plan
    task_type: str | None = None
    task_plan: TaskPlan | None = None

    def to_analyzer_dict(self) -> dict[str, Any]:
        """Return clean structured dictionary as requested by Task Planner / Query Analyzer spec."""
        clean_q = self.question.rstrip("？?。！!, ").strip()
        res: dict[str, Any] = {
            "query": clean_q,
            "topic": self.topic,
            "institution_type": self.institution_type,
            "regulator": self.regulator,
            "document_name": self.document_name,
            "article_number": self.article_number,
            "indicator": self.indicator,
            "time_period": self.time_period,
            "rule_type": self.rule_type,
            "keywords": self.keywords,
            "task_type": self.task_type,
        }
        if self.task_plan:
            res["task_plan"] = self.task_plan.to_dict()
        return res

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.task_plan:
            data["task_plan"] = self.task_plan.to_dict()
        data["analyzer"] = self.to_analyzer_dict()
        return data


@dataclass(slots=True)
class RetrievalResponse:
    query: str
    analysis: QueryAnalysis
    status: RetrievalStatus = "answerable"
    evidence: list[SearchResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    module4_guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "status": self.status,
            "analysis": self.analysis.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "diagnostics": self.diagnostics,
            "module4_guidance": self.module4_guidance,
        }
