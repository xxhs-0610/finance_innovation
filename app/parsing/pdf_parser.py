from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from app.parsing.common import clean_text, infer_value_type, join_non_empty, normalize_decimal
from app.parsing.metadata import (
    detect_heading,
    detect_period,
    detect_unit,
    extract_text_metadata,
    find_clause_no,
    prefer_extracted_title,
    stable_content_hash,
)
from app.parsing.models import ParseBundle, ParseIssue, ParsedBlock, ParsedCell, ParsedDocument, ParsedTable


PARSER_VERSION = "1.0.0"
_OCR_ENGINE = None


def _extract_pdf_lines(page) -> list[tuple[str, dict[str, float]]]:
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        grouped[round(float(word.get("top", 0)) / 3) * 3].append(word)
    lines: list[tuple[str, dict[str, float]]] = []
    for _, line_words in sorted(grouped.items()):
        line_words.sort(key=lambda item: float(item.get("x0", 0)))
        text = clean_text(" ".join(clean_text(item.get("text")) for item in line_words))
        if not text:
            continue
        lines.append(
            (
                text,
                {
                    "x0": min(float(item.get("x0", 0)) for item in line_words),
                    "top": min(float(item.get("top", 0)) for item in line_words),
                    "x1": max(float(item.get("x1", 0)) for item in line_words),
                    "bottom": max(float(item.get("bottom", 0)) for item in line_words),
                },
            )
        )
    return lines


