from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from app.indexing.query_analyzer import QueryAnalysis, analyze_query
from app.schemas.chunk_schema import SearchResult


NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*%?|\d+(?:\.\d+)?")
TITLE_LIKE_RE = re.compile(r"^(附件\d*|[（(].+[）)]|第[一二三四五六七八九十百]+[章节条款]?|[一二三四五六七八九十]+、.+)$")


def rerank_results(
    query: str,
    results: Iterable[SearchResult],
    *,
    analysis: QueryAnalysis | None = None,
) -> list[SearchResult]:
    analysis = analysis or analyze_query(query)
    scored: list[tuple[float, SearchResult]] = []
    for result in results:
        score = _score_result(result, analysis)
        result.score = score
        scored.append((score, result))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored]


def _score_result(result: SearchResult, analysis: QueryAnalysis) -> float:
    score = result.score
    text = result.text or ""
    haystack = _haystack(result)
    metadata = result.metadata or {}

    if analysis.query_type == "clause":
        score += 35 if result.chunk_type == "clause" else -18
    elif analysis.query_type == "table":
        score += 35 if result.chunk_type == "table" else -12

    score += _term_overlap_bonus(haystack, analysis.important_terms)
    score += _intent_bonus(text, haystack, analysis)
    score += _source_alignment_bonus(result, analysis)

    if result.chunk_type == "clause":
        score += _clause_quality_bonus(text)
    elif result.chunk_type == "table":
        score += _table_quality_bonus(metadata, analysis)

    return score


def _term_overlap_bonus(haystack: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    matched = 0
    bonus = 0.0
    for term in terms:
        if term and term in haystack:
            matched += 1
            bonus += 4.0 if len(term) <= 2 else 7.0
    if matched >= 3:
        bonus += 10.0
    return min(bonus, 55.0)


def _intent_bonus(text: str, haystack: str, analysis: QueryAnalysis) -> float:
    score = 0.0
    if "threshold" in analysis.intents:
        if any(item in haystack for item in ("不得低于", "不低于", "不得高于", "不得超过", "最低", "至少")):
            score += 24
        if NUMBER_RE.search(text):
            score += 12
    if "list" in analysis.intents or "explain" in analysis.intents:
        if any(item in haystack for item in ("包括", "至少", "以下", "如下", "分为", "分级", "机制", "流程", "步骤", "方面")):
            score += 24
        if text.endswith("：") or text.endswith(":"):
            score += 5
    if "value" in analysis.intents and NUMBER_RE.search(text):
        score += 10
    return score


def _source_alignment_bonus(result: SearchResult, analysis: QueryAnalysis) -> float:
    score = 0.0
    title = result.source.title or ""
    text = result.text or ""
    metadata = result.metadata or {}
    period = str(metadata.get("period") or "")
    metric_name = str(metadata.get("metric_name") or "")
    row_header = str(metadata.get("row_header") or "")

    for year in analysis.years:
        if year and (year in period or year in title or year in text):
            score += 18
        elif analysis.query_type == "table":
            score -= 8

    for term in analysis.important_terms:
        if _normalize_metric(metric_name) == _normalize_metric(term):
            score += 45
        elif _normalize_metric(row_header) == _normalize_metric(term):
            score += 35
        elif term in metric_name or term in row_header:
            score += 16

    query = analysis.original_query
    if "商业银行" in query and "保险公司" in title:
        score -= 12
    if "保险" in query and "商业银行" in title and "商业银行" not in query:
        score -= 12
    return score


def _clause_quality_bonus(text: str) -> float:
    length = len(text.strip())
    if length <= 4:
        return -60.0
    if length <= 10:
        return -35.0
    if length <= 18 and TITLE_LIKE_RE.match(text.strip()):
        return -25.0
    if length >= 35:
        return 8.0
    return 0.0


def _table_quality_bonus(metadata: dict, analysis: QueryAnalysis) -> float:
    score = 0.0
    record_type = str(metadata.get("record_type") or "")
    values = metadata.get("values")
    metric_name = str(metadata.get("metric_name") or "")
    row_header = str(metadata.get("row_header") or "")
    table_name = str(metadata.get("table_name") or "")

    if record_type == "table_row":
        score += 12
    elif record_type == "table_summary":
        score += -18 if analysis.query_type == "table" else -25

    if _is_note_like(metric_name) or _is_note_like(row_header):
        score -= 55
    if "主要监管指标" in analysis.search_text and "主要监管指标" in table_name:
        score += 14

    if isinstance(values, list) and values:
        score += 12
        if any(_value_has_number(item) for item in values if isinstance(item, dict)):
            score += 8
        elif "value" in analysis.intents:
            score -= 18
    return score


def _value_has_number(item: dict[str, Any]) -> bool:
    value = str(item.get("value") or "")
    numeric = str(item.get("value_numeric") or "")
    return bool(numeric or NUMBER_RE.search(value))


def _normalize_metric(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value)


def _is_note_like(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("注", "备注", "说明")):
        return True
    note_markers = (
        "不含外国银行分行",
        "同时废止",
        "不直接可比",
        "相关指标",
        "起施行",
        "计算的数据结果",
    )
    return any(marker in text for marker in note_markers)


def _haystack(result: SearchResult) -> str:
    source = result.source
    parts = [
        result.text,
        source.title,
        source.issuer,
        source.publish_date,
        " ".join(source.section_path),
        source.clause_no,
        source.sheet_name,
        source.table_name,
        source.cell_ref,
        json.dumps(result.metadata or {}, ensure_ascii=False),
    ]
    return " ".join(part for part in parts if part)
