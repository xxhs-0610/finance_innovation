from __future__ import annotations

from app.indexing.index_reader import KnowledgeBaseReader
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.metadata_filter import (
    attach_filter_diagnostics,
    build_filter_attempts,
)
from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis


class BM25Retriever:
    name = "bm25"

    def __init__(self, reader: KnowledgeBaseReader | None = None) -> None:
        self.reader = reader or KnowledgeBaseReader()

    def search(self, analysis: QueryAnalysis, top_k: int = 20) -> list[SearchResult]:
        if top_k <= 0:
            return []
        search_query = " ".join(analysis.keywords) or analysis.question
        for attempt in build_filter_attempts(analysis.filters):
            results = self.reader.search(
                search_query,
                top_k=top_k,
                chunk_type=analysis.preferred_chunk_type,
                filters=attempt.filters,
                rerank=False,
            )
            if results:
                annotated = [
                    attach_filter_diagnostics(result, attempt) for result in results
                ]
                filtered = apply_entity_filters(analysis, annotated)
                if filtered:
                    return filtered
        return []
