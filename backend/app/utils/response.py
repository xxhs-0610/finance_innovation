"""Standardized API Response Envelopes and Response Helpers."""
from __future__ import annotations

import time
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class APIResponse(BaseModel, Generic[DataT]):
    """Standard unified response wrapper for REST APIs."""

    code: int = Field(default=200, description="Business status code, 200 means success")
    message: str = Field(default="success", description="Status message")
    data: Optional[DataT] = Field(default=None, description="Response payload")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000), description="Epoch timestamp in ms")


def success_response(data: Any = None, message: str = "success") -> dict[str, Any]:
    """Helper to return a success dict response."""
    return {
        "code": 200,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }


def error_response(code: int = 500, message: str = "Internal Server Error", data: Any = None) -> dict[str, Any]:
    """Helper to return a standardized error dict response."""
    return {
        "code": code,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
