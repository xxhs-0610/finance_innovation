from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

from app.parsing.config import PROJECT_ROOT, DatabaseConfig, output_paths
from app.parsing.database import ParsingDatabase
from app.parsing.inventory import build_inventory, inventory_summary, write_manifest
from app.parsing.models import ParsedDocument
from app.parsing.registry import parse_document
from app.parsing.table_evidence import iter_table_evidence, table_summary_evidence


PARSER_VERSION = "1.0.0"


def sync_raw_files(source_dir: Path, target_dir: Path) -> dict[str, int]:
    if not source_dir.exists():
        raise FileNotFoundError(f"External source directory does not exist: {source_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    counters = Counter(copied=0, skipped=0)
    for source in sorted(path for path in source_dir.iterdir() if path.is_file() and not path.name.startswith("._")):
        target = target_dir / source.name
        if target.exists() and target.stat().st_size == source.stat().st_size:
            counters["skipped"] += 1
            continue
        shutil.copy2(source, target)
        counters["copied"] += 1
    return dict(counters)


def inventory_and_store(input_dir: Path, database: ParsingDatabase) -> tuple[list[ParsedDocument], dict[str, object]]:
    documents = build_inventory(input_dir)
    paths = output_paths()
    write_manifest(paths["manifest"], documents)
    database.upsert_inventory(documents)
    return documents, inventory_summary(documents)


def run_parse(
    input_dir: Path,
    database: ParsingDatabase,
    *,
    force: bool = False,
    retry_failed: bool = False,
    limit: int | None = None,
    file_types: set[str] | None = None,
    doc_ids: set[str] | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    documents, summary = inventory_and_store(input_dir, database)
    if file_types:
        documents = [doc for doc in documents if doc.file_type in file_types]
    if doc_ids:
        documents = [doc for doc in documents if doc.doc_id in doc_ids]
    if limit is not None:
        documents = documents[:limit]
    mode = "retry_failed" if retry_failed else ("force" if force else "incremental")
    run_id = database.start_run(PARSER_VERSION, mode, str(input_dir), len(documents))
    counters = Counter(processed=0, success=0, partial=0, failed=0, skipped=0)
    object_counts = Counter(blocks=0, tables=0, cells=0, issues=0)
    for index, document in enumerate(documents, start=1):
        if not database.should_parse(document, PARSER_VERSION, force=force, retry_failed=retry_failed):
            counters["skipped"] += 1
            progress(f"[{index}/{len(documents)}] SKIP {document.doc_id} {document.file_name}")
            continue
        progress(f"[{index}/{len(documents)}] PARSE {document.doc_id} {document.file_name}")
        document.parse_status = "parsing"
        try:
            bundle = parse_document(document.absolute_path, document)
            counts = database.persist_bundle(bundle, run_id)
            object_counts.update(counts)
            counters["processed"] += 1
            counters[bundle.document.parse_status] += 1
            progress(
                f"[{index}/{len(documents)}] {bundle.document.parse_status.upper()} "
                f"blocks={counts['blocks']} tables={counts['tables']} cells={counts['cells']}"
            )
        except Exception as exc:
            try:
                database.mark_failed(document, run_id, exc)
            except Exception as mark_exc:
                progress(
                    f"[{index}/{len(documents)}] WARNING could not persist failure status: "
                    f"{type(mark_exc).__name__}: {mark_exc}"
                )
            counters["processed"] += 1
            counters["failed"] += 1
            progress(f"[{index}/{len(documents)}] FAILED {document.doc_id}: {type(exc).__name__}: {exc}")
    run_summary = {"inventory": summary, "objects": dict(object_counts)}
    database.finish_run(run_id, dict(counters), run_summary)
    return {"run_id": run_id, "files": dict(counters), **run_summary}


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_rows(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
            count += 1
    return count


def export_jsonl(database: ParsingDatabase, *, include_cell_archive: bool = True) -> dict[str, int]:
    paths = output_paths()

    def meta_rows():
        sql = """
            SELECT doc_id,title,issuer,publish_date,file_type,source_url,local_path,sha256,
                   document_no,source_page_title,attachment_title,document_family_id,
                   file_size,page_count,sheet_count,parse_status
            FROM rag_documents ORDER BY source_seq, doc_id
        """
        columns = [
            "doc_id", "title", "issuer", "publish_date", "file_type", "source_url", "local_path", "sha256",
            "document_no", "source_page_title", "attachment_title", "document_family_id", "file_size",
            "page_count", "sheet_count", "parse_status",
        ]
        for row in database.stream_query(sql):
            yield dict(zip(columns, row))

    def document_rows():
        sql = """
            SELECT d.doc_id,d.title,d.issuer,d.publish_date,d.source_url,d.local_path,
                   b.section_path,b.clause_no,b.text,b.block_id,b.block_type,b.page_no,
                   b.source_locator,d.document_no
            FROM rag_document_blocks b
            JOIN rag_documents d ON d.doc_id=b.doc_id
            WHERE b.is_active=1 AND b.block_type IN ('paragraph','clause','list') AND b.text<>''
            ORDER BY d.source_seq,b.sequence_no
        """
        for row in database.stream_query(sql):
            section_path = json.loads(row[6]) if isinstance(row[6], str) and row[6] else (row[6] or [])
            source_locator = json.loads(row[12]) if isinstance(row[12], str) and row[12] else (row[12] or {})
            yield {
                "doc_id": row[0],
                "title": row[1] or "",
                "issuer": row[2] or "",
                "publish_date": row[3].isoformat() if row[3] else "",
                "source_url": row[4],
                "local_path": row[5],
                "section_path": section_path,
                "clause_no": row[7] or "",
                "text": row[8],
                "block_id": row[9],
                "block_type": row[10],
                "page_no": row[11],
                "source_locator": source_locator,
                "document_no": row[13] or "",
            }

    def table_rows():
        sql = """
            SELECT d.doc_id,d.title,d.issuer,d.publish_date,d.source_url,d.local_path,
                   t.sheet_name,t.table_name,c.metric_name,c.period,c.unit,
                   COALESCE(NULLIF(c.display_value,''),c.raw_value),c.row_header,c.col_header,c.cell_ref,
                   t.table_id,t.page_no,c.formula,c.normalized_value,c.source_locator
            FROM rag_table_cells c
            JOIN rag_tables t ON t.table_id=c.table_id
            JOIN rag_documents d ON d.doc_id=c.doc_id
            WHERE c.is_active=1 AND t.is_active=1 AND c.is_header=0
              AND COALESCE(NULLIF(c.display_value,''),c.raw_value) IS NOT NULL
              AND COALESCE(NULLIF(c.display_value,''),c.raw_value) <> ''
            ORDER BY d.source_seq,t.sequence_no,c.row_index,c.col_index
        """
        for row in database.stream_query(sql):
            source_locator = json.loads(row[19]) if isinstance(row[19], str) and row[19] else (row[19] or {})
            yield {
                "doc_id": row[0],
                "title": row[1] or "",
                "issuer": row[2] or "",
                "publish_date": row[3].isoformat() if row[3] else "",
                "source_url": row[4],
                "local_path": row[5],
                "sheet_name": row[6] or "",
                "table_name": row[7] or "",
                "metric_name": row[8] or "",
                "period": row[9] or "",
                "unit": row[10] or "",
                "value": row[11] or "",
                "row_header": row[12] or "",
                "col_header": row[13] or "",
                "cell_ref": row[14],
                "table_id": row[15],
                "page_no": row[16],
                "formula": row[17] or "",
                "value_numeric": row[18],
                "source_locator": source_locator,
            }

    result = {
        "doc_meta": _write_rows(paths["doc_meta"], meta_rows()),
        "parsed_docs": _write_rows(paths["parsed_docs"], document_rows()),
    }
    if include_cell_archive:
        result["parsed_tables"] = _write_rows(paths["parsed_tables"], table_rows())
    return result


def export_table_evidence(database: ParsingDatabase, max_cells_per_evidence: int = 20) -> dict[str, int]:
    """Export retrieval-oriented table summaries and row segments for module 2."""
    path = output_paths()["table_evidence"]

    summary_sql = """
        SELECT d.doc_id,d.title,d.issuer,d.publish_date,d.source_url,d.local_path,
               t.table_id,t.sheet_name,t.table_name,t.page_no,t.range_ref,t.unit,t.period,
               t.row_count,t.column_count
        FROM rag_tables t
        JOIN rag_documents d ON d.doc_id=t.doc_id
        WHERE t.is_active=1
        ORDER BY d.source_seq,t.sequence_no
    """
    summary_columns = [
        "doc_id", "title", "issuer", "publish_date", "source_url", "local_path",
        "table_id", "sheet_name", "table_name", "page_no", "range_ref", "unit", "period",
        "row_count", "column_count",
    ]

    cells_sql = """
        SELECT d.doc_id,d.title,d.issuer,d.publish_date,d.source_url,d.local_path,
               t.table_id,t.sheet_name,t.table_name,t.page_no,
               c.row_index,c.col_index,c.cell_ref,
               COALESCE(NULLIF(c.display_value,''),c.raw_value),c.normalized_value,c.formula,
               c.metric_name,c.period,c.unit,c.row_header,c.col_header,c.is_header
        FROM rag_table_cells c
        JOIN rag_tables t ON t.table_id=c.table_id
        JOIN rag_documents d ON d.doc_id=c.doc_id
        WHERE c.is_active=1 AND t.is_active=1
          AND COALESCE(NULLIF(c.display_value,''),c.raw_value) IS NOT NULL
          AND COALESCE(NULLIF(c.display_value,''),c.raw_value)<>''
        ORDER BY d.source_seq,t.sequence_no,c.row_index,c.col_index
    """
    cell_columns = [
        "doc_id", "title", "issuer", "publish_date", "source_url", "local_path",
        "table_id", "sheet_name", "table_name", "page_no", "row_index", "col_index", "cell_ref",
        "value", "normalized_value", "formula", "metric_name", "period", "unit", "row_header",
        "col_header", "is_header",
    ]

    def summary_rows():
        for row in database.stream_query(summary_sql):
            yield table_summary_evidence(dict(zip(summary_columns, row)))

    def cell_rows():
        for row in database.stream_query(cells_sql):
            yield dict(zip(cell_columns, row))

    path.parent.mkdir(parents=True, exist_ok=True)
    counters = Counter(table_summaries=0, table_rows=0, total=0)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in summary_rows():
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
            counters["table_summaries"] += 1
            counters["total"] += 1
        for row in iter_table_evidence(cell_rows(), max_cells_per_evidence=max_cells_per_evidence):
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
            counters["table_rows"] += 1
            counters["total"] += 1
    return dict(counters)


def write_report(database: ParsingDatabase) -> tuple[Path, dict[str, Any]]:
    data = database.report_data()
    path = output_paths()["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    by_type = "\n".join(f"| {row['file_type']} | {row['total']} |" for row in data["by_type"])
    by_status = "\n".join(f"| {row['parse_status']} | {row['total']} |" for row in data["by_status"])
    issues = "\n".join(f"| {row['severity']} | {row['total']} |" for row in data["issues"]) or "| 无 | 0 |"
    problems = "\n".join(
        f"| {row['doc_id']} | {row['parse_status']} | {row['file_name']} | {row['last_error'] or ''} |"
        for row in data["problem_files"]
    ) or "| - | - | 无 | - |"
    content = f"""# 模块1文档解析质量报告

生成时间：{datetime.now().isoformat(timespec='seconds')}

## 总体统计

- 文档：{data['documents']}
- SHA-256 完全重复文件：{data['duplicates']}
- 正文块：{data['blocks']}
- 表格：{data['tables']}
- 活动单元格：{data['cells']}

## 文件格式

| 格式 | 数量 |
|---|---:|
{by_type}

## 解析状态

| 状态 | 数量 |
|---|---:|
{by_status}

## 问题统计

| 严重程度 | 数量 |
|---|---:|
{issues}

## 部分成功或失败文件

| doc_id | 状态 | 文件 | 最后错误 |
|---|---|---|---|
{problems}
"""
    path.write_text(content, encoding="utf-8")
    return path, data


def dependency_status() -> dict[str, bool]:
    modules = {
        "pymysql": "pymysql",
        "python-docx": "docx",
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "pdfplumber": "pdfplumber",
        "pypdf": "pypdf",
        "PyMuPDF (optional OCR rendering)": "fitz",
        "RapidOCR (optional)": "rapidocr_onnxruntime",
        "pywin32 (Windows DOC fallback)": "win32com",
    }
    return {label: importlib.util.find_spec(module) is not None for label, module in modules.items()}
