"""Health Check API Controller."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health status")
@router.get("/api/v1/health", summary="API v1 health status")
def get_health() -> dict[str, Any]:
    """Return health check metadata for the RegTrust-RAG engine."""
    return {
        "status": "healthy",
        "service": "RegTrust-RAG Engine",
        "version": "2.1.0",
        "pipeline": "Module 1-4 Connected",
    }
