from __future__ import annotations

import re

from app.indexing.index_reader import KnowledgeBaseReader
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.metadata_filter import (
    attach_filter_diagnostics,
    build_filter_attempts,
)
from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis, QueryType
from app.retrieval.table_evidence import normalize_period, table_matches_period


NORMALIZE_RE = re.compile(r"[\s，。！？?；;：:、（）()【】\[\]<>《》_-]+")
QUARTER_RE = re.compile(r"((?:19|20)\d{2})年?第?([一二三四1234])季度")
Q_RE = re.compile(r"((?:19|20)\d{2})[Qq]([1-4])")
QUARTER_MAP = {"一": "1", "二": "2", "三": "3", "四": "4"}


class TableRetriever:
    name = "table"
    supported_query_types: frozenset[QueryType] = frozenset(
        {"table_lookup", "cross_document"}
    )

    def __init__(self, reader: KnowledgeBaseReader | None = None) -> None:
        self.reader = reader or KnowledgeBaseReader()

    def search(self, analysis: QueryAnalysis, top_k: int = 20) -> list[SearchResult]:
        if top_k <= 0:
            return []
        search_query = " ".join(analysis.keywords) or analysis.question
        candidate_top_k = max(top_k * 3, 50)
        for attempt in build_filter_attempts(analysis.filters):
            results = self.reader.search(
                search_query,
                top_k=candidate_top_k,
                chunk_type="table",
                filters=attempt.filters,
                rerank=False,
            )
            if results:
                annotated = [
                    attach_filter_diagnostics(result, attempt) for result in results
                ]
                filtered = apply_entity_filters(analysis, annotated)
                if filtered:
                    return rerank_table_candidates(analysis, filtered)[:top_k]
        return []


def rerank_table_candidates(
    analysis: QueryAnalysis, candidates: list[SearchResult]
) -> list[SearchResult]:
    reranked: list[tuple[int, int, SearchResult]] = []
    for native_rank, candidate in enumerate(candidates, start=1):
        match_score, matched_fields = _table_match_score(analysis, candidate)
        metadata = dict(candidate.metadata)
        metadata["table_matching"] = {
            "match_score": match_score,
            "matched_fields": matched_fields,
            "native_score": candidate.score,
            "native_rank": native_rank,
        }
        result = SearchResult(
            chunk_id=candidate.chunk_id,
            chunk_type=candidate.chunk_type,
            score=float(match_score) + 1.0 / (60 + native_rank),
            text=candidate.text,
            source=candidate.source,
            metadata=metadata,
        )
        reranked.append((match_score, native_rank, result))

    reranked.sort(key=lambda item: (-item[0], item[1], item[2].chunk_id))
    return [item[2] for item in reranked]


def _table_match_score(
    analysis: QueryAnalysis, candidate: SearchResult
) -> tuple[int, list[str]]:
    score = 0
    matched_fields: list[str] = []
    metadata = candidate.metadata

    query_metric = _normalize(analysis.entities.get("metric", ""))
    candidate_metric = _normalize(
        str(metadata.get("metric_name") or metadata.get("row_header") or "")
    )
    if query_metric and candidate_metric:
        if query_metric == candidate_metric:
            score += 8
            matched_fields.append("metric_exact")
        elif query_metric in candidate_metric or candidate_metric in query_metric:
            score += 3
            matched_fields.append("metric_partial")

    query_period = analysis.entities.get("normalized_period") or analysis.entities.get(
        "period", ""
    )
    candidate_periods = (
        str(metadata.get("period") or ""),
        str(metadata.get("col_header") or ""),
    )
    normalized_query_period = _normalize_period(query_period)
    if normalized_query_period and (
        any(
            _normalize_period(value) == normalized_query_period
            for value in candidate_periods
            if value
        )
        or table_matches_period(candidate, normalized_query_period)
    ):
        score += 6
        matched_fields.append("period_exact")

    query_document = _normalize(analysis.entities.get("document", ""))
    source_title = _normalize(candidate.source.title)
    if query_document and source_title:
        if query_document == source_title:
            score += 5
            matched_fields.append("document_exact")
        elif query_document in source_title or source_title in query_document:
            score += 2
            matched_fields.append("document_partial")

    query_value = _normalize(analysis.entities.get("value", ""))
    candidate_values = _table_values(metadata)
    if query_value and query_value in candidate_values:
        score += 2
        matched_fields.append("value_exact")

    return score, matched_fields


def _normalize(value: str) -> str:
    return NORMALIZE_RE.sub("", value or "").lower()


def _normalize_period(value: str) -> str:
    return normalize_period(value)


def _table_values(metadata: dict) -> set[str]:
    values = {_normalize(str(metadata.get("value") or ""))}
    for item in metadata.get("values") or []:
        if isinstance(item, dict):
            values.add(_normalize(str(item.get("value") or "")))
            values.add(_normalize(str(item.get("value_numeric") or "")))
    values.discard("")
    return values
