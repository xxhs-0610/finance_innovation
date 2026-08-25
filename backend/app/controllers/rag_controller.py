"""RAG Core API Controller (Retrieval & Question Answering)."""
from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.rag_service import rag_service


class RetrievalRequest(BaseModel):
    """Request payload for Module 3 retrieval endpoint."""

    question: str = Field(..., min_length=1, max_length=2000, description="用户监管问答或报表查询问题")
    top_k: int = Field(default=5, ge=1, le=50, description="召回切片最大数量")


class RetrievalAPIResponse(BaseModel):
    """Response payload for Module 3 retrieval."""

    query: str
    status: str
    analysis: dict[str, Any]
    evidence: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    module4_guidance: dict[str, Any]


class AskRequest(BaseModel):
    """Request payload for end-to-end question answering."""

    question: str = Field(..., description="用户问答输入")
    top_k: Optional[int] = Field(default=5, ge=1, le=50, description="检索切片数")


router = APIRouter(tags=["rag"])


@router.post(
    "/api/v1/retrieve",
    response_model=RetrievalAPIResponse,
    summary="Run Module 3 Hybrid Retrieval",
)
def retrieve_endpoint(request: RetrievalRequest) -> dict[str, Any]:
    """Execute query classification, entity/metadata filtering, multi-channel retrieval, and RRF fusion."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")

    try:
        response = rag_service.retrieve(question, top_k=request.top_k)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "retrieval_unavailable",
                "error_type": type(exc).__name__,
            },
        ) from exc

    return response.to_dict() if hasattr(response, "to_dict") else response


@router.post("/api/v1/ask", summary="Run End-to-End RAG Q&A with Fact Verification")
def api_ask(req: AskRequest) -> dict[str, Any]:
    """Execute complete Module 3 -> Module 4 pipeline."""
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="问题不能为空")

    try:
        return rag_service.ask(q, top_k=req.top_k or 5)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
