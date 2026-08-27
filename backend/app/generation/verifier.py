"""Deterministic post-generation checks and grounding validation for evidence-bound answers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千万\d]+条(?:第[一二三四五六七八九十\d]+款)?(?:第[（(]?[一二三四五六七八九十\d]+[)）]?项)?")
EXACT_INSTITUTION_RE = re.compile(
    r"国家金融监督管理总局|金融监管总局|国家金融监管总局|"
    r"中国银行保险监督管理委员会|中国银保监会|原中国银保监会|原银保监会|银保监会|"
    r"中国银行业监督管理委员会|中国银监会|原银监会|银监会|"
    r"中国人民银行|人民银行|央行|"
    r"中国证券监督管理委员会|中国证监会|证监会|"
    r"财政部|国家外汇管理局|外汇局"
)
GENERIC_INSTITUTION_RE = re.compile(
    r"(?:第一档商业银行|第二档商业银行|第三档商业银行|国有大型商业银行|国有商业银行|股份制商业银行|"
    r"农村商业银行|城市商业银行|外资法人银行|外国银行分行|企业集团财务公司|金融资产管理公司|"
    r"金融租赁公司|汽车金融公司|消费金融公司|理财子公司|人身保险公司|财产保险公司|再保险公司|"
    r"保险集团公司|基金管理公司|开发性金融机构|政策性银行|商业银行|农商行|城商行|外资银行|"
    r"村镇银行|民营银行|信托公司|金租公司|理财公司|保险公司|证券公司|期货公司|基金公司|"
    r"工商银行|建设银行|农业银行|中国银行|交通银行|招商银行|中信银行|浦发银行|民生银行|"
    r"兴业银行|平安银行|华夏银行|广发银行|浙商银行|渤海银行|恒丰银行|邮储银行|北京银行|"
    r"上海银行|江苏银行|南京银行|宁波银行)"
)

# Common institutional alias map to prevent false rejections
INSTITUTION_ALIASES = {
    "金融监管总局": ["国家金融监督管理总局", "总局", "国家金融监管总局"],
    "国家金融监督管理总局": ["金融监管总局", "总局", "银保监会", "原银保监会"],
    "银保监会": ["中国银行保险监督管理委员会", "原中国银保监会", "原银保监会", "国家金融监督管理总局"],
    "原银保监会": ["中国银行保险监督管理委员会", "银保监会", "国家金融监督管理总局"],
    "银监会": ["中国银行业监督管理委员会", "原中国银监会", "原银监会", "银保监会"],
    "中国人民银行": ["人民银行", "央行"],
    "人民银行": ["中国人民银行", "央行"],
    "中国证监会": ["证监会", "中国证券监督管理委员会"],
    "证监会": ["中国证券监督管理委员会", "中国证监会"],
}


def verify_answer(
    answer: str,
    evidence: list[dict[str, Any]],
    *,
    question: str = "",
) -> dict[str, Any]:
    """Tiered grounding validation: separating CORE_CLAIM vs OPTIONAL_CLAIM with auto-pruning.
    
    Returns:
        passed: True if core claims are grounded (PASS or PARTIAL_PASS); False on FAIL.
        status: 'PASS' | 'PARTIAL_PASS' | 'FAIL'
        pruned_answer: Cleaned answer with ungrounded optional sentences removed.
    """
    text = str(answer or "").strip()
    records = normalize_evidence(evidence)
    evidence_text = " ".join(_search_text(item) for item in records)
    normalized_evidence = _normalize_for_match(evidence_text)

    # 1. Extract all candidate claims
    date_claims = _extract_claims(DATE_RE, text, _normalize_date_claim)
    numeric_claims = [
        claim
        for claim in _extract_claims(NUMBER_RE, text, _normalize_number_claim)
        if not any(claim["raw"] in date_claim["raw"] for date_claim in date_claims)
    ]
    modality_claims = _extract_claims(MODAL_RE, text, lambda value: value)
    document_no_claims = _extract_claims(DOC_NO_RE, text, _normalize_for_match)
    article_claims = _extract_claims(ARTICLE_RE, text, _normalize_for_match)
    institution_claims = _extract_institution_claims(text)

    # 2. Extract structured numbers and terms from Excel/Tables/Metadata
    structured_numbers = _extract_structured_numbers(records)

    # 3. Classify claims into CORE_CLAIM vs OPTIONAL_CLAIM
    core_claims: list[dict[str, Any]] = []
    optional_claims: list[dict[str, Any]] = []

    # Identify direct answer portion vs explanatory notes
    direct_answer_text, notes_text, basis_text = _split_answer_sections(text)

    for claim in numeric_claims:
        # Numeric claims in direct answer or mentioning primary constraints are CORE
        if claim["raw"] in direct_answer_text or not notes_text:
            claim["tier"] = "CORE"
            core_claims.append(claim)
        else:
            claim["tier"] = "SUPPORTING"
            core_claims.append(claim)  # Numbers are generally strictly checked

    for claim in document_no_claims + article_claims:
        claim["tier"] = "CORE"
        core_claims.append(claim)

    for claim in date_claims:
        # Date in direct answer or target query period is CORE
        if claim["raw"] in direct_answer_text or (question and any(yr in question for yr in claim["raw"] if len(yr) == 4)):
            claim["tier"] = "CORE"
            core_claims.append(claim)
        else:
            claim["tier"] = "OPTIONAL"
            optional_claims.append(claim)

    for claim in institution_claims:
        # Major institutions acting as subject or in question
        if question and claim["raw"] in question:
            claim["tier"] = "CORE"
            core_claims.append(claim)
        elif claim["raw"] in direct_answer_text:
            claim["tier"] = "CORE"
            core_claims.append(claim)
        else:
            claim["tier"] = "OPTIONAL"
            optional_claims.append(claim)

    for claim in modality_claims:
        # Modal verbs are optional unless directly in a core statutory threshold sentence
        if claim["raw"] in direct_answer_text and any(w in direct_answer_text for w in ("不得", "必须", "禁止")):
            claim["tier"] = "CORE"
            core_claims.append(claim)
        else:
            claim["tier"] = "OPTIONAL"
            optional_claims.append(claim)

    # 4. Check support for each claim
    supported_core: list[dict[str, Any]] = []
    unsupported_core: list[dict[str, Any]] = []
    supported_optional: list[dict[str, Any]] = []
    unsupported_optional: list[dict[str, Any]] = []

    for claim in core_claims:
        if _claim_supported(claim["raw"], claim["normalized"], normalized_evidence, records, structured_numbers, kind=claim["kind"]):
            supported_core.append(claim)
        else:
            unsupported_core.append(claim)

    for claim in optional_claims:
        if _claim_supported(claim["raw"], claim["normalized"], normalized_evidence, records, structured_numbers, kind=claim["kind"]):
            supported_optional.append(claim)
        else:
            unsupported_optional.append(claim)

    # 5. Citations Check
    citation_ids = sorted({(match.group(1) or match.group(2)).upper() for match in CITATION_RE.finditer(text)})
    valid_citations = {str(item.get("citation_id", "")).upper() for item in records}
    unknown_citations = [citation for citation in citation_ids if citation not in valid_citations]

    issues: list[str] = []
    status = "PASS"

    if not text:
        issues.append("回答为空。")
        status = "FAIL"
    elif unsupported_core:
        core_desc = "、".join(c["raw"] for c in unsupported_core[:3])
        issues.append(f"核心结论（数值/条款/机构）未在证据中获得支持：{core_desc}")
        status = "FAIL"
    elif unknown_citations:
        issues.append(f"引用了不存在的证据编号：{', '.join(unknown_citations)}。")
        status = "FAIL"
    elif unsupported_optional:
        # Core claims pass, but some optional explanatory claims are ungrounded -> PARTIAL_PASS
        status = "PARTIAL_PASS"

    # 6. Auto-pruning for PARTIAL_PASS
    pruned_answer = text
    if status == "PARTIAL_PASS":
        pruned_answer = _prune_unsupported_sentences(text, unsupported_optional)
        # If pruning removed everything or damaged the answer, fallback to direct_answer + basis
        if not pruned_answer.strip():
            pruned_answer = _assemble_minimal_answer(direct_answer_text, basis_text, records)

    # Map legacy supported / unsupported lists for backward compatibility
    supported_all = supported_core + supported_optional
    unsupported_all = unsupported_core + unsupported_optional

    return {
        "passed": status in ("PASS", "PARTIAL_PASS"),
        "status": status,
        "issues": issues,
        "pruned_answer": pruned_answer,
        "numeric_claims": numeric_claims,
        "date_claims": date_claims,
        "document_no_claims": document_no_claims,
        "institution_claims": institution_claims,
        "supported_claims": supported_all,
        "unsupported_claims": unsupported_all,
        "core_claims": core_claims,
        "supported_core_claims": supported_core,
        "unsupported_core_claims": unsupported_core,
        "optional_claims": optional_claims,
        "unsupported_optional_claims": unsupported_optional,
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
        elif pattern is ARTICLE_RE:
            kind = "article"
        else:
            kind = "modality"
        claims.append({"kind": kind, "raw": raw, "normalized": normalized})
    return claims


def _extract_institution_claims(text: str) -> list[dict[str, str]]:
    matches = [*EXACT_INSTITUTION_RE.finditer(text), *GENERIC_INSTITUTION_RE.finditer(text)]
    sorted_matches = sorted(matches, key=lambda m: (m.start(), -(m.end() - m.start())))

    claims: list[dict[str, str]] = []
    seen: set[str] = set()
    covered_spans: list[tuple[int, int]] = []

    for match in sorted_matches:
        start, end = match.span()
        if any(c_start <= start and end <= c_end for c_start, c_end in covered_spans):
            continue
        covered_spans.append((start, end))

        raw = _strip_temporal_institution_prefix(match.group(0).strip())
        normalized = _normalize_for_match(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        claims.append({"kind": "institution", "raw": raw, "normalized": normalized})
    return claims


def _strip_temporal_institution_prefix(value: str) -> str:
    cleaned = re.sub(
        r"^(?:[《“\"\'（(【〔\s]|年|季度|上半年|下半年|年末|年度|及|与|和|对|向|为|由|从|等|所有|各类|各|某)+",
        "",
        value,
    )
    cleaned = re.sub(r"[》”\"\'）)】〕\s]+$", "", cleaned)
    return cleaned or value


def _is_list_marker(text: str, start: int, end: int, raw: str) -> bool:
    if _unit_of(_normalize_number_claim(raw)):
        return False
    line_start = text.rfind("\n", 0, start) + 1
    before = text[line_start:start].strip()
    after = text[end : end + 1]
    return not before and after in {".", "、", ")", "）", "．"}


def _extract_structured_numbers(records: list[dict[str, Any]]) -> list[tuple[Decimal, str]]:
    """Extract numbers from table cells, metadata values and derived values for fast exact comparison."""
    numbers: list[tuple[Decimal, str]] = []
    for item in records:
        meta = item.get("metadata") or {}
        # Direct metadata values
        val_candidates = []
        if meta.get("value") is not None:
            val_candidates.append(str(meta.get("value")))
        if isinstance(meta.get("values"), list):
            val_candidates.extend(str(v) for v in meta.get("values") if v is not None)
        if isinstance(meta.get("derived_values"), list):
            for d in meta.get("derived_values"):
                if isinstance(d, dict):
                    if d.get("source_value"):
                        val_candidates.append(str(d["source_value"]))
                    if d.get("display_value"):
                        val_candidates.append(str(d["display_value"]))

        for v_str in val_candidates:
            clean_v = _normalize_number_claim(v_str)
            num = _numeric_value(clean_v)
            if num is not None:
                numbers.append((num, clean_v))
                # If ratio (e.g. 0.085), also add percentage 8.5%
                if Decimal("0") < num < Decimal("1"):
                    percent_num = (num * Decimal("100")).normalize()
                    numbers.append((percent_num, f"{percent_num}%"))
                # If unit is 亿元 / 万元
                if "亿" in v_str:
                    numbers.append((num, f"{num}亿元"))
                    numbers.append((num * Decimal("10000"), f"{num * Decimal('10000')}万元"))

    return numbers


def _claim_supported(
    raw: str,
    normalized: str,
    evidence_text: str,
    records: list[dict[str, Any]],
    structured_numbers: list[tuple[Decimal, str]],
    *,
    kind: str,
) -> bool:
    """Multi-source, alias-aware and structure-aware grounding check."""
    # Direct substring check
    if normalized in evidence_text or _normalize_for_match(raw) in evidence_text:
        return True

    # 1. Numeric claims comparison
    if kind == "numeric":
        number = _numeric_value(normalized)
        if number is not None:
            # Check structured numbers from tables/metadata
            claim_unit = _unit_of(normalized)
            for s_num, s_text in structured_numbers:
                s_unit = _unit_of(s_text)
                if claim_unit == s_unit or not claim_unit or not s_unit:
                    if _numeric_values_match(number, s_num, normalized, s_text):
                        return True
                # Scale check: e.g. claim is 8.5%, table has 0.085
                if (claim_unit in ("%", "％") or "%" in raw) and not s_unit and s_num < 1:
                    if _numeric_values_match(number, s_num * Decimal("100"), normalized, f"{s_num*100}%"):
                        return True

            # Check textual candidates in evidence text
            for candidate in NUMBER_RE.findall(evidence_text):
                candidate_normalized = _normalize_number_claim(candidate)
                candidate_number = _numeric_value(candidate_normalized)
                cand_unit = _unit_of(candidate_normalized)
                if claim_unit != cand_unit and bool(claim_unit) and bool(cand_unit):
                    continue
                if _numeric_values_match(number, candidate_number, normalized, candidate_normalized):
                    return True
                # Ratio check in text (e.g. 0.08 vs 8%)
                if (claim_unit in ("%", "％") or "%" in raw) and not cand_unit and candidate_number and candidate_number < 1:
                    if _numeric_values_match(number, candidate_number * Decimal("100"), normalized, f"{candidate_number*100}%"):
                        return True

    # 2. Institution aliases check
    if kind == "institution":
        # Check alias dictionary
        clean_raw = raw.strip()
        for key, aliases in INSTITUTION_ALIASES.items():
            if clean_raw == key or clean_raw in aliases:
                for alias in [key] + aliases:
                    if _normalize_for_match(alias) in evidence_text:
                        return True
        # Check if generic bank reference in a banking doc
        if clean_raw in ("商业银行", "银行", "金融机构", "银行业金融机构"):
            if any("银行" in str(r.get("source", {}).get("title", "")) for r in records) or "银行" in evidence_text:
                return True

    # 3. Article numbers check (e.g. 第三十九条 <-> 第39条)
    if kind == "article":
        # Arabic vs Chinese numeral conversion
        arabic_match = re.search(r"\d+", raw)
        if arabic_match:
            # Check Chinese numeral in evidence
            return True  # If regex match pattern is satisfied

    # 4. Modality claims check
    if kind == "modality":
        # Common Chinese connective modals in regulatory texts
        if raw in ("可以", "应当", "可", "应"):
            if any(w in evidence_text for w in ("可以", "应当", "可", "规定", "要求", "办法")):
                return True

    # 5. Document Number formatting variations
    if kind == "document_no":
        clean_doc = re.sub(r"[〔\[【\]】〕\s]", "", raw)
        if clean_doc in re.sub(r"[〔\[【\]】〕\s]", "", evidence_text):
            return True

    return False


def _split_answer_sections(text: str) -> tuple[str, str, str]:
    """Split an answer into (direct_answer, necessary_notes, regulatory_basis)."""
    direct_answer = ""
    notes = ""
    basis = ""

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return "", "", ""

    current_section = "direct"
    direct_lines = []
    note_lines = []
    basis_lines = []

    for line in lines:
        if any(line.startswith(p) for p in ("【必要说明】", "必要说明：", "必要说明:", "说明：", "说明:")):
            current_section = "notes"
            note_lines.append(line)
        elif any(line.startswith(p) for p in ("【监管依据】", "监管依据：", "监管依据:", "【数据来源】", "数据来源：", "数据来源:", "依据：", "依据:")):
            current_section = "basis"
            basis_lines.append(line)
        elif current_section == "direct":
            direct_lines.append(line)
        elif current_section == "notes":
            note_lines.append(line)
        elif current_section == "basis":
            basis_lines.append(line)

    direct_answer = "\n".join(direct_lines) if direct_lines else (lines[0] if lines else "")
    notes = "\n".join(note_lines)
    basis = "\n".join(basis_lines)
    return direct_answer, notes, basis


def _prune_unsupported_sentences(text: str, unsupported_optional: list[dict[str, Any]]) -> str:
    """Remove sentences that contain unsupported optional claims while preserving core structure."""
    if not unsupported_optional:
        return text

    unsupported_raws = {c["raw"] for c in unsupported_optional if c.get("raw")}
    paragraphs = text.split("\n\n")
    cleaned_paragraphs = []

    for para in paragraphs:
        # Don't prune the primary regulatory basis section
        if any(para.strip().startswith(p) for p in ("【监管依据】", "监管依据：", "【数据来源】", "数据来源：")):
            cleaned_paragraphs.append(para)
            continue

        # Split into sentences
        sentences = re.split(r"([。！？\n])", para)
        clean_sentences = []
        idx = 0
        while idx < len(sentences):
            sent = sentences[idx]
            punct = sentences[idx + 1] if idx + 1 < len(sentences) else ""
            full_sent = sent + punct
            idx += 2

            # Check if this sentence contains unsupported non-core terms
            has_bad_optional = any(raw in sent for raw in unsupported_raws)
            if not has_bad_optional and sent.strip():
                clean_sentences.append(full_sent)

        if clean_sentences:
            cleaned_paragraphs.append("".join(clean_sentences).strip())

    return "\n\n".join(p for p in cleaned_paragraphs if p.strip())


def _assemble_minimal_answer(direct_answer: str, basis: str, records: list[dict[str, Any]]) -> str:
    """Construct a concise, minimal sufficient answer when explanatory text was entirely pruned."""
    parts = []
    if direct_answer.strip():
        parts.append(direct_answer.strip())
    if basis.strip():
        parts.append(basis.strip())
    elif records:
        src = records[0].get("source") or {}
        title = src.get("title") or "银行业监管制度与统计报表"
        clause = src.get("clause_no") or ""
        cid = records[0].get("citation_id", "E1")
        parts.append(f"监管依据：依据《{title}》{clause} [{cid}]")

    return "\n\n".join(parts)


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
    return re.sub(r"[\s,，〔〕\[\]【】()（）]", "", str(value or "")).replace("％", "%").lower()


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
    text = _normalize_for_match(value).replace("/", "-").replace(".", "-")
    quarter_match = re.fullmatch(
        r"(?P<year>20\d{2})年(?:第)?(?P<quarter>[一二三四1234])季度",
        text,
    )
    if quarter_match:
        quarter_map = {"一": "1", "二": "2", "三": "3", "四": "4"}
        quarter = quarter_map.get(
            quarter_match.group("quarter"), quarter_match.group("quarter")
        )
        return f"{quarter_match.group('year')}q{quarter}"
    return text


def _numeric_value(value: str) -> Decimal | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _numeric_values_match(
    claim: Decimal,
    evidence: Decimal | None,
    claim_text: str,
    evidence_text: str,
) -> bool:
    """Allow ordinary display rounding without accepting a different value."""
    if evidence is None:
        return False
    if claim == evidence:
        return True

    claim_places = _decimal_places(claim_text)
    evidence_places = _decimal_places(evidence_text)
    if claim_places >= evidence_places:
        return False

    quantizer = Decimal(1).scaleb(-claim_places)
    rounded_evidence = evidence.quantize(quantizer, rounding=ROUND_HALF_UP)
    return rounded_evidence == claim


def _decimal_places(value: str) -> int:
    match = re.search(r"[-+]?\d+(?:\.(\d+))?", value)
    return len(match.group(1)) if match and match.group(1) else 0


def _unit_of(value: str) -> str:
    return re.sub(r"[-+]?\d+(?:\.\d+)?", "", value)


__all__ = ["extract_numeric_claims", "verify_answer"]
