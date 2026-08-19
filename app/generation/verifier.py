"""Deterministic post-generation checks for evidence-bound answers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.answer_schema import normalize_evidence


NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|％|‰|万亿元|亿元|万元|元|万人次|万人|人次|户|家|天|日|个月|年)?"
)
DATE_RE = re.compile(r"(?:20\d{2}(?:[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?|年(?:第?[一二三四]季度|上半年|下半年)?)?)")
MODAL_RE = re.compile(r"应当|必须|不得|禁止|可以|可|原则上|不应|应予")
CITATION_RE = re.compile(r"\[(E\d+)\]|\b(E\d+)\b", re.IGNORECASE)
DOC_NO_RE = re.compile(
    r"(?:银保监规|银保监发|银监发|保监发|金规|金发|证监发|财金|金融监管总局令)"
    r"(?:〔|\[|【)\d{4}(?:〕|\]|】)\d{1,4}号"
    r"|(?:国家金融监督管理总局令|中国人民银行令|中国银保监会令|中国银监会令)"
    r"\s*\d{4}年第?\d+号"
)
EXACT_INSTITUTION_RE = re.compile(
    r"国家金融监督管理总局|中国人民银行|中国银行保险监督管理委员会|"
    r"中国证券监督管理委员会|原中国银保监会|中国银保监会|中国证监会|财政部"
)
GENERIC_INSTITUTION_RE = re.compile(
    r"(?<![\u4e00-\u9fff])[\u4e00-\u9fff]{2,10}(?:银行|保险公司|证券公司|金融监管局|银保监局)"
)


def verify_answer(
    answer: str,
    evidence: list[dict[str, Any]],
    *,
    question: str = "",
) -> dict[str, Any]:
    """Check numeric, date and normative claims against supplied evidence."""

    text = str(answer or "").strip()
    records = normalize_evidence(evidence)
    evidence_text = " ".join(_search_text(item) for item in records)
    normalized_evidence = _normalize_for_match(evidence_text)

    numeric_claims = _extract_claims(NUMBER_RE, text, _normalize_number_claim)
    date_claims = _extract_claims(DATE_RE, text, _normalize_date_claim)
    modality_claims = _extract_claims(MODAL_RE, text, lambda value: value)
    document_no_claims = _extract_claims(DOC_NO_RE, text, _normalize_for_match)
    institution_claims = _extract_institution_claims(text)
    unsupported: list[dict[str, str]] = []
    supported: list[dict[str, str]] = []

    all_claims = numeric_claims + date_claims + modality_claims + document_no_claims + institution_claims
    for claim in all_claims:
        normalized = claim["normalized"]
        if _claim_supported(claim["raw"], normalized, normalized_evidence, kind=claim["kind"]):
            supported.append(claim)
        else:
            unsupported.append(claim)

    citation_ids = sorted({(match.group(1) or match.group(2)).upper() for match in CITATION_RE.finditer(text)})
    valid_citations = {str(item.get("citation_id", "")).upper() for item in records}
    unknown_citations = [citation for citation in citation_ids if citation not in valid_citations]
    issues: list[str] = []
    if unsupported:
        issues.append("回答中存在无法在证据中定位的关键字段。")
    if unknown_citations:
        issues.append(f"引用了不存在的证据编号：{', '.join(unknown_citations)}。")
    if records and not citation_ids:
        issues.append("回答未提供证据引用。")
    if not text:
        issues.append("回答为空。")

    return {
        "passed": not issues,
        "issues": issues,
        "numeric_claims": numeric_claims,
        "date_claims": date_claims,
        "document_no_claims": document_no_claims,
        "institution_claims": institution_claims,
        "supported_claims": supported,
        "unsupported_claims": unsupported,
        "citations": citation_ids,
        "unknown_citations": unknown_citations,
        "question": question,
    }


def extract_numeric_claims(text: str) -> list[str]:
    """Public helper used by evaluation and regression tests."""

    return [claim["raw"] for claim in _extract_claims(NUMBER_RE, text, _normalize_number_claim)]


def _extract_claims(pattern: re.Pattern[str], text: str, normalizer) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(text):
        raw = match.group(0).strip()
        if not raw or raw.upper().startswith("E"):
            continue
        if pattern is NUMBER_RE and _is_list_marker(text, match.start(), match.end(), raw):
            continue
        normalized = str(normalizer(raw))
        key = (raw, normalized)
        if key in seen:
            continue
        seen.add(key)
        if pattern is NUMBER_RE:
            kind = "numeric"
        elif pattern is DATE_RE:
            kind = "date"
        elif pattern is DOC_NO_RE:
            kind = "document_no"
        else:
            kind = "modality"
        claims.append({"kind": kind, "raw": raw, "normalized": normalized})
    return claims


def _extract_institution_claims(text: str) -> list[dict[str, str]]:
    matches = [*EXACT_INSTITUTION_RE.finditer(text), *GENERIC_INSTITUTION_RE.finditer(text)]
    claims: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in sorted(matches, key=lambda item: item.start()):
        raw = match.group(0).strip()
        normalized = _normalize_for_match(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        claims.append({"kind": "institution", "raw": raw, "normalized": normalized})
    return claims


def _is_list_marker(text: str, start: int, end: int, raw: str) -> bool:
    if _unit_of(_normalize_number_claim(raw)):
        return False
    line_start = text.rfind("\n", 0, start) + 1
    before = text[line_start:start].strip()
    after = text[end : end + 1]
    return not before and after in {".", "、", ")", "）", "．"}


def _claim_supported(raw: str, normalized: str, evidence_text: str, *, kind: str) -> bool:
    if kind == "numeric":
        number = _numeric_value(normalized)
        if number is not None:
            for candidate in NUMBER_RE.findall(evidence_text):
                candidate_normalized = _normalize_number_claim(candidate)
                candidate_number = _numeric_value(candidate_normalized)
                if candidate_number == number and _unit_of(normalized) == _unit_of(candidate_normalized):
                    return True
    return normalized in evidence_text or _normalize_for_match(raw) in evidence_text


def _search_text(item: dict[str, Any]) -> str:
    source = item.get("source") or {}
    metadata = item.get("metadata") or {}
    values = metadata.get("values") if isinstance(metadata.get("values"), list) else []
    value_text = " ".join(str(value) for value in values)
    derived_values = metadata.get("derived_values") if isinstance(metadata.get("derived_values"), list) else []
    derived_text = " ".join(str(value) for value in derived_values)
    fields = [
        item.get("text"),
        item.get("retrieval_text"),
        source.get("title"),
        source.get("issuer"),
        source.get("publish_date"),
        source.get("clause_no"),
        source.get("sheet_name"),
        source.get("table_name"),
        source.get("cell_ref"),
        source.get("source_url"),
        source.get("local_path"),
        metadata.get("metric_name"),
        metadata.get("period"),
        metadata.get("unit"),
        metadata.get("value"),
        value_text,
        derived_text,
    ]
    return _normalize_for_match(" ".join(str(field or "") for field in fields))


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[\s,，]", "", str(value or "")).replace("％", "%").lower()


def _normalize_number_claim(value: str) -> str:
    text = _normalize_for_match(value)
    match = re.search(r"[-+]?\d[\d]*(?:\.\d+)?", text)
    if not match:
        return text
    number = match.group(0)
    try:
        number = format(Decimal(number).normalize(), "f")
    except InvalidOperation:
        pass
    suffix = text[match.end() :]
    return f"{number}{suffix}"


def _normalize_date_claim(value: str) -> str:
    return _normalize_for_match(value).replace("/", "-").replace(".", "-")


def _numeric_value(value: str) -> Decimal | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _unit_of(value: str) -> str:
    return re.sub(r"[-+]?\d+(?:\.\d+)?", "", value)


__all__ = ["extract_numeric_claims", "verify_answer"]
