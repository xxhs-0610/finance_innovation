"""SQLite Persistence and DAO Layer for Knowledge Base Chunks & Metadata."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.indexing.index_reader import _resolve_default_db_path
from app.utils.paths import resolve_path


class SQLiteKBRepository:
    """DAO for accessing the rebuilt SQLite metadata & full-text database."""

    def __init__(self, db_path: Optional[Path | str] = None):
        if db_path is None:
            self.db_path = resolve_path("data/processed/kb_rebuild/metadata.db")
        else:
            self.db_path = resolve_path(db_path)

    def is_available(self) -> bool:
        return self.db_path.exists()

    def get_stats(self) -> dict[str, int]:
        """Fetch total chunk count and distinct document count."""
        if not self.is_available():
            return {"chunk_count": 0, "doc_count": 0}

        chunk_count = 0
        doc_count = 0
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                cur = con.cursor()
                cur.execute("SELECT COUNT(*) FROM chunks")
                row = cur.fetchone()
                if row:
                    chunk_count = row[0]
                cur.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks")
                row = cur.fetchone()
                if row:
                    doc_count = row[0]
        except Exception:
            pass

        return {"chunk_count": chunk_count, "doc_count": doc_count}

    def get_chunk_counts_by_doc(self) -> dict[str, int]:
        """Fetch chunk counts grouped by doc_id."""
        if not self.is_available():
            return {}

        counts: dict[str, int] = {}
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                cur = con.cursor()
                cur.execute("SELECT doc_id, COUNT(*) FROM chunks GROUP BY doc_id")
                for r in cur.fetchall():
                    if r[0]:
                        counts[str(r[0])] = r[1]
        except Exception:
            pass
        return counts

    def search_documents(self, search: str = "", limit: int = 500) -> list[dict[str, Any]]:
        """Query documents and aggregate chunk stats directly from SQLite."""
        if not self.is_available():
            return []

        docs: list[dict[str, Any]] = []
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                cur = con.cursor()
                query = "SELECT doc_id, title, issuer, chunk_type, COUNT(*) FROM chunks"
                params: list[Any] = []
                if search:
                    query += " WHERE title LIKE ? OR doc_id LIKE ?"
                    params.extend([f"%{search}%", f"%{search}%"])
                query += " GROUP BY doc_id, title ORDER BY COUNT(*) DESC LIMIT ?"
                params.append(limit)

                cur.execute(query, params)
                for r in cur.fetchall():
                    doc_id, title, issuer, chunk_type, c_cnt = r
                    doc_type = "Excel" if chunk_type == "table" else "Word"
                    if "pdf" in str(title).lower():
                        doc_type = "PDF"
                    docs.append({
                        "id": doc_id or "DOC",
                        "title": title or "监管文件",
                        "docNo": "-",
                        "type": doc_type,
                        "chunks": c_cnt,
                        "category": "银行业监管与报表",
                        "status": "已索引",
                        "issuer": issuer or "金融监管总局",
                    })
        except Exception:
            pass

    def get_document_full_content(self, doc_id: str, title: str = "") -> dict[str, Any]:
        """Fetch all chunks and metadata for a complete document view."""
        if not self.is_available():
            return {}

        chunks: list[dict[str, Any]] = []
        doc_info: dict[str, Any] = {}

        try:
            with sqlite3.connect(str(self.db_path)) as con:
                con.row_factory = sqlite3.Row
                cur = con.cursor()

                # Query by doc_id first, then fallback to title
                if doc_id and doc_id != "DOC":
                    cur.execute(
                        "SELECT * FROM chunks WHERE doc_id = ? ORDER BY rowid ASC",
                        (doc_id,),
                    )
                    rows = cur.fetchall()
                else:
                    rows = []

                if not rows and title:
                    cur.execute(
                        "SELECT * FROM chunks WHERE title LIKE ? ORDER BY rowid ASC",
                        (f"%{title}%",),
                    )
                    rows = cur.fetchall()

                for row in rows:
                    r_dict = dict(row)
                    if not doc_info:
                        doc_info = {
                            "doc_id": r_dict.get("doc_id"),
                            "title": r_dict.get("title"),
                            "issuer": r_dict.get("issuer"),
                            "publish_date": r_dict.get("publish_date"),
                            "local_path": r_dict.get("local_path"),
                            "chunk_type": r_dict.get("chunk_type"),
                        }
                    chunks.append({
                        "chunk_id": r_dict.get("chunk_id"),
                        "clause_no": r_dict.get("clause_no"),
                        "section_path": r_dict.get("section_path"),
                        "text": r_dict.get("text"),
                        "sheet_name": r_dict.get("sheet_name"),
                        "table_name": r_dict.get("table_name"),
                    })
        except Exception:
            pass

        full_text = "\n\n".join([c["text"] for c in chunks if c.get("text")])

        return {
            "doc_info": doc_info,
            "total_chunks": len(chunks),
            "chunks": chunks,
            "full_text": full_text,
        }


# Repository singleton instance
sqlite_kb_repo = SQLiteKBRepository()
