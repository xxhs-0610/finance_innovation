"""Evidence sufficiency and refusal policy for module 4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.indexing.text_utils import query_tokens
from app.schemas.answer_schema import normalize_evidence


@dataclass(slots=True)
class SufficiencyResult:
    sufficient: bool
    overlap: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "overlap": self.overlap,
            "reasons": list(self.reasons),
        }


def assess_evidence_sufficiency(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    min_overlap: int = 1,
) -> SufficiencyResult:
    """Return a conservative evidence decision before generation."""

    records = normalize_evidence(evidence)
    reasons: list[str] = []
    if not str(question or "").strip():
        return SufficiencyResult(False, reasons=["问题为空，无法判断回答范围。"])
    if not records:
        return SufficiencyResult(False, reasons=["没有可用证据。"])

    question_tokens = _substantive_tokens(question)
    if not question_tokens:
        return SufficiencyResult(False, reasons=["问题缺少可识别的关键词，请补充具体条件。"])
    include_source = any(
        marker in question
        for marker in ("发布", "发文", "机构", "部门", "机关", "日期", "何时", "文号", "文件名", "标题")
    )
    evidence_text = " ".join(
        _evidence_search_text(item, include_source=include_source) for item in records
    )
    overlap = sum(1 for token in question_tokens if token and token in evidence_text)
    source_metadata_supports_question = _has_requested_source_metadata(question, records)
    if question_tokens and overlap < min_overlap and not source_metadata_supports_question:
        reasons.append("证据与问题的关键词重合度不足。")

    if all(not str(item.get("source", {}).get("doc_id") or "").strip() for item in records):
        reasons.append("证据缺少可追溯的文档标识。")

    explicit_quality = [
        (item.get("metadata") or {}).get("evidence_quality", {}).get("complete")
        for item in records
        if isinstance((item.get("metadata") or {}).get("evidence_quality"), dict)
    ]
    if explicit_quality and not any(value is True for value in explicit_quality):
        reasons.append("证据来源字段不完整，无法形成可靠引用。")

    return SufficiencyResult(not reasons, overlap=overlap, reasons=reasons)


def build_refusal(
    question: str,
    reasons: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create the stable refusal payload consumed by module 5."""

    reason_list = [item for item in (reasons or []) if str(item).strip()]
    if not reason_list:
        reason_list = ["当前证据不足以支持确定性回答。"]
    return {
        "status": "refused",
        "answer": "当前证据不足以支持确定性回答，请补充问题条件或检查知识库范围。",
        "evidence": normalize_evidence(evidence or []),
        "risk_tips": reason_list + ["系统已拒绝猜测，建议补充时间、机构或指标范围。"],
        "confidence": 0.0,
        "citations": [],
        "verification": {
            "passed": False,
            "issues": reason_list,
            "numeric_claims": [],
            "date_claims": [],
            "document_no_claims": [],
            "institution_claims": [],
            "unsupported_claims": [],
        },
        "refusal_reason": "；".join(reason_list),
        "question": str(question or "").strip(),
    }


def _substantive_tokens(text: str) -> list[str]:
    tokens = query_tokens(text)
    ignored = {"什么", "哪些", "如何", "是否", "怎么", "情况", "相关", "请问", "可以"}
    return [token for token in tokens if len(token) >= 2 and token not in ignored]


def _evidence_search_text(item: dict[str, Any], *, include_source: bool = False) -> str:
    source = item.get("source") or {}
    metadata = item.get("metadata") or {}
    fields = [
        item.get("text"),
        item.get("retrieval_text"),
        source.get("clause_no"),
        source.get("sheet_name"),
        source.get("table_name"),
        metadata.get("metric_name"),
        metadata.get("period"),
        metadata.get("unit"),
        metadata.get("value"),
    ]
    if include_source:
        fields.extend(
            [
                source.get("title"),
                source.get("issuer"),
                source.get("publish_date"),
            ]
        )
    return " ".join(str(field).strip() for field in fields if str(field or "").strip())


def _has_requested_source_metadata(question: str, evidence: list[dict[str, Any]]) -> bool:
    requests = [
        (("发布机构", "发文机关", "发布部门", "哪个机构", "哪个部门", "谁发布", "颁布"), "issuer"),
        (("发布日期", "发布时间", "何时发布", "什么时候发布", "哪年发布"), "publish_date"),
        (("文件名", "文件标题", "标题"), "title"),
        (("来源链接", "原文链接", "网址"), "source_url"),
    ]
    requested_fields = [field for markers, field in requests if any(marker in question for marker in markers)]
    if not requested_fields:
        return False
    for field in requested_fields:
        if not any(str((item.get("source") or {}).get(field) or "").strip() for item in evidence):
            return False
    return True


__all__ = ["SufficiencyResult", "assess_evidence_sufficiency", "build_refusal"]
