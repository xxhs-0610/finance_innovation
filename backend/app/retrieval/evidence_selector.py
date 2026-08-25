from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis
from app.retrieval.table_evidence import (
    has_usable_table_value,
    narrow_table_evidence,
)


SPACE_RE = re.compile(r"\s+")
TEXT_NORMALIZE_RE = re.compile(r"[^0-9A-Za-z%％\u4e00-\u9fff]+")
NUMBER_WITH_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:[%％]|亿元|万元|元|个|家|倍|日|天|年)"
)


def select_evidence(
    candidates: Iterable[SearchResult],
    top_k: int = 5,
    analysis: QueryAnalysis | None = None,
) -> list[SearchResult]:
    if top_k <= 0:
        return []

    deduplicated: list[SearchResult] = []
    seen_chunk_ids: set[str] = set()
    seen_doc_text: set[tuple[str, str]] = set()
    for candidate in candidates:
        if analysis:
            candidate = narrow_table_evidence(candidate, analysis)
        normalized_text = SPACE_RE.sub("", candidate.text)
        doc_text_key = (candidate.source.doc_id, normalized_text)
        if candidate.chunk_id in seen_chunk_ids or doc_text_key in seen_doc_text:
            continue
        seen_chunk_ids.add(candidate.chunk_id)
        seen_doc_text.add(doc_text_key)
        deduplicated.append(attach_evidence_quality(candidate))

    if analysis and analysis.query_type == "table_lookup":
        sufficient = next(
            (
                candidate
                for candidate in deduplicated
                if _is_sufficient_table_evidence(candidate, analysis)
            ),
            None,
        )
        if sufficient:
            return [sufficient]

    if analysis and analysis.query_type == "clause_threshold":
        sufficient = next(
            (
                candidate
                for candidate in deduplicated
                if _is_sufficient_threshold_evidence(candidate, analysis)
            ),
            None,
        )
        if sufficient:
            return [sufficient]

    if analysis and analysis.query_type == "cross_document":
        return _select_document_diversity(deduplicated, top_k)
    return deduplicated[:top_k]


def attach_evidence_quality(candidate: SearchResult) -> SearchResult:
    source = candidate.source
    missing_fields: list[str] = []
    if not source.doc_id:
        missing_fields.append("source.doc_id")
    if not source.title:
        missing_fields.append("source.title")
    if not (source.source_url or source.local_path):
        missing_fields.append("source.source_url_or_local_path")

    if candidate.chunk_type == "clause":
        if not (source.clause_no or source.section_path):
            missing_fields.append("source.clause_no_or_section_path")
    else:
        if not source.table_name:
            missing_fields.append("source.table_name")
        if not source.cell_ref:
            missing_fields.append("source.cell_ref")
        for key in ("metric_name", "period"):
            if not candidate.metadata.get(key):
                missing_fields.append(f"metadata.{key}")
        if not has_usable_table_value(candidate.metadata):
            missing_fields.append("metadata.value_or_values")

    metadata = dict(candidate.metadata)
    metadata["evidence_quality"] = {
        "complete": not missing_fields,
        "missing_fields": missing_fields,
    }
    return SearchResult(
        chunk_id=candidate.chunk_id,
        chunk_type=candidate.chunk_type,
        score=candidate.score,
        text=candidate.text,
        source=candidate.source,
        metadata=metadata,
    )


def _is_sufficient_table_evidence(
    candidate: SearchResult, analysis: QueryAnalysis
) -> bool:
    if candidate.chunk_type != "table":
        return False
    quality = candidate.metadata.get("evidence_quality", {})
    if (
        not quality.get("complete")
        or not has_usable_table_value(candidate.metadata)
        or candidate.metadata.get("table_cell_selection", {}).get("status")
        == "ambiguous_dimension"
    ):
        return False

    matched_fields = set(
        candidate.metadata.get("table_matching", {}).get("matched_fields", [])
    )
    if analysis.entities.get("metric") and "metric_exact" not in matched_fields:
        return False
    if analysis.entities.get("normalized_period") and "period_exact" not in matched_fields:
        return False
    return bool(analysis.entities.get("metric"))


def _is_sufficient_threshold_evidence(
    candidate: SearchResult, analysis: QueryAnalysis
) -> bool:
    if candidate.chunk_type != "clause":
        return False
    quality = candidate.metadata.get("evidence_quality", {})
    metric = _normalize_text(analysis.entities.get("metric", ""))
    text = _normalize_text(candidate.text)
    return bool(
        quality.get("complete")
        and metric
        and metric in text
        and NUMBER_WITH_UNIT_RE.search(candidate.text)
    )


def _select_document_diversity(
    candidates: list[SearchResult], top_k: int
) -> list[SearchResult]:
    selected: list[SearchResult] = []
    selected_chunk_ids: set[str] = set()
    seen_doc_ids: set[str] = set()
    for candidate in candidates:
        doc_id = candidate.source.doc_id
        if doc_id and doc_id not in seen_doc_ids:
            selected.append(candidate)
            selected_chunk_ids.add(candidate.chunk_id)
            seen_doc_ids.add(doc_id)
            if len(selected) >= top_k:
                return selected
    for candidate in candidates:
        if candidate.chunk_id not in selected_chunk_ids:
            selected.append(candidate)
            if len(selected) >= top_k:
                break
    return selected


def _normalize_text(value: str) -> str:
    return TEXT_NORMALIZE_RE.sub("", value or "").lower()
