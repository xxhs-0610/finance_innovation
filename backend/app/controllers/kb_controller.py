"""Knowledge Base Management API Controller.
Exposes statistics, document catalog, and index diagnostics endpoints.
"""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter

from app.services.kb_service import kb_service
from app.utils.logger import get_logger

logger = get_logger("app.controllers.kb")
router = APIRouter(tags=["kb"])


@router.get("/api/v1/stats", summary="Knowledge base overview statistics")
def get_stats() -> dict[str, Any]:
    """Return counts of chunks, indexed documents, raw files, and index configuration."""
    logger.info("[KBController] 接收知识库概览统计请求 GET /api/v1/stats")
    stats = kb_service.get_statistics()
    logger.info(
        f"[KBController] 统计概览返回: {stats.get('chunk_count', 0)} Chunks, {stats.get('document_count', 0)} Docs, {stats.get('embedding_dimension')} 维"
    )
    return stats


@router.get("/api/v1/kb/indexes", summary="Detailed index status and file inventory")
def get_indexes_status() -> dict[str, Any]:
    """Return dense (FAISS) & sparse (BM25) index metrics, file sizes, and chunk breakdown."""
    logger.info("[KBController] 接收索引资产全量清单请求 GET /api/v1/kb/indexes")
    return kb_service.get_indexes_overview()


@router.post("/api/v1/kb/indexes/verify", summary="Run health check and integrity verification on indexes")
def verify_indexes() -> dict[str, Any]:
    """Execute live verification on FAISS index readability, embedding matrices, and mappings."""
    logger.info("[KBController] 触发全量双路索引健康体检 POST /api/v1/kb/indexes/verify")
    result = kb_service.verify_indexes()
    logger.info(
        f"[KBController] 索引健康体检完成: passed={result.get('passed')}, latency={result.get('latency_ms')}ms"
    )
    return result


@router.get("/api/v1/kb/docs", summary="Paginated list of indexed documents")
def get_kb_docs(limit: int = 500, search: str = "") -> dict[str, Any]:
    """Return document catalog with chunk counts, document numbers, and categories."""
    logger.debug(f"[KBController] 查询文档列表: limit={limit}, search='{search}'")
    return kb_service.list_documents(limit=limit, search=search)


@router.get("/api/v1/kb/doc/preview", summary="Get full document text and paragraphs by doc_id or title")
def get_doc_preview(doc_id: str = "", title: str = "") -> dict[str, Any]:
    """Return complete structured document context, clauses, and metadata."""
    logger.info(f"[KBController] 获取文档详情与切片预览: doc_id='{doc_id}', title='{title}'")
    return kb_service.get_document_preview(doc_id=doc_id, title=title)


@router.get("/api/v1/kb/doc/{doc_id}", summary="Get document details and all paragraphs by doc_id")
def get_doc_by_id(doc_id: str) -> dict[str, Any]:
    """Return complete document text for a specific doc_id."""
    logger.info(f"[KBController] 获取文档详情: doc_id='{doc_id}'")
    return kb_service.get_document_preview(doc_id=doc_id)
