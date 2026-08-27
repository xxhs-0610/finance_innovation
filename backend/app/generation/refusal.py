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


REASON_CODE_EXPLANATIONS: dict[str, str] = {
    "AMBIGUOUS_QUERY": (
        "您的问题表述不够明确或缺少具体的业务判断条件，请补充具体机构、指标或业务背景后再次提问。"
    ),
    "RETRIEVAL_FAILED": (
        "系统检索未能定位到与该问题相关的制度或报表切片，请确认提问是否在监管知识库收录范围内。"
    ),
    "MISSING_EVIDENCE": (
        "该问题属于本系统的银行业监管问答范围，但当前知识库中未检索到能够支持可靠回答的相关依据。"
    ),
    "NO_RELEVANT_EVIDENCE": (
        "该问题属于本系统的银行业监管问答范围，但当前知识库中未检索到能够支持可靠回答的相关依据。"
    ),
    "MISSING_OPERAND": (
        "系统已定位查询目标，但在知识库对应表格中未能完整提取到必要的操作数数值，无法完成确定性计算或比较。"
    ),
    "CONFLICTING_EVIDENCE": (
        "检索到的不同监管资料之间存在规定或数值冲突，在进一步核实明确版本差异前，暂不直接给出确定结论。"
    ),
    "CALCULATION_FAILED": (
        "表格确定性算术执行失败（数学计算异常），无法生成可靠计算结果。"
    ),
    "OPTION_NOT_VERIFIED": (
        "经逐项条款比对，选项依据不足或未在指定监管文件中找到明确正向支持。"
    ),
    "INSUFFICIENT_OPTIONS": (
        "选项验证未能筛选出符合题目数量要求的确定性正确答案。"
    ),
    "GROUNDING_FAILED": (
        "回答内容在最终事实核验中未通过可信度检查（包含未充分证实的推测），系统已安全拦截。"
    ),
    "INSUFFICIENT_COVERAGE": (
        "当前检索证据仅覆盖了部分问题要求，证据覆盖度不足以得出完整结论，因此暂不提供确定回答。"
    ),
    "MISSING_NUMERIC_EVIDENCE": (
        "当前检索资料涉及该指标，但没有找到能够支持用户所询问具体数值的可靠证据，因此暂不提供确定数值。"
    ),
    "MISSING_KEY_FACT": (
        "当前检索资料涉及相关业务主题，但缺少推导确定性结论的关键监管事实依据，暂不直接给出确定结论。"
    ),
    "OUTDATED_OR_VERSION_UNCLEAR": (
        "当前检索到的资料存在版本或生效时间不明确的问题，为避免引用失效规定，暂不直接给出确定结论。"
    ),
    "MISSING_SCENARIO_CONDITION": (
        "当前监管规定针对不同机构档位或业务场景设有不同的监管要求，请补充具体适用条件后再行查询。"
    ),
}


def format_verifier_refusal_answer(
    reason_code: str,
    *,
    reason: str = "",
    missing_information: list[str] | None = None,
) -> str:
    """Generate distinct, specialized refusal text based on reason_code."""
    base_text = REASON_CODE_EXPLANATIONS.get(reason_code)
    if not base_text:
        return reason or "当前证据不足以支持确定性回答，请补充问题条件或检查知识库范围。"

    if missing_information:
        missing_str = "；".join(missing_information)
        if reason_code == "INSUFFICIENT_COVERAGE":
            return f"当前检索证据仅覆盖了部分问题要求（缺少：{missing_str}），证据覆盖度不足以得出完整结论，因此暂不提供确定回答。"
        elif reason_code == "MISSING_NUMERIC_EVIDENCE":
            return f"当前检索资料涉及该指标，但没有找到能够支持用户所询问具体数值的可靠证据（缺失：{missing_str}），因此暂不提供确定数值。"
        elif reason_code == "MISSING_KEY_FACT":
            return f"当前检索资料涉及相关业务主题，但缺少推导确定性结论的关键监管事实依据（缺失：{missing_str}），暂不直接给出确定结论。"
        elif reason_code == "MISSING_OPERAND":
            return f"系统已定位目标表格，但未能在表格中提取到以下必要操作数数值（{missing_str}），无法完成确定性比对或计算。"

    return base_text


def build_refusal(
    question: str,
    reasons: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    *,
    reason_code: str | None = None,
    missing_information: list[str] | None = None,
    custom_answer: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Create the stable refusal payload consumed by module 5 with specialized reason_code explanations."""

    reason_list = [item for item in (reasons or []) if str(item).strip()]
    if not reason_list:
        reason_list = ["当前证据不足以支持确定性回答。"]

    final_error_code = error_code or reason_code or "MISSING_EVIDENCE"

    if custom_answer:
        answer_text = custom_answer
    elif reason_code:
        answer_text = format_verifier_refusal_answer(
            reason_code,
            reason="；".join(reason_list),
            missing_information=missing_information,
        )
    elif error_code and error_code in REASON_CODE_EXPLANATIONS:
        answer_text = REASON_CODE_EXPLANATIONS[error_code]
    else:
        answer_text = "当前证据不足以支持确定性回答，请补充问题条件或检查知识库范围。"

    return {
        "status": "refused",
        "answer": answer_text,
        "evidence": normalize_evidence(evidence or []),
        "risk_tips": reason_list + ["系统坚持有依据才回答原则，已拒绝输出未经核验的推测。"],
        "confidence": 0.0,
        "citations": [],
        "error_code": final_error_code,
        "verification": {
            "passed": False,
            "issues": reason_list,
            "error_code": final_error_code,
            "numeric_claims": [],
            "date_claims": [],
            "document_no_claims": [],
            "institution_claims": [],
            "unsupported_claims": [],
        },
        "refusal_reason": "；".join(reason_list) if reason_list else final_error_code,
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
