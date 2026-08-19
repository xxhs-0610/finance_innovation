from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.generation.refusal import assess_evidence_sufficiency, build_refusal
from app.generation.verifier import verify_answer
from app.schemas.answer_schema import AnswerResult, normalize_evidence


Generator = Callable[[str, list[dict[str, Any]]], str]


def generate_answer(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    generator: Generator | None = None,
    min_evidence_overlap: int = 1,
) -> dict[str, Any]:
    """Generate an evidence-bound answer and verify high-risk claims.

    ``generator`` is an optional adapter for an LLM provider. Without one, the
    default extractive generator is used so the repository remains runnable
    offline and has deterministic regression tests.
    """

    normalized = normalize_evidence(evidence)
    sufficiency = assess_evidence_sufficiency(
        question,
        normalized,
        min_overlap=min_evidence_overlap,
    )
    if not sufficiency.sufficient:
        refusal = build_refusal(question, sufficiency.reasons, normalized)
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        return refusal

    try:
        generated = (generator or _extractive_generator)(str(question or "").strip(), normalized)
    except Exception:
        refusal = build_refusal(question, ["答案生成服务调用失败。"], normalized)
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        return refusal
    answer_text = str(generated or "").strip()
    verification = verify_answer(answer_text, normalized, question=question)
    risk_tips: list[str] = []
    status = "answered"
    refusal_reason = ""

    if not verification["passed"]:
        status = "refused"
        refusal_reason = "；".join(verification["issues"])
        risk_tips.extend(verification["issues"])
        answer_text = "当前生成内容未通过证据校验，系统已拒绝输出未经核验的结论。"
    elif _has_multiple_scopes(normalized):
        risk_tips.append("证据来自不同文档或期间，使用前请确认适用范围和时点。")

    citations = verification.get("citations") or [item["citation_id"] for item in normalized]
    confidence = _estimate_confidence(normalized, verification, sufficiency.overlap)
    result = AnswerResult(
        status=status,
        answer=answer_text,
        evidence=normalized,
        risk_tips=risk_tips,
        confidence=confidence if status == "answered" else 0.0,
        citations=citations,
        verification={**verification, "sufficiency": sufficiency.to_dict()},
        refusal_reason=refusal_reason,
        question=str(question or "").strip(),
    )
    return result.to_dict()


def _extractive_generator(question: str, evidence: list[dict[str, Any]]) -> str:
    """Produce a conservative answer using only retrieved evidence text."""

    if not evidence:
        return ""
    metadata_answer = _answer_metadata_question(question, evidence)
    if metadata_answer is not None:
        return metadata_answer
    lines: list[str] = []
    for item in evidence[:3]:
        text = str(item.get("text") or "").strip().rstrip("。；;")
        if not text:
            continue
        citation = item.get("citation_id", "E1")
        source = item.get("source") or {}
        prefix = "数据证据" if item.get("chunk_type") == "table" else "制度依据"
        clause = source.get("clause_no") or source.get("cell_ref")
        locator = f"（{clause}）" if clause else ""
        lines.append(f"{prefix}{locator}：{text} [{citation}]")
    if not lines:
        return ""
    if len(lines) == 1:
        return f"结论：{lines[0]}"
    return "结论：结合检索到的证据，相关信息如下：\n" + "\n".join(
        f"{idx}. {line}" for idx, line in enumerate(lines, start=1)
    )


def _answer_metadata_question(question: str, evidence: list[dict[str, Any]]) -> str | None:
    source = evidence[0].get("source") or {}
    citation = evidence[0].get("citation_id", "E1")
    requested = False
    parts: list[str] = []

    field_markers = [
        ("发布机构", ("发布机构", "发文机关", "发布部门", "哪个机构", "哪个部门", "谁发布", "颁布"), source.get("issuer")),
        ("发布日期", ("发布日期", "发布时间", "何时发布", "什么时候发布", "哪年发布"), source.get("publish_date")),
        ("文件标题", ("文件名", "文件标题", "标题"), source.get("title")),
        ("原文来源", ("来源链接", "原文链接", "网址"), source.get("source_url")),
    ]
    for label, markers, value in field_markers:
        if any(marker in question for marker in markers):
            requested = True
            if str(value or "").strip():
                parts.append(f"{label}：{str(value).strip()}")

    if not requested:
        return None
    if not parts:
        return ""
    return f"结论：{'；'.join(parts)} [{citation}]"


def _estimate_confidence(
    evidence: list[dict[str, Any]],
    verification: dict[str, Any],
    overlap: int,
) -> float:
    if not evidence or not verification.get("passed"):
        return 0.0
    scores = [max(0.0, float(item.get("score", 0.0) or 0.0)) for item in evidence]
    score_signal = min(1.0, sum(scores[:3]) / max(1, len(scores[:3]))) if any(scores) else 0.5
    overlap_signal = min(1.0, overlap / 3) if overlap else 0.25
    citation_signal = 1.0 if verification.get("citations") else 0.6
    return min(0.98, 0.45 * score_signal + 0.35 * overlap_signal + 0.20 * citation_signal)


def _has_multiple_scopes(evidence: list[dict[str, Any]]) -> bool:
    docs = {str((item.get("source") or {}).get("doc_id") or "") for item in evidence}
    periods = {
        str((item.get("metadata") or {}).get("period") or "")
        for item in evidence
        if (item.get("metadata") or {}).get("period")
    }
    return len(docs - {""}) > 1 or len(periods) > 1


__all__ = ["generate_answer"]

