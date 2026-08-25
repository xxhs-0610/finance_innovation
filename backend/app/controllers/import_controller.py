"""Import and Parsing Pipeline API Controller."""
from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.parse_service import parse_service


class ParseRequest(BaseModel):
    """Payload for scheduling document parsing."""

    filenames: Optional[list[str]] = Field(default=None, description="待解析入库的文件名列表")


router = APIRouter(tags=["import"])


@router.post("/api/v1/import/parse", summary="Trigger incremental document parsing")
def trigger_parse(req: ParseRequest) -> dict[str, Any]:
    """Queue files for multi-format document parsing and database ingestion."""
    return parse_service.trigger_batch_parse(req.filenames)
