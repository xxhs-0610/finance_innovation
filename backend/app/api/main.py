"""RegTrust-RAG FastAPI REST Backend Application.
Layered architecture router container and endpoint registry.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Optional

# Compatibility patch for Starlette router when on_startup / on_shutdown is not accepted
import starlette.routing

_orig_router_init = starlette.routing.Router.__init__
def _patched_router_init(self, *args, on_startup=None, on_shutdown=None, **kwargs):
    self.on_startup = on_startup or []
    self.on_shutdown = on_shutdown or []
    try:
        return _orig_router_init(self, *args, **kwargs)
    except TypeError:
        return _orig_router_init(self, *args, on_startup=on_startup, on_shutdown=on_shutdown, **kwargs)
starlette.routing.Router.__init__ = _patched_router_init

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Core Generation and Retrieval references (preserved for backward compatibility with existing tests)
from app.generation.answer_generator import generate_answer
from app.generation.deepseek_client import deepseek_enabled, deepseek_generator
from app.retrieval.hybrid_retriever import retrieve

# Controllers
from app.controllers.health_controller import router as health_router
from app.controllers.rag_controller import (
    router as rag_router,
    RetrievalRequest,
    RetrievalAPIResponse,
    AskRequest,
)
from app.controllers.kb_controller import router as kb_router
from app.controllers.import_controller import router as import_router, ParseRequest

# Services
from app.services.rag_service import rag_service

# Utils, Exceptions & Logging
from app.utils.exceptions import BusinessException, business_exception_handler
from app.utils.logger import get_logger, setup_logging
from configs.settings import settings
import time
import uuid
from starlette.requests import Request

logger = get_logger("app.api")

FRONTEND_DIR = settings.paths.frontend_dir
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"


def ask(question: str) -> dict:
    """Run the formal module 3 -> module 4 pipeline."""
    response = retrieve(question)
    generator = deepseek_generator if deepseek_enabled() else None
    return generate_answer(question, response, generator=generator)


# Create FastAPI application
app = FastAPI(
    title="RegTrust-RAG API",
    description="银行业监管制度与统计报表可信 RAG 问答系统 (标准分层重构版)",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Exception handlers
app.add_exception_handler(BusinessException, business_exception_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    method = request.method
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    start_time = time.perf_counter()

    is_static = path.startswith("/src") or path.startswith("/css") or path.startswith("/js") or path.endswith(".ico")
    if not is_static:
        logger.info(f"👉 [REQ-{req_id}] {method} {path} | Client: {client_ip}")

    try:
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start_time) * 1000
        if not is_static:
            status_code = response.status_code
            log_fn = logger.info if status_code < 400 else (logger.warning if status_code < 500 else logger.error)
            log_fn(f"👈 [REQ-{req_id}] {method} {path} | Status: {status_code} | Latency: {latency_ms:.2f}ms")
        return response
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.error(
            f"❌ [REQ-{req_id}] {method} {path} | Exception: {type(exc).__name__}: {exc} | Latency: {latency_ms:.2f}ms",
            exc_info=True,
        )
        raise


# Register Routers
app.include_router(health_router)
app.include_router(kb_router)
app.include_router(import_router)


@app.post(
    "/api/v1/retrieve",
    response_model=RetrievalAPIResponse,
    tags=["retrieval"],
    summary="Run module-3 retrieval",
)
def retrieve_endpoint(request: RetrievalRequest) -> dict[str, Any]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")
    try:
        response = retrieve(question, top_k=request.top_k)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "retrieval_unavailable",
                "error_type": type(exc).__name__,
            },
        ) from exc
    return response.to_dict() if hasattr(response, "to_dict") else response


def ask(question: str, top_k: int = 5) -> dict[str, Any]:
    return rag_service.ask(
        question,
        top_k=top_k,
        retriever_fn=retrieve,
        deepseek_enabled_fn=deepseek_enabled,
    )


@app.post("/api/v1/ask", tags=["rag"], summary="Run End-to-End RAG Q&A")
def api_ask(req: AskRequest):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="问题不能为空")

    return rag_service.ask(q, top_k=req.top_k or 5)

# Mount frontend static folders for unified local preview
if (FRONTEND_DIR / "src").exists():
    app.mount("/src", StaticFiles(directory=str(FRONTEND_DIR / "src")), name="src")
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


@app.get("/", summary="Frontend Single Page App Launcher")
def get_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "status": "healthy",
        "service": "RegTrust-RAG Engine",
        "version": "2.1.0",
        "architecture": "Layered REST API (Controllers - Services - Repositories - Models)",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.server.host, port=settings.server.port)
