from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from app.parsing.common import clean_text, join_non_empty, normalize_decimal, infer_value_type
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


def _iter_docx_blocks(document) -> Iterator[object]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _table_from_docx(table, document: ParsedDocument, table_index: int, sequence_no: int) -> ParsedTable:
    rows = [[clean_text(cell.text) for cell in row.cells] for row in table.rows]
    title = next((value for row in rows[:3] for value in row if value), f"表{table_index}")
    unit = detect_unit(*(value for row in rows[:5] for value in row))
    period = detect_period(document.title, document.file_name, *(value for row in rows[:5] for value in row))
    table_id = f"{document.doc_id}_word_table_{table_index:04d}"

    def cells_factory() -> Iterator[ParsedCell]:
        header_rows = {1}
        for row_index, row in enumerate(rows, start=1):
            row_header = clean_text(row[0]) if row else ""
            for col_index, value in enumerate(row, start=1):
                if not value:
                    continue
                col_header = clean_text(rows[0][col_index - 1]) if rows and col_index <= len(rows[0]) else ""
                is_header = row_index in header_rows
                metric_name = row_header if col_index > 1 else col_header
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
                    metric_name=metric_name,
                    period=period,
                    unit=unit,
                    row_header=row_header,
                    col_header=col_header,
                    is_header=is_header,
                    source_locator={"table_index": table_index, "row": row_index, "column": col_index},
                )

    return ParsedTable(
        table_id=table_id,
        doc_id=document.doc_id,
        sequence_no=sequence_no,
        source_kind=document.file_type,
        table_index=table_index,
        table_name=title,
        unit=unit,
        period=period,
        header_rows=[1] if rows else [],
        row_count=len(rows),
        column_count=max((len(row) for row in rows), default=0),
        source_locator={"table_index": table_index, "sequence_no": sequence_no},
        cells_factory=cells_factory,
    )


def parse_docx(path: Path, document: ParsedDocument, parser_name: str = "python-docx") -> ParseBundle:
    from docx import Document
    from docx.table import Table

    docx = Document(str(path))
    blocks: list[ParsedBlock] = []
    tables: list[ParsedTable] = []
    issues: list[ParseIssue] = []
    section_stack: list[str] = []
    sequence_no = 0
    table_index = 0

    for item in _iter_docx_blocks(docx):
        sequence_no += 1
        if isinstance(item, Table):
            table_index += 1
            tables.append(_table_from_docx(item, document, table_index, sequence_no))
            continue
        text = clean_text(item.text)
        if not text:
            continue
        style_name = clean_text(getattr(getattr(item, "style", None), "name", ""))
        heading_level = detect_heading(text, style_name)
        clause_no = find_clause_no(text)
        if heading_level:
            while len(section_stack) >= heading_level:
                section_stack.pop()
            section_stack.append(text)
            block_type = "heading"
        elif clause_no:
            block_type = "clause"
        elif style_name.lower().startswith("list"):
            block_type = "list"
        else:
            block_type = "paragraph"
        blocks.append(
            ParsedBlock(
                block_id=f"{document.doc_id}_block_{len(blocks) + 1:06d}",
                doc_id=document.doc_id,
                sequence_no=sequence_no,
                block_type=block_type,
                text=text,
                heading_level=heading_level,
                section_path=list(section_stack),
                clause_no=clause_no,
                source_locator={"sequence_no": sequence_no, "style": style_name},
                content_hash=stable_content_hash(text),
            )
        )

    sample_text = "\n".join(block.text for block in blocks[:100])
    metadata = extract_text_metadata(sample_text, document.title)
    document.title = prefer_extracted_title(metadata["title"], document.title)
    document.issuer = metadata["issuer"] or document.issuer
    document.document_no = metadata["document_no"] or document.document_no
    document.publish_date = metadata["publish_date"] or document.publish_date
    document.publish_date_text = metadata["publish_date_text"] or document.publish_date_text
    document.parser_name = parser_name
    document.parser_version = PARSER_VERSION
    document.metadata_source.update(
        {key: "document_text" for key in ("title", "issuer", "document_no", "publish_date") if metadata.get(key)}
    )
    document.metadata_confidence.update(
        {key: 0.9 for key in ("title", "issuer", "document_no", "publish_date") if metadata.get(key)}
    )
    if not blocks and not tables:
        issues.append(
            ParseIssue(document.doc_id, "word", "error", "EMPTY_DOCUMENT", "Word document contains no extractable content")
        )
    return ParseBundle(document=document, blocks=blocks, tables=tables, issues=issues)


def _convert_with_libreoffice(source: Path, output_dir: Path) -> Path | None:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return None
    subprocess.run(
        [executable, "--headless", "--convert-to", "docx", "--outdir", str(output_dir), str(source)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    target = output_dir / f"{source.stem}.docx"
    return target if target.exists() else None


def _convert_with_word_com(source: Path, output_dir: Path) -> Path | None:
    if shutil.which("WINWORD.EXE") is None and not Path(
        r"C:\Program Files\Microsoft Office\Root\Office16\WINWORD.EXE"
    ).exists():
        return None
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError:
        return None
    target = output_dir / f"{source.stem}.docx"
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        opened = word.Documents.Open(str(source.resolve()), ReadOnly=True, AddToRecentFiles=False)
        try:
            opened.SaveAs2(str(target.resolve()), FileFormat=16)
        finally:
            opened.Close(False)
    finally:
        word.Quit()
    return target if target.exists() else None


def parse_doc(path: Path, document: ParsedDocument) -> ParseBundle:
    with tempfile.TemporaryDirectory(prefix="rag_doc_convert_") as temporary:
        output_dir = Path(temporary)
        converted = None
        converter = ""
        try:
            converted = _convert_with_libreoffice(path, output_dir)
            converter = "libreoffice"
        except Exception:
            converted = None
        if converted is None:
            converted = _convert_with_word_com(path, output_dir)
            converter = "word-com"
        if converted is None:
            return ParseBundle(
                document=document,
                issues=[
                    ParseIssue(
                        document.doc_id,
                        "doc-conversion",
                        "error",
                        "DOC_CONVERTER_UNAVAILABLE",
                        "Neither LibreOffice nor Microsoft Word COM conversion is available",
                        retryable=True,
                    )
                ],
            )
        bundle = parse_docx(converted, document, parser_name=f"{converter}+python-docx")
        bundle.issues.append(
            ParseIssue(
                document.doc_id,
                "doc-conversion",
                "info",
                "DOC_CONVERTED",
                f"Legacy DOC converted with {converter}",
            )
        )
        return bundle
