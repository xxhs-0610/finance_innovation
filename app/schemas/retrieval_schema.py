from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.schemas.chunk_schema import ChunkType, SearchResult


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

    def to_dict(self) -> dict:
        return asdict(self)


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
