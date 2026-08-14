from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from app.parsing.config import display_local_path
from app.parsing.metadata import ISSUER_NAMES, extract_text_metadata, parse_filename, sha256_file
from app.parsing.models import ParsedDocument


SUPPORTED_EXTENSIONS = {".doc", ".docx", ".pdf", ".xls", ".xlsx"}


def iter_source_files(input_dir: Path) -> Iterable[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    yield from sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("~$")
        ),
        key=lambda item: item.name,
    )


def build_inventory(input_dir: Path) -> list[ParsedDocument]:
    documents: list[ParsedDocument] = []
    seen_ids: set[str] = set()
    sha_to_doc: dict[str, str] = {}
    for path in iter_source_files(input_dir):
        info = parse_filename(path)
        sha256 = sha256_file(path)
        doc_id = info["doc_id"] or f"file_{sha256[:16]}"
        if doc_id in seen_ids:
            doc_id = f"{doc_id}_{sha256[:8]}"
        seen_ids.add(doc_id)
        duplicate_of = sha_to_doc.get(sha256)
        sha_to_doc.setdefault(sha256, doc_id)
        filename_metadata = extract_text_metadata(path.stem, info["title"])
        issuer = next((name for name in ISSUER_NAMES if name in path.stem), filename_metadata["issuer"])
        documents.append(
            ParsedDocument(
                doc_id=doc_id,
                source_seq=info["source_seq"],
                file_name=path.name,
                file_type=path.suffix.lower().lstrip("."),
                file_size=path.stat().st_size,
                sha256=sha256,
                local_path=display_local_path(path),
                absolute_path=path.resolve(),
                title=info["title"],
                source_page_title=info["source_page_title"],
                attachment_title=info["attachment_title"],
                document_family_id=info["document_family_id"],
                issuer=issuer,
                document_no=filename_metadata["document_no"],
                publish_date=filename_metadata["publish_date"],
                publish_date_text=filename_metadata["publish_date_text"],
                duplicate_of_doc_id=duplicate_of,
                metadata_source={
                    "doc_id": "filename_sequence" if info["source_seq"] is not None else "sha256",
                    "title": "filename",
                    "source_page_title": "filename",
                    "attachment_title": "filename",
                    **({"issuer": "filename"} if issuer else {}),
                    **({"document_no": "filename"} if filename_metadata["document_no"] else {}),
                    **({"publish_date": "filename"} if filename_metadata["publish_date"] else {}),
                },
                metadata_confidence={
                    "title": 0.75,
                    "source_page_title": 0.8,
                    "attachment_title": 0.8,
                    **({"issuer": 0.85} if issuer else {}),
                    **({"document_no": 0.85} if filename_metadata["document_no"] else {}),
                    **({"publish_date": 0.8} if filename_metadata["publish_date"] else {}),
                },
            )
        )
    return documents


def write_manifest(path: Path, documents: Iterable[ParsedDocument]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for doc in documents:
            row = {
                "doc_id": doc.doc_id,
                "source_seq": doc.source_seq,
                "title": doc.title,
                "source_page_title": doc.source_page_title,
                "attachment_title": doc.attachment_title,
                "document_family_id": doc.document_family_id,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "sha256": doc.sha256,
                "source_url": doc.source_url,
                "local_path": doc.local_path,
                "duplicate_of_doc_id": doc.duplicate_of_doc_id,
            }
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def inventory_summary(documents: Iterable[ParsedDocument]) -> dict[str, object]:
    docs = list(documents)
    return {
        "total": len(docs),
        "by_type": dict(sorted(Counter(doc.file_type for doc in docs).items())),
        "duplicates": sum(1 for doc in docs if doc.duplicate_of_doc_id),
    }
