"""Evidence Adapter Module for RegTrust-RAG (Prompt 10).

Adapts multi-format knowledge chunks (PDF, Word, Excel) into a uniform Evidence contract.
Decouples upper-level task planners, executors, verifiers, and composers from raw file formats.
"""

from __future__ import annotations

import os
import re
from typing import Any, Sequence

from app.schemas.chunk_schema import KnowledgeChunk, SearchResult, SourceInfo
from app.schemas.table_execution_schema import TableOperandResult
from app.schemas.unified_evidence_schema import SourceType, UnifiedEvidence
from app.utils.logger import get_logger

logger = get_logger("app.retrieval.evidence_adapter")


class EvidenceAdapter:
    """Universal Evidence Adapter across PDF, Word, and Excel sources."""

    def adapt(self, raw_item: Any) -> UnifiedEvidence:
        """Convert any raw chunk, search result, or dict into a standard UnifiedEvidence."""
        if isinstance(raw_item, UnifiedEvidence):
            return raw_item

        # Extract fields from dict or object
        if isinstance(raw_item, SearchResult):
            evidence_id = raw_item.chunk_id
            text = raw_item.text
            score = raw_item.score
            source = raw_item.source
            metadata = dict(raw_item.metadata or {})
            if source.doc_id:
                metadata.setdefault("doc_id", source.doc_id)
            chunk_type = raw_item.chunk_type
            title = source.title
            local_path = source.local_path
            source_url = source.source_url
            section_path = source.section_path
            clause_no = source.clause_no
            sheet_name = source.sheet_name
            table_name = source.table_name
            cell_ref = source.cell_ref
            issuer = source.issuer
            publish_date = source.publish_date
        elif isinstance(raw_item, KnowledgeChunk):
            evidence_id = raw_item.chunk_id
            text = raw_item.text
            score = 1.0
            source = raw_item.source
            metadata = dict(raw_item.metadata or {})
            if source.doc_id:
                metadata.setdefault("doc_id", source.doc_id)
            chunk_type = raw_item.chunk_type
            title = source.title
            local_path = source.local_path
            source_url = source.source_url
            section_path = source.section_path
            clause_no = source.clause_no
            sheet_name = source.sheet_name
            table_name = source.table_name
            cell_ref = source.cell_ref
            issuer = source.issuer
            publish_date = source.publish_date
        elif isinstance(raw_item, dict):
            source_data = raw_item.get("source") if isinstance(raw_item.get("source"), dict) else {}
            evidence_id = str(raw_item.get("evidence_id") or raw_item.get("chunk_id") or raw_item.get("id") or "E1")
            text = str(raw_item.get("text") or raw_item.get("content") or "")
            score = float(raw_item.get("score") or 1.0)
            metadata = dict(raw_item.get("metadata")) if isinstance(raw_item.get("metadata"), dict) else {}
            doc_id = raw_item.get("doc_id") or source_data.get("doc_id")
            if doc_id:
                metadata.setdefault("doc_id", str(doc_id))
            chunk_type = raw_item.get("chunk_type") or ("table" if "sheet_name" in raw_item or "table_name" in raw_item else "clause")
            title = str(raw_item.get("title") or raw_item.get("source_title") or raw_item.get("document_name") or source_data.get("title") or "")
            local_path = str(raw_item.get("local_path") or source_data.get("local_path") or "")
            source_url = str(raw_item.get("source_url") or source_data.get("source_url") or "")
            section_path = raw_item.get("section_path") or source_data.get("section_path") or []
            clause_no = str(raw_item.get("clause_no") or raw_item.get("article") or source_data.get("clause_no") or "")
            sheet_name = str(raw_item.get("sheet_name") or raw_item.get("sheet") or source_data.get("sheet_name") or "")
            table_name = str(raw_item.get("table_name") or source_data.get("table_name") or "")
            cell_ref = str(raw_item.get("cell_ref") or raw_item.get("cell") or source_data.get("cell_ref") or "")
            issuer = str(raw_item.get("issuer") or source_data.get("issuer") or "")
            publish_date = str(raw_item.get("publish_date") or source_data.get("publish_date") or "")
        else:
            text = str(raw_item)
            return UnifiedEvidence(
                evidence_id="E1",
                source_type="unknown",
                source_title="",
                location={},
                content=text,
            )

        # 1. Determine source_type
        source_type = self._detect_source_type(
            local_path=local_path,
            source_url=source_url,
            title=title,
            chunk_type=chunk_type,
            metadata=metadata,
        )

        # 2. Extract standardized location
        location = self._extract_location(
            source_type=source_type,
            sheet_name=sheet_name,
            table_name=table_name,
            cell_ref=cell_ref,
            section_path=section_path,
            clause_no=clause_no,
            metadata=metadata,
            text=text,
        )

        # 3. Parse structured_value
        structured_val = self._extract_structured_value(source_type, text, metadata)

        # 4. Clean source_title
        if not title and "【" in text and "】" in text:
            m = re.search(r"【([^】]+)】", text)
            if m:
                title = m.group(1).strip()

        return UnifiedEvidence(
            evidence_id=evidence_id,
            source_type=source_type,
            source_title=title,
            location=location,
            content=text,
            structured_value=structured_val,
            score=score,
            citation_id=str(raw_item.get("citation_id", "E1") if isinstance(raw_item, dict) else "E1"),
            issuer=issuer,
            publish_date=publish_date,
            metadata=metadata,
        )

    def adapt_list(self, raw_items: Sequence[Any]) -> list[UnifiedEvidence]:
        """Convert a sequence of raw items into a list of UnifiedEvidence."""
        return [self.adapt(item) for item in raw_items]

    def _detect_source_type(
        self,
        local_path: str,
        source_url: str,
        title: str,
        chunk_type: str,
        metadata: dict[str, Any],
    ) -> SourceType:
        """Detect source type (excel, word, pdf) based on file extension and semantics."""
        path_lower = (local_path + " " + source_url).lower()
        if any(path_lower.endswith(ext) or ext + "?" in path_lower for ext in (".xlsx", ".xls", ".csv")):
            return "excel"
        if any(path_lower.endswith(ext) or ext + "?" in path_lower for ext in (".docx", ".doc")):
            return "word"
        if ".pdf" in path_lower:
            return "pdf"

        # Check metadata
        doc_format = str(metadata.get("format") or metadata.get("file_type") or "").lower()
        if doc_format in {"excel", "xlsx", "xls", "csv"}:
            return "excel"
        if doc_format in {"word", "docx", "doc"}:
            return "word"
        if doc_format in {"pdf"}:
            return "pdf"

        # Check chunk_type and semantic hints
        if chunk_type == "table" or "情况表" in title or "统计表" in title or "资产负债表" in title or "损益表" in title:
            return "excel"
        if "办法" in title or "规定" in title or "指引" in title or "通知" in title or "条例" in title:
            return "word"

        return "unknown"

    def _extract_location(
        self,
        source_type: SourceType,
        sheet_name: str,
        table_name: str,
        cell_ref: str,
        section_path: Any,
        clause_no: str,
        metadata: dict[str, Any],
        text: str,
    ) -> dict[str, Any]:
        """Build format-specific location map conforming to Prompt 10 specification."""
        loc: dict[str, Any] = {}
        if source_type == "excel":
            # Extract row and column info if available in text
            row_val = ""
            col_val = ""
            m_row = re.search(r"(?:行|项目)[=：:\s]+([^\|；;\n]+)", text)
            if m_row:
                row_val = m_row.group(1).strip()
            loc = {
                "sheet": sheet_name or table_name or str(metadata.get("sheet", "")),
                "row": row_val or str(metadata.get("row", "")),
                "column": col_val or str(metadata.get("column", "")),
                "cell": cell_ref or str(metadata.get("cell", "")),
            }
        elif source_type == "word":
            sec_str = (
                " > ".join(section_path)
                if isinstance(section_path, list)
                else str(section_path or metadata.get("section", ""))
            )
            loc = {
                "section": sec_str,
                "article": clause_no or str(metadata.get("article", "")),
            }
        elif source_type == "pdf":
            page = metadata.get("page") or metadata.get("page_no")
            if not page:
                m_page = re.search(r"第\s*(\d+)\s*页", text)
                page = int(m_page.group(1)) if m_page else 1
            sec_str = (
                " > ".join(section_path)
                if isinstance(section_path, list)
                else str(section_path or metadata.get("section", ""))
            )
            loc = {
                "page": int(page),
                "section": sec_str,
            }
        else:
            loc = {"raw": clause_no or sheet_name or ""}
        return loc

    def _extract_structured_value(
        self,
        source_type: SourceType,
        text: str,
        metadata: dict[str, Any],
    ) -> Any | None:
        """Extract structured representation from chunk content (e.g. key-value pairs)."""
        if source_type == "excel" or "行=" in text or "项目=" in text or " = " in text:
            from app.retrieval.table_executor import parse_table_chunk_kv
            kv_map, unit = parse_table_chunk_kv(text)
            if kv_map:
                return {"kv": kv_map, "unit": unit}
        return None

    def extract_numeric_value(
        self,
        evidence_list: Sequence[UnifiedEvidence | Any],
        target_name: str,
        *,
        row: str | None = None,
        column: str | None = None,
        scope: str | None = None,
    ) -> TableOperandResult:
        """Universal programmatic numeric extraction across all evidence types (Excel, Word, PDF)."""
        adapted_list = [self.adapt(e) for e in evidence_list]
        from app.retrieval.table_executor import extract_operand_value
        return extract_operand_value(
            adapted_list,
            target_name,
            row=row,
            column=column,
            scope=scope,
        )


evidence_adapter = EvidenceAdapter()
