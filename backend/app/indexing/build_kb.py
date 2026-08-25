from __future__ import annotations

import json
from pathlib import Path

from app.indexing.chunk_clauses import iter_clause_chunks
from app.indexing.chunk_tables import iter_table_chunks
from app.indexing.metadata_store import init_db, insert_chunks
from app.shared.jsonl import read_jsonl


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

    stats = {
        "parsed_docs": 0,
        "parsed_tables": 0,
        "clause_chunks": 0,
        "table_chunks": 0,
        "total_chunks": 0,
    }
    clause_path = processed_dir / "clause_chunks.jsonl"
    table_path = processed_dir / "table_chunks.jsonl"
    bm25_path = indexes_dir / "bm25_corpus.jsonl"
    con = init_db(processed_dir / "metadata.db")
    try:
        with (
            clause_path.open("w", encoding="utf-8", newline="\n") as clause_file,
            table_path.open("w", encoding="utf-8", newline="\n") as table_file,
            bm25_path.open("w", encoding="utf-8", newline="\n") as bm25_file,
        ):
            def counted_rows(path: Path, key: str):
                for row in read_jsonl(path):
                    stats[key] += 1
                    yield row

            def all_chunks():
                for chunk in iter_clause_chunks(counted_rows(parsed_docs_path, "parsed_docs")):
                    stats["clause_chunks"] += 1
                    stats["total_chunks"] += 1
                    clause_file.write(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                    bm25_file.write(
                        json.dumps(
                            {
                                "chunk_id": chunk.chunk_id,
                                "chunk_type": chunk.chunk_type,
                                "doc_id": chunk.doc_id,
                                "text": chunk.retrieval_text,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    yield chunk
                for chunk in iter_table_chunks(counted_rows(parsed_tables_path, "parsed_tables")):
                    stats["table_chunks"] += 1
                    stats["total_chunks"] += 1
                    table_file.write(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                    bm25_file.write(
                        json.dumps(
                            {
                                "chunk_id": chunk.chunk_id,
                                "chunk_type": chunk.chunk_type,
                                "doc_id": chunk.doc_id,
                                "text": chunk.retrieval_text,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    yield chunk

            insert_chunks(con, all_chunks(), batch_size=1000)
    finally:
        con.close()
    return stats
