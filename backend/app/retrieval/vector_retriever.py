from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.indexing.index_reader import KnowledgeBaseReader
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.metadata_filter import (
    attach_filter_diagnostics,
    build_filter_attempts,
)
from app.schemas.chunk_schema import ChunkType, SearchResult
from app.schemas.retrieval_schema import QueryAnalysis
from app.utils.paths import resolve_path


class VectorSearchBackend(Protocol):
    def search(
        self,
        query: str,
        *,
        top_k: int,
        chunk_type: ChunkType | None,
        filters: dict[str, str],
    ) -> list[SearchResult]: ...


class VectorRetriever:
    name = "vector"

    def __init__(self, backend: VectorSearchBackend) -> None:
        self.backend = backend

    def search(self, analysis: QueryAnalysis, top_k: int = 20) -> list[SearchResult]:
        if top_k <= 0:
            return []
        for attempt in build_filter_attempts(analysis.filters):
            results = self.backend.search(
                analysis.question,
                top_k=top_k,
                chunk_type=analysis.preferred_chunk_type,
                filters=attempt.filters,
            )
            if results:
                annotated = [
                    attach_filter_diagnostics(result, attempt) for result in results
                ]
                filtered = apply_entity_filters(analysis, annotated)
                if filtered:
                    return filtered
        return []


class KnowledgeBaseVectorBackend:
    """Adapter for module 2's persisted FAISS vector index."""

    def __init__(self, reader: KnowledgeBaseReader | None = None) -> None:
        self.reader = reader or KnowledgeBaseReader()
        # Module 2's vector metadata may contain the repository-relative model
        # path ``Model/...``. Resolve it at the module-3 adapter boundary so
        # starting the API from ``backend/`` does not silently disable FAISS.
        if not getattr(self.reader, "model_name", None):
            model_path = resolve_path(Path("Model") / "bge-small-zh-v1.5")
            if model_path.exists():
                try:
                    self.reader.model_name = str(model_path)
                except AttributeError:
                    pass

    def search(
        self,
        query: str,
        *,
        top_k: int,
        chunk_type: ChunkType | None,
        filters: dict[str, str],
    ) -> list[SearchResult]:
        return self.reader.vector_search(
            query,
            top_k=top_k,
            chunk_type=chunk_type,
            filters=filters,
            rerank=False,
        )
