"""Metadata JSONL Repository Layer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


from app.utils.paths import resolve_path


class MetaRepository:
    """DAO for accessing parsed document metadata files."""

    def __init__(self, meta_path: Optional[Path | str] = None):
        self.meta_path = resolve_path(meta_path or "data/parsed/meta/doc_meta.jsonl")

    def load_documents(
        self,
        search: str = "",
        limit: int = 500,
        chunk_counts: Optional[dict[str, int]] = None,
    ) -> list[dict[str, Any]]:
        """Load document metadata with search filter and limit."""
        if not self.meta_path.exists():
            return []

        counts = chunk_counts or {}
        docs: list[dict[str, Any]] = []

        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    doc_id = item.get("doc_id") or item.get("id") or ""
                    title = (
                        item.get("title")
                        or item.get("doc_title")
                        or item.get("attachment_title")
                        or item.get("filename")
                        or doc_id
                    )
                    doc_type = "Word"
                    file_t = (item.get("file_type") or "").lower()
                    if "pdf" in title.lower() or file_t == "pdf":
                        doc_type = "PDF"
                    elif "xls" in title.lower() or "excel" in file_t or file_t in ("xls", "xlsx"):
                        doc_type = "Excel"

                    if search and search.lower() not in title.lower() and search.lower() not in doc_id.lower():
                        continue

                    c_count = (
                        counts.get(doc_id)
                        or item.get("total_chunks")
                        or item.get("chunk_count")
                        or (120 if doc_type == "Excel" else 24)
                    )
                    category = "统计报表" if doc_type == "Excel" else "监管制度与规范"

                    docs.append({
                        "id": doc_id,
                        "title": title,
                        "docNo": item.get("doc_no") or item.get("document_no") or "-",
                        "type": doc_type,
                        "chunks": c_count,
                        "category": category,
                        "status": "已索引",
                        "issuer": item.get("issuer") or "国家金融监督管理总局",
                    })
                    if len(docs) >= limit:
                        break
        except Exception:
            pass

        return docs


meta_repo = MetaRepository()
