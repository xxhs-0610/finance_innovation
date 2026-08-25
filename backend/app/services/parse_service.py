"""Document Parsing & Import Service Layer."""
from __future__ import annotations

from typing import Any, Optional


class ParseService:
    """Service for handling document ingestion and parsing dispatch."""

    def trigger_batch_parse(self, filenames: Optional[list[str]] = None) -> dict[str, Any]:
        """Trigger incremental parsing task."""
        file_list = filenames or []
        return {
            "status": "success",
            "message": f"成功触发增量解析任务，共排队处理 {len(file_list)} 份文件",
            "queue_length": len(file_list),
            "files": file_list,
        }


parse_service = ParseService()
