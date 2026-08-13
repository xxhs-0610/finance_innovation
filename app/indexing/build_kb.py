from __future__ import annotations

from pathlib import Path

from app.indexing.chunk_clauses import build_clause_chunks
from app.indexing.chunk_tables import build_table_chunks
from app.indexing.metadata_store import build_metadata_db
from app.shared.jsonl import read_jsonl, write_jsonl


def build_kb(
    parsed_docs_path: str | Path,
    parsed_tables_path: str | Path,
    processed_dir: str | Path = "data/processed",
    indexes_dir: str | Path = "indexes",
) -> dict[str, int]:
    processed_dir = Path(processed_dir)
    indexes_dir = Path(indexes_dir)
    parsed_docs_path = Path(parsed_docs_path)
    parsed_tables_path = Path(parsed_tables_path)
    if not parsed_docs_path.exists():
        raise FileNotFoundError(f"Parsed documents file not found: {parsed_docs_path}")
    if not parsed_tables_path.exists():
        raise FileNotFoundError(f"Parsed tables file not found: {parsed_tables_path}")
    processed_dir.mkdir(parents=True, exist_ok=True)
    indexes_dir.mkdir(parents=True, exist_ok=True)

    doc_rows = list(read_jsonl(parsed_docs_path))
    table_rows = list(read_jsonl(parsed_tables_path))
    clause_chunks = build_clause_chunks(doc_rows)
    table_chunks = build_table_chunks(table_rows)
    all_chunks = clause_chunks + table_chunks

    write_jsonl(
        processed_dir / "clause_chunks.jsonl",
        [chunk.to_dict() for chunk in clause_chunks],
    )
    write_jsonl(
        processed_dir / "table_chunks.jsonl",
        [chunk.to_dict() for chunk in table_chunks],
    )
    write_jsonl(
        indexes_dir / "bm25_corpus.jsonl",
        [
            {
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "doc_id": chunk.doc_id,
                "text": chunk.retrieval_text,
            }
            for chunk in all_chunks
        ],
    )
    build_metadata_db(processed_dir / "metadata.db", all_chunks)

    return {
        "parsed_docs": len(doc_rows),
        "parsed_tables": len(table_rows),
        "clause_chunks": len(clause_chunks),
        "table_chunks": len(table_chunks),
        "total_chunks": len(all_chunks),
    }
