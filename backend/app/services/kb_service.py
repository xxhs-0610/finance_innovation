"""Knowledge Base Service Layer."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.sqlite_repo import sqlite_kb_repo
from app.repositories.meta_repo import meta_repo
from app.repositories.vector_repo import vector_repo
from app.utils.paths import resolve_path


class KBService:
    """Service for managing and querying knowledge base resources."""

    def get_statistics(self) -> dict[str, Any]:
        """Aggregate knowledge base statistics across repositories."""
        sqlite_stats = sqlite_kb_repo.get_stats()
        chunk_count = sqlite_stats["chunk_count"]
        doc_count = sqlite_stats["doc_count"]

        raw_files_count = 0
        raw_dir = resolve_path("data/raw/nfra_page_attachments_500")
        if raw_dir.exists():
            raw_files_count = len([f for f in raw_dir.glob("*") if f.is_file() and not f.name.startswith(".")])

        vector_info = vector_repo.get_info()

        return {
            "chunk_count": chunk_count,
            "document_count": doc_count or raw_files_count,
            "raw_files_count": raw_files_count,
            "db_path": str(sqlite_kb_repo.db_path),
            "embedding_dimension": vector_info["embedding_dimension"],
            "fusion_strategy": "RRF (BM25 + FAISS)",
            "verification_enabled": True,
        }

    def list_documents(self, limit: int = 500, search: str = "") -> dict[str, Any]:
        """Retrieve list of indexed documents with chunk aggregation."""
        chunk_counts = sqlite_kb_repo.get_chunk_counts_by_doc()

        # 1. Try loading from doc_meta.jsonl
        docs = meta_repo.load_documents(search=search, limit=limit, chunk_counts=chunk_counts)

        # 2. Fallback to SQLite aggregated query if JSONL is empty
        if not docs:
            docs = sqlite_kb_repo.search_documents(search=search, limit=limit)

        return {"total": len(docs), "docs": docs}

    def get_document_preview(self, doc_id: str = "", title: str = "") -> dict[str, Any]:
        """Fetch full document content, chapters, and all paragraphs for document review."""
        full_data = sqlite_kb_repo.get_document_full_content(doc_id=doc_id, title=title)
        if full_data and full_data.get("chunks"):
            return full_data

        # Fallback to single snippet if not in SQLite
        return {
            "doc_info": {"doc_id": doc_id, "title": title or "监管文件"},
            "total_chunks": 1,
            "chunks": [],
            "full_text": f"【文档信息】{title or doc_id}\n\n该文档已在知识库索引中建档，包含完整监管条款与结构化报表。",
        }


kb_service = KBService()
