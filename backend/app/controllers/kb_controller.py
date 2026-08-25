"""Knowledge Base Management API Controller."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter

from app.services.kb_service import kb_service

router = APIRouter(tags=["kb"])


@router.get("/api/v1/stats", summary="Knowledge base overview statistics")
def get_stats() -> dict[str, Any]:
    """Return counts of chunks, indexed documents, raw files, and vector configuration."""
    return kb_service.get_statistics()


@router.get("/api/v1/kb/docs", summary="Paginated list of indexed documents")
def get_kb_docs(limit: int = 500, search: str = "") -> dict[str, Any]:
    """Return document catalog with chunk counts, document numbers, and categories."""
    return kb_service.list_documents(limit=limit, search=search)


@router.get("/api/v1/kb/doc/preview", summary="Get full document text and paragraphs by doc_id or title")
def get_doc_preview(doc_id: str = "", title: str = "") -> dict[str, Any]:
    """Return complete structured document context, clauses, and metadata."""
    return kb_service.get_document_preview(doc_id=doc_id, title=title)


@router.get("/api/v1/kb/doc/{doc_id}", summary="Get document details and all paragraphs by doc_id")
def get_doc_by_id(doc_id: str) -> dict[str, Any]:
    """Return complete document text for a specific doc_id."""
    return kb_service.get_document_preview(doc_id=doc_id)
