"""Unified Evidence Schema for RegTrust-RAG (Prompt 10).

Defines the unified Evidence contract across all document types (Excel, Word, PDF).
Top-level tasks (LOOKUP, COMPARE, CALCULATE, OPTION_VERIFY, DIRECT_QA) interact
strictly with UnifiedEvidence, while EvidenceAdapter handles format-specific parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal["pdf", "word", "excel", "unknown"]


@dataclass(slots=True)
class UnifiedEvidence:
    """Standardized multi-format Evidence object."""
    evidence_id: str
    source_type: SourceType
    source_title: str
    location: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    structured_value: Any | None = None
    score: float = 1.0
    citation_id: str = "E1"
    issuer: str = ""
    publish_date: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Produce the standardized Prompt 10 dictionary structure."""
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_title": self.source_title,
            "location": self.location,
            "content": self.content,
            "structured_value": self.structured_value,
            "score": self.score,
            "citation_id": self.citation_id,
            "issuer": self.issuer,
            "publish_date": self.publish_date,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnifiedEvidence:
        """Construct UnifiedEvidence from standard or raw dictionary."""
        return cls(
            evidence_id=str(data.get("evidence_id") or data.get("chunk_id") or "E1"),
            source_type=data.get("source_type") or "unknown",  # type: ignore
            source_title=str(data.get("source_title") or data.get("title") or data.get("document_name") or ""),
            location=data.get("location") if isinstance(data.get("location"), dict) else {},
            content=str(data.get("content") or data.get("text") or ""),
            structured_value=data.get("structured_value"),
            score=float(data.get("score") or 1.0),
            citation_id=str(data.get("citation_id") or "E1"),
            issuer=str(data.get("issuer") or ""),
            publish_date=str(data.get("publish_date") or ""),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        )
