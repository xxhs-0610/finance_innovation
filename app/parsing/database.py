from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor, SSCursor

from app.parsing.config import DatabaseConfig
from app.parsing.models import ParseBundle, ParseIssue, ParsedDocument


SCHEMA_VERSION = "001"


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS rag_schema_migrations (
        version VARCHAR(32) PRIMARY KEY,
        applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        description VARCHAR(500) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_parse_runs (
        run_id CHAR(36) PRIMARY KEY,
        parser_version VARCHAR(64) NOT NULL,
        config_hash VARCHAR(64) NULL,
        run_mode VARCHAR(32) NOT NULL,
        input_root TEXT NOT NULL,
        status VARCHAR(32) NOT NULL,
        started_at DATETIME(6) NOT NULL,
        finished_at DATETIME(6) NULL,
        total_files INT NOT NULL DEFAULT 0,
        processed_files INT NOT NULL DEFAULT 0,
        success_files INT NOT NULL DEFAULT 0,
        partial_files INT NOT NULL DEFAULT 0,
        failed_files INT NOT NULL DEFAULT 0,
        skipped_files INT NOT NULL DEFAULT 0,
        summary_json JSON NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_documents (
        doc_id VARCHAR(96) PRIMARY KEY,
        source_seq INT NULL,
        file_name VARCHAR(1000) NOT NULL,
        file_type VARCHAR(16) NOT NULL,
        file_size BIGINT UNSIGNED NOT NULL,
        sha256 CHAR(64) NOT NULL,
        local_path TEXT NOT NULL,
        title VARCHAR(1000) NULL,
        source_page_title VARCHAR(1000) NULL,
        attachment_title VARCHAR(1000) NULL,
        document_family_id VARCHAR(96) NULL,
        issuer VARCHAR(512) NULL,
        document_no VARCHAR(255) NULL,
        publish_date DATE NULL,
        publish_date_text VARCHAR(128) NULL,
        source_url TEXT NULL,
        page_count INT NULL,
        sheet_count INT NULL,
        language VARCHAR(32) NOT NULL DEFAULT 'zh-CN',
        parse_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        parser_name VARCHAR(128) NULL,
        parser_version VARCHAR(64) NULL,
        duplicate_of_doc_id VARCHAR(96) NULL,
        metadata_source JSON NULL,
        metadata_confidence JSON NULL,
        last_run_id CHAR(36) NULL,
        last_error TEXT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        INDEX idx_documents_sha256 (sha256),
        INDEX idx_documents_status (parse_status),
        INDEX idx_documents_type (file_type),
        INDEX idx_documents_source_seq (source_seq),
        INDEX idx_documents_family (document_family_id),
        INDEX idx_documents_publish_date (publish_date),
        INDEX idx_documents_title (title(191)),
        INDEX idx_documents_issuer (issuer(191))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_document_blocks (
        block_id VARCHAR(160) PRIMARY KEY,
        doc_id VARCHAR(96) NOT NULL,
        sequence_no INT NOT NULL,
        block_type VARCHAR(32) NOT NULL,
        page_no INT NULL,
        heading_level INT NULL,
        section_path JSON NULL,
        clause_no VARCHAR(128) NULL,
        text LONGTEXT NOT NULL,
        bbox JSON NULL,
        source_locator JSON NULL,
        content_hash CHAR(64) NOT NULL,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        INDEX idx_blocks_doc_active_seq (doc_id, is_active, sequence_no),
        INDEX idx_blocks_clause (clause_no),
        INDEX idx_blocks_type (block_type),
        CONSTRAINT fk_blocks_document FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_tables (
        table_id VARCHAR(160) PRIMARY KEY,
        doc_id VARCHAR(96) NOT NULL,
        sequence_no INT NOT NULL,
        source_kind VARCHAR(32) NOT NULL,
        table_index INT NOT NULL,
        table_name VARCHAR(1000) NULL,
        sheet_name VARCHAR(512) NULL,
        page_no INT NULL,
        range_ref VARCHAR(128) NULL,
        unit VARCHAR(128) NULL,
        period VARCHAR(128) NULL,
        header_rows JSON NULL,
        row_count INT NOT NULL DEFAULT 0,
        column_count INT NOT NULL DEFAULT 0,
        merged_ranges JSON NULL,
        source_locator JSON NULL,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        INDEX idx_tables_doc_active (doc_id, is_active),
        INDEX idx_tables_sheet (sheet_name(191)),
        INDEX idx_tables_name (table_name(191)),
        INDEX idx_tables_period (period),
        CONSTRAINT fk_tables_document FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_table_cells (
        cell_id VARCHAR(190) PRIMARY KEY,
        table_id VARCHAR(160) NOT NULL,
        doc_id VARCHAR(96) NOT NULL,
        row_index INT NOT NULL,
        col_index INT NOT NULL,
        cell_ref VARCHAR(64) NOT NULL,
        raw_value LONGTEXT NULL,
        display_value LONGTEXT NULL,
        normalized_value DECIMAL(65,18) NULL,
        value_type VARCHAR(32) NOT NULL,
        formula LONGTEXT NULL,
        metric_name TEXT NULL,
        period VARCHAR(128) NULL,
        unit VARCHAR(128) NULL,
        row_header TEXT NULL,
        col_header TEXT NULL,
        is_header TINYINT(1) NOT NULL DEFAULT 0,
        is_merged TINYINT(1) NOT NULL DEFAULT 0,
        merged_anchor_ref VARCHAR(64) NULL,
        source_locator JSON NULL,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        INDEX idx_cells_table_position (table_id, row_index, col_index),
        INDEX idx_cells_doc_active (doc_id, is_active),
        INDEX idx_cells_metric (metric_name(191)),
        INDEX idx_cells_period (period),
        CONSTRAINT fk_cells_table FOREIGN KEY (table_id) REFERENCES rag_tables(table_id),
        CONSTRAINT fk_cells_document FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_parse_issues (
        issue_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        run_id CHAR(36) NULL,
        doc_id VARCHAR(96) NOT NULL,
        stage VARCHAR(64) NOT NULL,
        severity VARCHAR(16) NOT NULL,
        error_code VARCHAR(128) NOT NULL,
        message TEXT NOT NULL,
        retryable TINYINT(1) NOT NULL DEFAULT 0,
        context_json JSON NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        INDEX idx_issues_doc (doc_id),
        INDEX idx_issues_run (run_id),
        INDEX idx_issues_severity (severity),
        INDEX idx_issues_retryable (retryable),
        CONSTRAINT fk_issues_document FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ParsingDatabase:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    def _connect(self, database: str | None = None, cursorclass=DictCursor):
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.username,
            password=self.config.password,
            database=database,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=10,
            # The largest supplied workbook contains more than one million
            # cells and a single-document transaction can legitimately take
            # several minutes while MySQL maintains indexes.
            read_timeout=1800,
            write_timeout=1800,
            cursorclass=cursorclass,
        )

    def check(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION() AS version, @@character_set_server AS charset, @@collation_server AS collation")
                server = cursor.fetchone()
                cursor.execute("SHOW DATABASES LIKE %s", (self.config.database,))
                exists = cursor.fetchone() is not None
            return {**server, "database": self.config.database, "database_exists": exists}
        finally:
            connection.close()

    def init_database(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.config.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            connection.commit()
        finally:
            connection.close()
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                for statement in DDL_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO rag_schema_migrations (version, description) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE description=VALUES(description)",
                    (SCHEMA_VERSION, "Initial module-1 parsing schema"),
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_inventory(self, documents: Iterable[ParsedDocument]) -> None:
        sql = """
            INSERT INTO rag_documents (
                doc_id, source_seq, file_name, file_type, file_size, sha256, local_path,
                title, source_page_title, attachment_title, document_family_id,
                source_url, language, parse_status, duplicate_of_doc_id,
                metadata_source, metadata_confidence
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            ) ON DUPLICATE KEY UPDATE
                parse_status=IF(sha256 <> VALUES(sha256), 'pending', parse_status),
                source_seq=VALUES(source_seq), file_name=VALUES(file_name), file_type=VALUES(file_type),
                file_size=VALUES(file_size), sha256=VALUES(sha256), local_path=VALUES(local_path),
                source_page_title=VALUES(source_page_title), attachment_title=VALUES(attachment_title),
                document_family_id=VALUES(document_family_id), duplicate_of_doc_id=VALUES(duplicate_of_doc_id)
        """
        connection = self._connect(self.config.database)
        try:
            rows = []
            for doc in documents:
                rows.append(
                    (
                        doc.doc_id,
                        doc.source_seq,
                        doc.file_name,
                        doc.file_type,
                        doc.file_size,
                        doc.sha256,
                        doc.local_path,
                        doc.title,
                        doc.source_page_title,
                        doc.attachment_title,
                        doc.document_family_id,
                        doc.source_url,
                        doc.language,
                        doc.parse_status,
                        doc.duplicate_of_doc_id,
                        _json(doc.metadata_source),
                        _json(doc.metadata_confidence),
                    )
                )
            with connection.cursor() as cursor:
                cursor.executemany(sql, rows)
            connection.commit()
        finally:
            connection.close()

    def start_run(self, parser_version: str, run_mode: str, input_root: str, total_files: int) -> str:
        run_id = str(uuid.uuid4())
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE rag_parse_runs SET status='aborted', finished_at=%s "
                    "WHERE status='running' AND finished_at IS NULL",
                    (datetime.now(),),
                )
                cursor.execute(
                    """
                    INSERT INTO rag_parse_runs (
                        run_id, parser_version, run_mode, input_root, status, started_at, total_files
                    ) VALUES (%s,%s,%s,%s,'running',%s,%s)
                    """,
                    (run_id, parser_version, run_mode, input_root, datetime.now(), total_files),
                )
            connection.commit()
        finally:
            connection.close()
        return run_id

    def finish_run(self, run_id: str, counters: dict[str, int], summary: dict[str, Any] | None = None) -> None:
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_parse_runs SET status=%s, finished_at=%s, processed_files=%s,
                        success_files=%s, partial_files=%s, failed_files=%s, skipped_files=%s,
                        summary_json=%s WHERE run_id=%s
                    """,
                    (
                        "completed" if counters.get("failed", 0) == 0 else "completed_with_errors",
                        datetime.now(),
                        counters.get("processed", 0),
                        counters.get("success", 0),
                        counters.get("partial", 0),
                        counters.get("failed", 0),
                        counters.get("skipped", 0),
                        _json(summary or {}),
                        run_id,
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def should_parse(self, doc: ParsedDocument, parser_version: str, force: bool = False, retry_failed: bool = False) -> bool:
        if force:
            return True
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT sha256, parse_status, parser_version FROM rag_documents WHERE doc_id=%s", (doc.doc_id,)
                )
                row = cursor.fetchone()
            if not row:
                return True
            if retry_failed:
                return row["parse_status"] in {"failed", "partial"}
            return not (
                row["sha256"] == doc.sha256
                and row["parse_status"] in {"success", "partial"}
                and row["parser_version"] == parser_version
            )
        finally:
            connection.close()

    def persist_bundle(self, bundle: ParseBundle, run_id: str, cell_batch_size: int = 1000) -> dict[str, int]:
        connection = self._connect(self.config.database)
        counts = {"blocks": 0, "tables": 0, "cells": 0, "issues": 0}
        try:
            with connection.cursor() as cursor:
                self._upsert_document(cursor, bundle.document, run_id)
                cursor.execute("UPDATE rag_document_blocks SET is_active=0 WHERE doc_id=%s", (bundle.document.doc_id,))
                cursor.execute("UPDATE rag_tables SET is_active=0 WHERE doc_id=%s", (bundle.document.doc_id,))
                cursor.execute("UPDATE rag_table_cells SET is_active=0 WHERE doc_id=%s", (bundle.document.doc_id,))
                for block in bundle.blocks:
                    cursor.execute(
                        """
                        INSERT INTO rag_document_blocks (
                            block_id, doc_id, sequence_no, block_type, page_no, heading_level,
                            section_path, clause_no, text, bbox, source_locator, content_hash, is_active
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
                        ON DUPLICATE KEY UPDATE sequence_no=VALUES(sequence_no), block_type=VALUES(block_type),
                            page_no=VALUES(page_no), heading_level=VALUES(heading_level),
                            section_path=VALUES(section_path), clause_no=VALUES(clause_no), text=VALUES(text),
                            bbox=VALUES(bbox), source_locator=VALUES(source_locator),
                            content_hash=VALUES(content_hash), is_active=1
                        """,
                        (
                            block.block_id,
                            block.doc_id,
                            block.sequence_no,
                            block.block_type,
                            block.page_no,
                            block.heading_level,
                            _json(block.section_path),
                            block.clause_no,
                            block.text,
                            _json(block.bbox) if block.bbox else None,
                            _json(block.source_locator),
                            block.content_hash,
                        ),
                    )
                    counts["blocks"] += 1
                for table in bundle.tables:
                    cursor.execute(
                        """
                        INSERT INTO rag_tables (
                            table_id, doc_id, sequence_no, source_kind, table_index, table_name,
                            sheet_name, page_no, range_ref, unit, period, header_rows, row_count,
                            column_count, merged_ranges, source_locator, is_active
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
                        ON DUPLICATE KEY UPDATE sequence_no=VALUES(sequence_no), source_kind=VALUES(source_kind),
                            table_index=VALUES(table_index), table_name=VALUES(table_name),
                            sheet_name=VALUES(sheet_name), page_no=VALUES(page_no), range_ref=VALUES(range_ref),
                            unit=VALUES(unit), period=VALUES(period), header_rows=VALUES(header_rows),
                            row_count=VALUES(row_count), column_count=VALUES(column_count),
                            merged_ranges=VALUES(merged_ranges), source_locator=VALUES(source_locator), is_active=1
                        """,
                        (
                            table.table_id,
                            table.doc_id,
                            table.sequence_no,
                            table.source_kind,
                            table.table_index,
                            table.table_name,
                            table.sheet_name,
                            table.page_no,
                            table.range_ref,
                            table.unit,
                            table.period,
                            _json(table.header_rows),
                            table.row_count,
                            table.column_count,
                            _json(table.merged_ranges),
                            _json(table.source_locator),
                        ),
                    )
                    counts["tables"] += 1
                    batch: list[tuple[Any, ...]] = []
                    for cell in table.iter_cells():
                        batch.append(
                            (
                                cell.cell_id,
                                cell.table_id,
                                cell.doc_id,
                                cell.row_index,
                                cell.col_index,
                                cell.cell_ref,
                                cell.raw_value,
                                cell.display_value,
                                cell.normalized_value,
                                cell.value_type,
                                cell.formula,
                                cell.metric_name,
                                cell.period,
                                cell.unit,
                                cell.row_header,
                                cell.col_header,
                                int(cell.is_header),
                                int(cell.is_merged),
                                cell.merged_anchor_ref,
                                _json(cell.source_locator),
                            )
                        )
                        if len(batch) >= cell_batch_size:
                            self._insert_cell_batch(cursor, batch)
                            counts["cells"] += len(batch)
                            batch.clear()
                    if batch:
                        self._insert_cell_batch(cursor, batch)
                        counts["cells"] += len(batch)
                for issue in bundle.issues:
                    self._insert_issue(cursor, issue, run_id)
                    counts["issues"] += 1
            connection.commit()
            return counts
        except Exception:
            try:
                connection.rollback()
            except Exception:
                # The original exception may be a dropped connection. In that
                # case MySQL rolls the open transaction back server-side.
                pass
            raise
        finally:
            connection.close()

    def mark_failed(self, document: ParsedDocument, run_id: str, exc: Exception) -> None:
        document.parse_status = "failed"
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                self._upsert_document(cursor, document, run_id, last_error=str(exc))
                self._insert_issue(
                    cursor,
                    ParseIssue(
                        document.doc_id,
                        "pipeline",
                        "error",
                        type(exc).__name__.upper(),
                        str(exc),
                        retryable=True,
                    ),
                    run_id,
                )
            connection.commit()
        finally:
            connection.close()

    def _upsert_document(self, cursor, doc: ParsedDocument, run_id: str, last_error: str | None = None) -> None:
        cursor.execute(
            """
            INSERT INTO rag_documents (
                doc_id, source_seq, file_name, file_type, file_size, sha256, local_path, title,
                source_page_title, attachment_title, document_family_id, issuer, document_no,
                publish_date, publish_date_text, source_url, page_count, sheet_count, language,
                parse_status, parser_name, parser_version, duplicate_of_doc_id, metadata_source,
                metadata_confidence, last_run_id, last_error
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE source_seq=VALUES(source_seq), file_name=VALUES(file_name),
                file_type=VALUES(file_type), file_size=VALUES(file_size), sha256=VALUES(sha256),
                local_path=VALUES(local_path), title=VALUES(title), source_page_title=VALUES(source_page_title),
                attachment_title=VALUES(attachment_title), document_family_id=VALUES(document_family_id),
                issuer=VALUES(issuer), document_no=VALUES(document_no), publish_date=VALUES(publish_date),
                publish_date_text=VALUES(publish_date_text), source_url=VALUES(source_url),
                page_count=VALUES(page_count), sheet_count=VALUES(sheet_count), language=VALUES(language),
                parse_status=VALUES(parse_status), parser_name=VALUES(parser_name),
                parser_version=VALUES(parser_version), duplicate_of_doc_id=VALUES(duplicate_of_doc_id),
                metadata_source=VALUES(metadata_source), metadata_confidence=VALUES(metadata_confidence),
                last_run_id=VALUES(last_run_id), last_error=VALUES(last_error)
            """,
            (
                doc.doc_id,
                doc.source_seq,
                doc.file_name,
                doc.file_type,
                doc.file_size,
                doc.sha256,
                doc.local_path,
                doc.title,
                doc.source_page_title,
                doc.attachment_title,
                doc.document_family_id,
                doc.issuer,
                doc.document_no,
                doc.publish_date,
                doc.publish_date_text,
                doc.source_url,
                doc.page_count,
                doc.sheet_count,
                doc.language,
                doc.parse_status,
                doc.parser_name,
                doc.parser_version,
                doc.duplicate_of_doc_id,
                _json(doc.metadata_source),
                _json(doc.metadata_confidence),
                run_id,
                last_error,
            ),
        )

    @staticmethod
    def _insert_cell_batch(cursor, rows: list[tuple[Any, ...]]) -> None:
        cursor.executemany(
            """
            INSERT INTO rag_table_cells (
                cell_id, table_id, doc_id, row_index, col_index, cell_ref, raw_value,
                display_value, normalized_value, value_type, formula, metric_name, period,
                unit, row_header, col_header, is_header, is_merged, merged_anchor_ref,
                source_locator, is_active
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            ON DUPLICATE KEY UPDATE table_id=VALUES(table_id), doc_id=VALUES(doc_id),
                row_index=VALUES(row_index), col_index=VALUES(col_index), cell_ref=VALUES(cell_ref),
                raw_value=VALUES(raw_value), display_value=VALUES(display_value),
                normalized_value=VALUES(normalized_value), value_type=VALUES(value_type),
                formula=VALUES(formula), metric_name=VALUES(metric_name), period=VALUES(period),
                unit=VALUES(unit), row_header=VALUES(row_header), col_header=VALUES(col_header),
                is_header=VALUES(is_header), is_merged=VALUES(is_merged),
                merged_anchor_ref=VALUES(merged_anchor_ref), source_locator=VALUES(source_locator), is_active=1
            """,
            rows,
        )

    @staticmethod
    def _insert_issue(cursor, issue: ParseIssue, run_id: str) -> None:
        cursor.execute(
            """
            INSERT INTO rag_parse_issues (
                run_id, doc_id, stage, severity, error_code, message, retryable, context_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                run_id,
                issue.doc_id,
                issue.stage,
                issue.severity,
                issue.error_code,
                issue.message,
                int(issue.retryable),
                _json(issue.context),
            ),
        )

    def stream_query(self, sql: str, params: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
        connection = self._connect(self.config.database, cursorclass=SSCursor)
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            for row in cursor:
                yield row
        finally:
            cursor.close()
            connection.close()

    def report_data(self) -> dict[str, Any]:
        connection = self._connect(self.config.database)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM rag_documents")
                document_total = cursor.fetchone()["total"]
                cursor.execute("SELECT COUNT(*) AS total FROM rag_documents WHERE duplicate_of_doc_id IS NOT NULL")
                duplicate_total = cursor.fetchone()["total"]
                cursor.execute("SELECT file_type, COUNT(*) AS total FROM rag_documents GROUP BY file_type ORDER BY file_type")
                by_type = cursor.fetchall()
                cursor.execute("SELECT parse_status, COUNT(*) AS total FROM rag_documents GROUP BY parse_status")
                by_status = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) AS total FROM rag_document_blocks WHERE is_active=1")
                block_total = cursor.fetchone()["total"]
                cursor.execute("SELECT COUNT(*) AS total FROM rag_tables WHERE is_active=1")
                table_total = cursor.fetchone()["total"]
                cursor.execute("SELECT COUNT(*) AS total FROM rag_table_cells WHERE is_active=1")
                cell_total = cursor.fetchone()["total"]
                cursor.execute("SELECT severity, COUNT(*) AS total FROM rag_parse_issues GROUP BY severity")
                issues = cursor.fetchall()
                cursor.execute(
                    "SELECT doc_id, file_name, parse_status, last_error FROM rag_documents "
                    "WHERE parse_status IN ('partial','failed') ORDER BY source_seq"
                )
                problem_files = cursor.fetchall()
            return {
                "documents": document_total,
                "duplicates": duplicate_total,
                "by_type": by_type,
                "by_status": by_status,
                "blocks": block_total,
                "tables": table_total,
                "cells": cell_total,
                "issues": issues,
                "problem_files": problem_files,
            }
        finally:
            connection.close()
