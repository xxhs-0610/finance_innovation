"""Import and Parsing Pipeline API Controller."""
from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.parse_service import parse_service
from app.utils.logger import get_logger

logger = get_logger("app.controllers.import")


class ParseRequest(BaseModel):
    """Payload for scheduling document parsing."""

    filenames: Optional[list[str]] = Field(default=None, description="待解析入库的文件名列表")


router = APIRouter(tags=["import"])


@router.post("/api/v1/import/parse", summary="Trigger incremental document parsing")
def trigger_parse(req: ParseRequest) -> dict[str, Any]:
    """Queue files for multi-format document parsing and database ingestion."""
    logger.info(f"[ImportController] 触发文档批量解析任务: {len(req.filenames or [])} 个文件")
    result = parse_service.trigger_batch_parse(req.filenames)
    logger.info(f"[ImportController] 解析任务已接收: status={result.get('status')}")
    return result