def _ocr_pdf_page(path: Path, page_number: int) -> list[tuple[str, dict[str, float]]]:
    global _OCR_ENGINE
    try:
        import pymupdf as fitz
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return []
    pdf = fitz.open(path)
    try:
        page = pdf[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        result, _ = _OCR_ENGINE(image)
        lines: list[tuple[str, dict[str, float]]] = []
        for item in result or []:
            box, text, score = item
            if float(score) < 0.5 or not clean_text(text):
                continue
            xs = [float(point[0]) / 2 for point in box]
            ys = [float(point[1]) / 2 for point in box]
            lines.append(
                (
                    clean_text(text),
                    {"x0": min(xs), "top": min(ys), "x1": max(xs), "bottom": max(ys)},
                )
            )
        return lines
    finally:
        pdf.close()


def _pdf_table(
    rows: list[list[Any]], document: ParsedDocument, page_no: int, table_index: int, sequence_no: int
) -> ParsedTable:
    normalized_rows = [[clean_text(value) for value in row] for row in rows]
    table_id = f"{document.doc_id}_p{page_no:04d}_table_{table_index:03d}"
    table_name = next((value for row in normalized_rows[:3] for value in row if value), f"第{page_no}页表{table_index}")
    top_text = join_non_empty(value for row in normalized_rows[:5] for value in row)
    unit = detect_unit(top_text)
    period = detect_period(document.title, document.file_name, top_text)

    def factory() -> Iterator[ParsedCell]:
        for row_index, row in enumerate(normalized_rows, start=1):
            row_header = clean_text(row[0]) if row else ""
            for col_index, value in enumerate(row, start=1):
                if not value:
                    continue
                col_header = clean_text(normalized_rows[0][col_index - 1]) if normalized_rows else ""
                yield ParsedCell(
                    cell_id=f"{table_id}_r{row_index}_c{col_index}",
                    table_id=table_id,
                    doc_id=document.doc_id,
                    row_index=row_index,
                    col_index=col_index,
                    cell_ref=f"R{row_index}C{col_index}",
                    raw_value=value,
                    display_value=value,
                    normalized_value=normalize_decimal(value),
                    value_type=infer_value_type(value),
                    metric_name=row_header if col_index > 1 else col_header,
                    period=period,
                    unit=unit,
                    row_header=row_header,
                    col_header=col_header,
                    is_header=row_index == 1,
                    source_locator={"page_no": page_no, "table_index": table_index, "row": row_index, "column": col_index},
                )

    return ParsedTable(
        table_id=table_id,
        doc_id=document.doc_id,
        sequence_no=sequence_no,
        source_kind="pdf",
        table_index=table_index,
        table_name=table_name,
        page_no=page_no,
        unit=unit,
        period=period,
        header_rows=[1] if normalized_rows else [],
        row_count=len(normalized_rows),
        column_count=max((len(row) for row in normalized_rows), default=0),
        source_locator={"page_no": page_no, "table_index": table_index},
        cells_factory=factory,
    )


def parse_pdf(path: Path, document: ParsedDocument, ocr_threshold: int = 30) -> ParseBundle:
    import pdfplumber

    blocks: list[ParsedBlock] = []
    tables: list[ParsedTable] = []
    issues: list[ParseIssue] = []
    section_stack: list[str] = []
    sequence_no = 0
    global_table_index = 0
    with pdfplumber.open(path) as pdf:
        document.page_count = len(pdf.pages)
        document.parser_name = "pdfplumber"
        document.parser_version = PARSER_VERSION
        for page_no, page in enumerate(pdf.pages, start=1):
            lines = _extract_pdf_lines(page)
            text_length = sum(len(text) for text, _ in lines)
            if text_length < ocr_threshold:
                ocr_lines = _ocr_pdf_page(path, page_no)
                if ocr_lines:
                    lines = ocr_lines
                    issues.append(
                        ParseIssue(
                            document.doc_id,
                            "pdf-ocr",
                            "info",
                            "OCR_APPLIED",
                            f"OCR applied to PDF page {page_no}",
                            context={"page_no": page_no},
                        )
                    )
                elif page.images:
                    issues.append(
                        ParseIssue(
                            document.doc_id,
                            "pdf-ocr",
                            "warning",
                            "OCR_UNAVAILABLE",
                            f"Page {page_no} has little text and images, but OCR is unavailable or returned no text",
                            retryable=True,
                            context={"page_no": page_no},
                        )
                    )
                else:
                    issues.append(
                        ParseIssue(
                            document.doc_id,
                            "pdf",
                            "info",
                            "BLANK_PAGE",
                            f"PDF page {page_no} appears blank",
                            context={"page_no": page_no},
                        )
                    )
            for line_no, (text, bbox) in enumerate(lines, start=1):
                sequence_no += 1
                heading_level = detect_heading(text)
                clause_no = find_clause_no(text)
                if heading_level:
                    while len(section_stack) >= heading_level:
                        section_stack.pop()
                    section_stack.append(text)
                    block_type = "heading"
                elif clause_no:
                    block_type = "clause"
                else:
                    block_type = "paragraph"
                blocks.append(
                    ParsedBlock(
                        block_id=f"{document.doc_id}_block_{len(blocks) + 1:06d}",
                        doc_id=document.doc_id,
                        sequence_no=sequence_no,
                        block_type=block_type,
                        text=text,
                        page_no=page_no,
                        heading_level=heading_level,
                        section_path=list(section_stack),
                        clause_no=clause_no,
                        bbox=bbox,
                        source_locator={"page_no": page_no, "line_no": line_no, "bbox": bbox},
                        content_hash=stable_content_hash(text),
                    )
                )
            try:
                page_tables = page.extract_tables() or []
            except Exception as exc:
                issues.append(
                    ParseIssue(
                        document.doc_id,
                        "pdf-table",
                        "warning",
                        "TABLE_EXTRACTION_FAILED",
                        f"PDF table extraction failed on page {page_no}: {exc}",
                        retryable=True,
                        context={"page_no": page_no},
                    )
                )
                page_tables = []
            for page_table_index, rows in enumerate(page_tables, start=1):
                if not rows:
                    continue
                global_table_index += 1
                sequence_no += 1
                tables.append(_pdf_table(rows, document, page_no, global_table_index, sequence_no))

    metadata = extract_text_metadata("\n".join(block.text for block in blocks[:150]), document.title)
    document.title = prefer_extracted_title(metadata["title"], document.title)
    document.issuer = metadata["issuer"] or document.issuer
    document.document_no = metadata["document_no"] or document.document_no
    document.publish_date = metadata["publish_date"] or document.publish_date
    document.publish_date_text = metadata["publish_date_text"] or document.publish_date_text
    document.metadata_source.update(
        {key: "document_text" for key in ("title", "issuer", "document_no", "publish_date") if metadata.get(key)}
    )
    document.metadata_confidence.update(
        {key: 0.85 for key in ("title", "issuer", "document_no", "publish_date") if metadata.get(key)}
    )
    if not blocks and not tables:
        issues.append(ParseIssue(document.doc_id, "pdf", "error", "EMPTY_PDF", "PDF contains no extractable content"))
    return ParseBundle(document=document, blocks=blocks, tables=tables, issues=issues)
