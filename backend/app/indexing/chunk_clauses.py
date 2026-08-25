from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Iterator

from app.indexing.text_utils import clean_text, join_non_empty, normalize_section_path
from app.schemas.chunk_schema import KnowledgeChunk, SourceInfo


def iter_clause_chunks(rows: Iterable[dict]) -> Iterator[KnowledgeChunk]:
    counters: dict[str, int] = {}

    for row in rows:
        doc_id = clean_text(row.get("doc_id"))
        text = clean_text(row.get("text"))
        if not doc_id or not text:
            continue

        counters[doc_id] = counters.get(doc_id, 0) + 1
        source = SourceInfo(
            doc_id=doc_id,
            title=clean_text(row.get("title")),
            issuer=clean_text(row.get("issuer")),
            publish_date=clean_text(row.get("publish_date")),
            source_url=clean_text(row.get("source_url")),
            local_path=clean_text(row.get("local_path")),
            section_path=normalize_section_path(row.get("section_path")),
            clause_no=clean_text(row.get("clause_no")),
        )
        section_text = " ".join(source.section_path)
        retrieval_text = join_non_empty(
            [
                source.title,
                source.issuer,
                source.publish_date,
                section_text,
                source.clause_no,
                text,
            ]
        )
        chunk_id = f"{doc_id}_clause_{counters[doc_id]:04d}"
        yield KnowledgeChunk(
                chunk_id=chunk_id,
                chunk_type="clause",
                doc_id=doc_id,
                text=text,
                retrieval_text=retrieval_text,
                source=source,
                metadata={
                    "section_path": source.section_path,
                    "clause_no": source.clause_no,
                },
            )


def build_clause_chunks(rows: Iterable[dict]) -> list[KnowledgeChunk]:
    return list(iter_clause_chunks(rows))

