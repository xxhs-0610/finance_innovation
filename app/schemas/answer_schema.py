"""Schemas and normalization helpers for module 4 answers.

The project intentionally keeps these schemas as plain dictionaries so that the
result can be returned directly by the current Streamlit frontend and by a
future FastAPI route without requiring a new runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any


AnswerStatus = str


@dataclass(slots=True)
class AnswerResult:
    """Stable response contract consumed by module 5."""

    status: AnswerStatus
    answer: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risk_tips: list[str] = field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    refusal_reason: str = ""
    question: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "status": self.status,
            "answer": self.answer,
            "evidence": self.evidence,
            "risk_tips": self.risk_tips,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 4),
            "citations": self.citations,
            "verification": self.verification,
        }
        if self.refusal_reason:
            data["refusal_reason"] = self.refusal_reason
        if self.question:
            data["question"] = self.question
        return data


def normalize_evidence(evidence: Any) -> list[dict[str, Any]]:
    """Normalize module 3 results while preserving all source metadata."""

    if evidence is None:
        return []
    if not isinstance(evidence, (list, tuple)):
        evidence = [evidence]

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if not isinstance(item, dict):
            continue

        record = dict(item)
        source = record.get("source")
        if hasattr(source, "to_dict"):
            source = source.to_dict()
        if not isinstance(source, dict):
            source = {}
        record["source"] = dict(source)

        text = str(record.get("text") or record.get("retrieval_text") or "").strip()
        if not text:
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                text = str(metadata.get("retrieval_text") or "").strip()
        if not text:
            continue

        record["text"] = text
        record.setdefault("chunk_id", f"evidence_{index:03d}")
        record.setdefault("chunk_type", "unknown")
        try:
            record["score"] = float(record.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            record["score"] = 0.0
        record["citation_id"] = f"E{len(normalized) + 1}"
        normalized.append(record)
    return normalized


def normalize_retrieval_response(response: Any) -> dict[str, Any] | None:
    """Normalize module 3's full response without importing retrieval code.

    The helper accepts a ``RetrievalResponse`` dataclass, its serialized
    dictionary form, or any compatible object exposing ``to_dict``. A plain
    evidence list intentionally returns ``None`` because it is the legacy
    compatibility input and has no retrieval status or guidance.
    """

    if response is None or isinstance(response, (list, tuple)):
        return None
    if hasattr(response, "to_dict"):
        response = response.to_dict()
    elif hasattr(response, "status") and hasattr(response, "evidence"):
        response = {
            "status": getattr(response, "status", ""),
            "evidence": getattr(response, "evidence", []),
            "module4_guidance": getattr(response, "module4_guidance", {}),
            "diagnostics": getattr(response, "diagnostics", {}),
            "analysis": getattr(response, "analysis", {}),
            "query": getattr(response, "query", ""),
        }
    if not isinstance(response, Mapping):
        return None
    data = dict(response)
    if "evidence" not in data:
        return None
    data["evidence"] = normalize_evidence(data.get("evidence"))
    guidance = data.get("module4_guidance")
    data["module4_guidance"] = dict(guidance) if isinstance(guidance, Mapping) else {}
    diagnostics = data.get("diagnostics")
    data["diagnostics"] = dict(diagnostics) if isinstance(diagnostics, Mapping) else {}
    return data


__all__ = [
    "AnswerResult",
    "AnswerStatus",
    "normalize_evidence",
    "normalize_retrieval_response",
]
