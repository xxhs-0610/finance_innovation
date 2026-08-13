from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.indexing.text_utils import query_tokens
from app.schemas.chunk_schema import SearchResult, SourceInfo


class KnowledgeBaseReader:
    def __init__(self, db_path: str | Path = "data/processed/metadata.db") -> None:
        self.db_path = Path(db_path)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        chunk_type: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Knowledge DB not found: {self.db_path}. Run scripts/build_kb.py first."
            )
        filters = filters or {}
        safe_query = _prepare_fts_query(query)
        if not safe_query:
            return []

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

        params.append(top_k)
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
            return [_row_to_search_result(row) for row in rows]
        finally:
            con.close()


def _prepare_fts_query(query: str) -> str:
    return " OR ".join(f'"{token}"' for token in query_tokens(query))


def _row_to_search_result(row: sqlite3.Row) -> SearchResult:
    metadata = json.loads(row["metadata_json"] or "{}")
    section_path = json.loads(row["section_path"] or "[]")
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
        score=float(-row["rank_score"]),
        text=row["text"],
        source=source,
        metadata=metadata,
    )
