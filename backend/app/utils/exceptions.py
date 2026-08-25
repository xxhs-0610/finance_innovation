"""Custom Application Exceptions and Exception Handlers."""
from __future__ import annotations

from typing import Any
from fastapi import Request, status
from fastapi.responses import JSONResponse


class BusinessException(Exception):
    """Base business exception."""

    def __init__(self, code: int = 400, message: str = "业务请求异常", data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class RetrievalUnavailableException(BusinessException):
    """Raised when the retrieval engine is temporarily unavailable."""

    def __init__(self, message: str = "检索服务暂不可用", detail: Any = None):
        super().__init__(code=503, message=message, data=detail)


async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    """Global exception handler for BusinessException."""
    return JSONResponse(
        status_code=exc.code if exc.code in range(400, 600) else 400,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.data,
        },
    )
