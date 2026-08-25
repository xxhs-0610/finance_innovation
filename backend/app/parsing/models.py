from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Literal


IssueSeverity = Literal["info", "warning", "error"]
ParseStatus = Literal["pending", "parsing", "success", "partial", "failed", "skipped"]


@dataclass(slots=True)
class ParsedDocument:
    doc_id: str
    source_seq: int | None
    file_name: str
    file_type: str
    file_size: int
    sha256: str
    local_path: str
    absolute_path: Path
    title: str = ""
    source_page_title: str = ""
    attachment_title: str = ""
    document_family_id: str = ""
    issuer: str = ""
    document_no: str = ""
    publish_date: date | None = None
    publish_date_text: str = ""
    source_url: str | None = None
    page_count: int | None = None
    sheet_count: int | None = None
    language: str = "zh-CN"
    parse_status: ParseStatus = "pending"
    parser_name: str = ""
    parser_version: str = ""
    duplicate_of_doc_id: str | None = None
    metadata_source: dict[str, Any] = field(default_factory=dict)
    metadata_confidence: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedBlock:
    block_id: str
    doc_id: str
    sequence_no: int
    block_type: str
    text: str
    page_no: int | None = None
    heading_level: int | None = None
    section_path: list[str] = field(default_factory=list)
    clause_no: str = ""
    bbox: dict[str, float] | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""


@dataclass(slots=True)
class ParsedCell:
    cell_id: str
    table_id: str
    doc_id: str
    row_index: int
    col_index: int
    cell_ref: str
    raw_value: str = ""
    display_value: str = ""
    normalized_value: Decimal | None = None
    value_type: str = "text"
    formula: str = ""
    metric_name: str = ""
    period: str = ""
    unit: str = ""
    row_header: str = ""
    col_header: str = ""
    is_header: bool = False
    is_merged: bool = False
    merged_anchor_ref: str = ""
    source_locator: dict[str, Any] = field(default_factory=dict)


CellIteratorFactory = Callable[[], Iterator[ParsedCell]]


@dataclass(slots=True)
class ParsedTable:
    table_id: str
    doc_id: str
    sequence_no: int
    source_kind: str
    table_index: int
    table_name: str = ""
    sheet_name: str = ""
    page_no: int | None = None
    range_ref: str = ""
    unit: str = ""
    period: str = ""
    header_rows: list[int] = field(default_factory=list)
    row_count: int = 0
    column_count: int = 0
    merged_ranges: list[str] = field(default_factory=list)
    source_locator: dict[str, Any] = field(default_factory=dict)
    cells_factory: CellIteratorFactory | None = None

    def iter_cells(self) -> Iterator[ParsedCell]:
        if self.cells_factory is None:
            return iter(())
        return self.cells_factory()


@dataclass(slots=True)
class ParseIssue:
    doc_id: str
    stage: str
    severity: IssueSeverity
    error_code: str
    message: str
    retryable: bool = False
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParseBundle:
    document: ParsedDocument
    blocks: list[ParsedBlock] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

