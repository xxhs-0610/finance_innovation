from __future__ import annotations

from pathlib import Path

from app.parsing.excel_parser import parse_xls, parse_xlsx
from app.parsing.models import ParseBundle, ParsedDocument
from app.parsing.pdf_parser import parse_pdf
from app.parsing.word_parser import parse_doc, parse_docx


def parse_document(path: Path, document: ParsedDocument) -> ParseBundle:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        bundle = parse_docx(path, document)
    elif suffix == ".doc":
        bundle = parse_doc(path, document)
    elif suffix == ".pdf":
        bundle = parse_pdf(path, document)
    elif suffix == ".xlsx":
        bundle = parse_xlsx(path, document)
    elif suffix == ".xls":
        bundle = parse_xls(path, document)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    errors = [issue for issue in bundle.issues if issue.severity == "error"]
    warnings = [issue for issue in bundle.issues if issue.severity == "warning"]
    if errors and not bundle.blocks and not bundle.tables:
        bundle.document.parse_status = "failed"
    elif errors or warnings:
        bundle.document.parse_status = "partial"
    else:
        bundle.document.parse_status = "success"
    return bundle

