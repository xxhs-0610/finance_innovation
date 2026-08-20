from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.indexing.query_analyzer import analyze_query
from app.indexing.reranker import rerank_results
from app.indexing.text_utils import query_tokens
from app.indexing.vector_index import VectorIndexSearcher
from app.schemas.chunk_schema import SearchResult, SourceInfo


def _resolve_default_db_path(requested: str | Path) -> Path:
    p = Path(requested)
    if p.exists():
        return p
    for candidate in [
        Path("data/processed/kb_rebuild/metadata.db"),
        Path("data/processed/kb_full_validation/metadata.db"),
        Path("data/processed/metadata.db"),
        Path("data/processed/kb/metadata.db"),
    ]:
        if candidate.exists():
            return candidate
    return p


class KnowledgeBaseReader:
    def __init__(
        self,
        db_path: str | Path = "data/processed/kb_rebuild/metadata.db",
        *,
        vector_index_dir: str | Path | None = None,
        embedding_backend: str | None = None,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self.db_path = _resolve_default_db_path(db_path)
        self.vector_index_dir = Path(vector_index_dir) if vector_index_dir else _infer_vector_index_dir(self.db_path)
        self.embedding_backend = embedding_backend
        self.model_name = model_name
        self.device = device

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int | None = None,
        chunk_type: str | None = None,
        filters: dict[str, str] | None = None,
        rerank: bool = True,
    ) -> list[SearchResult]:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Knowledge DB not found: {self.db_path}. Run scripts/build_kb.py first."
            )
        filters = filters or {}
        analysis = analyze_query(query)
        safe_query = _prepare_fts_query(analysis.search_text)
        if not safe_query:
            return []
        limit = max(top_k, candidate_k or (max(top_k * 20, 50) if rerank else top_k))

        where = ["chunk_fts MATCH ?"]
        params: list[Any] = [safe_query]
        if chunk_type:
            where.append("c.chunk_type = ?")
            params.append(chunk_type)
        for key in ("doc_id", "title", "issuer", "publish_date"):
            value = filters.get(key)
            if value:
                where.append(f"c.{key} LIKE ?")
                params.append(f"%{value}%")

        params.append(limit)
        sql = f"""
            SELECT
                c.*,
                bm25(chunk_fts) AS rank_score
            FROM chunk_fts
            JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id
            WHERE {" AND ".join(where)}
            ORDER BY rank_score
            LIMIT ?
        """

        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(sql, params).fetchall()
            results = [_row_to_search_result(row) for row in rows]
            if rerank:
                results = rerank_results(query, results, analysis=analysis)
            return results[:top_k]
        finally:
            con.close()

    def vector_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int | None = None,
        chunk_type: str | None = None,
        filters: dict[str, str] | None = None,
        rerank: bool = True,
        index_dir: str | Path | None = None,
        embedding_backend: str | None = None,
        model_name: str | None = None,
    ) -> list[SearchResult]:
        self._ensure_db_exists()
        candidate_limit = max(top_k, candidate_k or max(top_k * 20, 50))
        searcher = VectorIndexSearcher(
            index_dir or self.vector_index_dir,
            embedding_backend=embedding_backend or self.embedding_backend,
            model_name=model_name or self.model_name,
            device=self.device,
        )
        hits = searcher.search(
            query,
            top_k=candidate_limit,
            candidate_k=candidate_limit,
            chunk_type=chunk_type,
        )
        if not hits:
            return []

        score_by_id = {hit.chunk_id: hit.score for hit in hits}
        rank_by_id = {hit.chunk_id: rank for rank, hit in enumerate(hits, start=1)}
        results = self._fetch_results_by_chunk_ids(
            [hit.chunk_id for hit in hits],
            score_by_id=score_by_id,
            chunk_type=chunk_type,
            filters=filters,
        )
        for result in results:
            _add_retrieval_metadata(
                result,
                vector_score=score_by_id.get(result.chunk_id),
                vector_rank=rank_by_id.get(result.chunk_id),
            )
        if rerank:
            results = rerank_results(query, results, analysis=analyze_query(query))
        return results[:top_k]

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int | None = None,
        chunk_type: str | None = None,
        filters: dict[str, str] | None = None,
        rerank: bool = True,
        index_dir: str | Path | None = None,
        embedding_backend: str | None = None,
        model_name: str | None = None,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        candidate_limit = max(top_k, candidate_k or max(top_k * 20, 50))
        bm25_results = self.search(
            query,
            top_k=candidate_limit,
            candidate_k=candidate_limit,
            chunk_type=chunk_type,
            filters=filters,
            rerank=False,
        )
        vector_results = self.vector_search(
            query,
            top_k=candidate_limit,
            candidate_k=candidate_limit,
            chunk_type=chunk_type,
            filters=filters,
            rerank=False,
            index_dir=index_dir,
            embedding_backend=embedding_backend,
            model_name=model_name,
        )
        fused = _fuse_results(
            bm25_results,
            vector_results,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
            rrf_k=rrf_k,
        )
        if rerank:
            fused = rerank_results(query, fused, analysis=analyze_query(query))
        return fused[:top_k]

    def _ensure_db_exists(self) -> None:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Knowledge DB not found: {self.db_path}. Run scripts/build_kb.py first."
            )

    def _fetch_results_by_chunk_ids(
        self,
        chunk_ids: list[str],
        *,
        score_by_id: dict[str, float],
        chunk_type: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        if not chunk_ids:
            return []
        filters = filters or {}
        placeholders = ",".join("?" for _ in chunk_ids)
        where = [f"chunk_id IN ({placeholders})"]
        params: list[Any] = list(chunk_ids)
        if chunk_type:
            where.append("chunk_type = ?")
            params.append(chunk_type)
        for key in ("doc_id", "title", "issuer", "publish_date"):
            value = filters.get(key)
            if value:
                where.append(f"{key} LIKE ?")
                params.append(f"%{value}%")

        sql = f"""
            SELECT *
            FROM chunks
            WHERE {" AND ".join(where)}
        """
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(sql, params).fetchall()
            result_by_id = {
                row["chunk_id"]: _row_to_search_result(row, score=score_by_id.get(row["chunk_id"], 0.0))
                for row in rows
            }
            return [result_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in result_by_id]
        finally:
            con.close()


def _prepare_fts_query(query: str) -> str:
    return " OR ".join(f'"{token}"' for token in query_tokens(query))


def _row_to_search_result(row: sqlite3.Row, *, score: float | None = None) -> SearchResult:
    metadata = json.loads(row["metadata_json"] or "{}")
    section_path = json.loads(row["section_path"] or "[]")
    if score is None:
        score = float(-row["rank_score"]) if "rank_score" in row.keys() else 0.0
    source = SourceInfo(
        doc_id=row["doc_id"],
        title=row["title"] or "",
        issuer=row["issuer"] or "",
        publish_date=row["publish_date"] or "",
        source_url=row["source_url"] or "",
        local_path=row["local_path"] or "",
        section_path=section_path,
        clause_no=row["clause_no"] or "",
        sheet_name=row["sheet_name"] or "",
        table_name=row["table_name"] or "",
        cell_ref=(metadata.get("cell_ref") or ""),
    )
    return SearchResult(
        chunk_id=row["chunk_id"],
        chunk_type=row["chunk_type"],
        score=float(score),
        text=row["text"],
        source=source,
        metadata=metadata,
    )


def _fuse_results(
    bm25_results: list[SearchResult],
    vector_results: list[SearchResult],
    *,
    bm25_weight: float,
    vector_weight: float,
    rrf_k: int,
) -> list[SearchResult]:
    fused: dict[str, SearchResult] = {}
    scores: dict[str, float] = {}

    for rank, result in enumerate(bm25_results, start=1):
        fused[result.chunk_id] = result
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + bm25_weight / (rrf_k + rank)
        _add_retrieval_metadata(result, bm25_score=result.score, bm25_rank=rank)

    for rank, result in enumerate(vector_results, start=1):
        if result.chunk_id not in fused:
            fused[result.chunk_id] = result
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + vector_weight / (rrf_k + rank)
        _add_retrieval_metadata(
            fused[result.chunk_id],
            vector_score=result.score,
            vector_rank=rank,
        )

    for chunk_id, result in fused.items():
        fusion_score = scores.get(chunk_id, 0.0) * 1000
        result.score = fusion_score
        _add_retrieval_metadata(result, fusion_score=fusion_score)

    return sorted(fused.values(), key=lambda item: item.score, reverse=True)


def _add_retrieval_metadata(
    result: SearchResult,
    *,
    bm25_score: float | None = None,
    bm25_rank: int | None = None,
    vector_score: float | None = None,
    vector_rank: int | None = None,
    fusion_score: float | None = None,
) -> None:
    retrieval = dict(result.metadata.get("_retrieval") or {})
    if bm25_score is not None:
        retrieval["bm25_score"] = bm25_score
    if bm25_rank is not None:
        retrieval["bm25_rank"] = bm25_rank
    if vector_score is not None:
        retrieval["vector_score"] = vector_score
    if vector_rank is not None:
        retrieval["vector_rank"] = vector_rank
    if fusion_score is not None:
        retrieval["fusion_score"] = fusion_score
    result.metadata["_retrieval"] = retrieval


def _infer_vector_index_dir(db_path: Path) -> Path:
    parent = db_path.parent
    if parent.name and parent.name not in {"processed", "data"}:
        return Path("indexes") / parent.name
    return Path("indexes")
