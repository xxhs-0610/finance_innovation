from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.indexing.text_utils import augment_for_fts
from app.schemas.chunk_schema import KnowledgeChunk


SCHEMA_SQL = """
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS chunk_fts;

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    chunk_type TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    title TEXT,
    issuer TEXT,
    publish_date TEXT,
    section_path TEXT,
    clause_no TEXT,
    sheet_name TEXT,
    table_name TEXT,
    source_url TEXT,
    local_path TEXT,
    text TEXT NOT NULL,
    retrieval_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    chunk_id UNINDEXED,
    chunk_type UNINDEXED,
    doc_id UNINDEXED,
    title,
    text,
    retrieval_text
);

CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX idx_chunks_type ON chunks(chunk_type);
CREATE INDEX idx_chunks_title ON chunks(title);
CREATE INDEX idx_chunks_issuer ON chunks(issuer);
CREATE INDEX idx_chunks_publish_date ON chunks(publish_date);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL)
    return con


def insert_chunks(con: sqlite3.Connection, chunks: Iterable[KnowledgeChunk], batch_size: int = 1000) -> None:
    chunk_rows = []
    fts_rows = []

    def flush() -> None:
        if not chunk_rows:
            return
        con.executemany(
            """
            INSERT INTO chunks (
                chunk_id, chunk_type, doc_id, title, issuer, publish_date,
                section_path, clause_no, sheet_name, table_name, source_url,
                local_path, text, retrieval_text, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            chunk_rows,
        )
        con.executemany(
            """
            INSERT INTO chunk_fts (
                chunk_id, chunk_type, doc_id, title, text, retrieval_text
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
        con.commit()
        chunk_rows.clear()
        fts_rows.clear()

    for chunk in chunks:
        source = chunk.source
        metadata_json = json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True)
        section_path = json.dumps(source.section_path, ensure_ascii=False)
        chunk_rows.append(
            (
                chunk.chunk_id,
                chunk.chunk_type,
                chunk.doc_id,
                source.title,
                source.issuer,
                source.publish_date,
                section_path,
                source.clause_no,
                source.sheet_name,
                source.table_name,
                source.source_url,
                source.local_path,
                chunk.text,
                augment_for_fts(chunk.retrieval_text),
                metadata_json,
            )
        )
        fts_rows.append(
            (
                chunk.chunk_id,
                chunk.chunk_type,
                chunk.doc_id,
                source.title,
                chunk.text,
                augment_for_fts(chunk.retrieval_text),
            )
        )
        if len(chunk_rows) >= batch_size:
            flush()
    flush()


def build_metadata_db(db_path: str | Path, chunks: Iterable[KnowledgeChunk]) -> None:
    con = init_db(db_path)
    try:
        insert_chunks(con, chunks)
    finally:
        con.close()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
