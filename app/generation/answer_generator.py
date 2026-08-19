from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from app.generation.refusal import assess_evidence_sufficiency, build_refusal
from app.generation.verifier import verify_answer
from app.schemas.answer_schema import (
    AnswerResult,
    normalize_evidence,
    normalize_retrieval_response,
)


Generator = Callable[[str, list[dict[str, Any]]], str]


def generate_answer(
    question: str,
    evidence: Any,
    *,
    generator: Generator | None = None,
    min_evidence_overlap: int = 1,
) -> dict[str, Any]:
    """Generate an evidence-bound answer and verify high-risk claims.

    ``generator`` is an optional adapter for an LLM provider. Without one, the
    default extractive generator is used so the repository remains runnable
    offline and has deterministic regression tests.
    """

    retrieval = normalize_retrieval_response(evidence)
    retrieval_status = ""
    retrieval_guidance: dict[str, Any] = {}
    retrieval_diagnostics: dict[str, Any] = {}
    if retrieval is not None:
        normalized = retrieval["evidence"]
        retrieval_status = str(retrieval.get("status") or "")
        retrieval_guidance = retrieval["module4_guidance"]
        retrieval_diagnostics = retrieval["diagnostics"]
        gated = _handle_retrieval_gate(
            question,
            normalized,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )
        if gated is not None:
            return gated
    else:
        normalized = normalize_evidence(evidence)

    normalized = _add_deterministic_table_derivations(normalized, question)
    sufficiency = assess_evidence_sufficiency(
        question,
        normalized,
        min_overlap=min_evidence_overlap,
    )
    if not sufficiency.sufficient:
        refusal = build_refusal(question, sufficiency.reasons, normalized)
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        return _attach_retrieval_context(
            refusal,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )

    try:
        generated = (generator or _extractive_generator)(str(question or "").strip(), normalized)
    except Exception:
        refusal = build_refusal(question, ["答案生成服务调用失败。"], normalized)
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        return _attach_retrieval_context(
            refusal,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )
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

    if retrieval_status == "degraded":
        risk_tips.append(_degraded_risk_tip(retrieval_diagnostics))

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
    payload = result.to_dict()
    if retrieval_status:
        payload["status"] = "degraded" if retrieval_status == "degraded" and status == "answered" else payload["status"]
    return _attach_retrieval_context(
        payload,
        retrieval_status,
        retrieval_guidance,
        retrieval_diagnostics,
    )


def _handle_retrieval_gate(
    question: str,
    evidence: list[dict[str, Any]],
    retrieval_status: str,
    guidance: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    """Honor module 3's answerability decision before any generation."""

    action = str(guidance.get("action") or "")
    may_generate = guidance.get("may_generate_answer")
    if may_generate is None:
        may_generate = retrieval_status in {"answerable", "degraded"} and bool(evidence)

    if retrieval_status == "no_evidence" or action == "refuse":
        refusal = build_refusal(
            question,
            [str(guidance.get("reason") or "模块3未找到足够的可靠证据。")],
            evidence,
        )
        refusal["status"] = "no_evidence" if retrieval_status == "no_evidence" else "refused"
        return _attach_retrieval_context(
            refusal, retrieval_status, guidance, diagnostics
        )

    if retrieval_status == "needs_clarification" or action == "clarify" or not may_generate:
        clarification = str(guidance.get("clarification_question") or "请补充问题中的适用对象或查询条件。")
        options = guidance.get("clarification_options")
        payload = {
            "status": "needs_clarification",
            "answer": clarification,
            "evidence": evidence,
            "risk_tips": ["信息条件不足，系统未生成确定性答案。"],
            "confidence": 0.0,
            "citations": [],
            "verification": {
                "passed": False,
                "issues": ["模块3要求先澄清问题条件。"],
                "sufficiency": {"sufficient": False, "reasons": ["模块3要求先澄清问题条件。"]},
            },
            "clarification_question": clarification,
            "question": str(question or "").strip(),
        }
        if isinstance(options, list) and options:
            payload["clarification_options"] = options
        return _attach_retrieval_context(
            payload, retrieval_status, guidance, diagnostics
        )

    return None


def _attach_retrieval_context(
    payload: dict[str, Any],
    retrieval_status: str,
    guidance: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    if retrieval_status:
        payload["retrieval_status"] = retrieval_status
        payload["module4_guidance"] = guidance
        payload["diagnostics"] = diagnostics
    return payload


def _degraded_risk_tip(diagnostics: dict[str, Any]) -> str:
    failures = diagnostics.get("failures") if isinstance(diagnostics, Mapping) else None
    if isinstance(failures, list) and failures:
        components = [str(item.get("component")) for item in failures if isinstance(item, Mapping) and item.get("component")]
        if components:
            return f"检索链路部分降级（{', '.join(components)}），答案仅基于当前可用证据生成。"
    return "检索链路部分降级，答案仅基于当前可用证据生成。"


def _add_deterministic_table_derivations(
    evidence: list[dict[str, Any]], question: str
) -> list[dict[str, Any]]:
    """Record safe ratio conversions without overwriting source values."""

    wants_ratio = any(marker in str(question or "") for marker in ("百分比", "百分率", "占比", "比例", "率"))
    if not wants_ratio:
        return evidence
    output: list[dict[str, Any]] = []
    for item in evidence:
        record = deepcopy(item)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
        metadata = dict(metadata)
        metric = str(metadata.get("metric_name") or "")
        unit = str(metadata.get("unit") or "")
        raw = metadata.get("value_numeric", metadata.get("value"))
        if "率" in metric or "比例" in metric or "占比" in metric:
            converted = _ratio_as_percent(raw, unit)
            if converted is not None:
                metadata.setdefault("derived_values", []).append({
                    "kind": "ratio_to_percent",
                    "source_value": str(raw),
                    "display_value": converted,
                    "explanation": f"保留原值 {raw}，按百分比展示为 {converted}。",
                })
        record["metadata"] = metadata
        output.append(record)
    return output


def _ratio_as_percent(raw: Any, unit: str) -> str | None:
    if "%" not in unit and "％" not in unit:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not Decimal("-1") <= value <= Decimal("1") or value == 0:
        return None
    return f"{(value * 100).normalize():f}%"


def _extractive_generator(question: str, evidence: list[dict[str, Any]]) -> str:
    """Produce a conservative answer using only retrieved evidence text."""

    if not evidence:
        return ""
    metadata_answer = _answer_metadata_question(question, evidence)
    if metadata_answer is not None:
        return metadata_answer
    lines: list[str] = []
    for item in evidence[:3]:
        text = _evidence_text_for_answer(item)
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


def _evidence_text_for_answer(item: dict[str, Any]) -> str:
    text = str(item.get("text") or "").strip().rstrip("。；;")
    derived = (item.get("metadata") or {}).get("derived_values", [])
    if isinstance(derived, list):
        explanations = [
            str(value.get("explanation"))
            for value in derived
            if isinstance(value, Mapping) and value.get("explanation")
        ]
        if explanations:
            text = f"{text}（{'；'.join(explanations)}）"
    return text


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

