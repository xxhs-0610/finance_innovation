from __future__ import annotations

from collections.abc import Iterable

from app.indexing.text_utils import clean_text, join_non_empty
from app.schemas.chunk_schema import KnowledgeChunk, SourceInfo


def build_table_chunks(rows: Iterable[dict]) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    counters: dict[str, int] = {}

    for row in rows:
        doc_id = clean_text(row.get("doc_id"))
        metric_name = clean_text(row.get("metric_name"))
        value = clean_text(row.get("value"))
        if not doc_id or not (metric_name or value):
            continue

        counters[doc_id] = counters.get(doc_id, 0) + 1
        source = SourceInfo(
            doc_id=doc_id,
            title=clean_text(row.get("title")),
            issuer=clean_text(row.get("issuer")),
            publish_date=clean_text(row.get("publish_date")),
            source_url=clean_text(row.get("source_url")),
            local_path=clean_text(row.get("local_path")),
            sheet_name=clean_text(row.get("sheet_name")),
            table_name=clean_text(row.get("table_name")),
            cell_ref=clean_text(row.get("cell_ref")),
        )
        period = clean_text(row.get("period"))
        unit = clean_text(row.get("unit"))
        row_header = clean_text(row.get("row_header"))
        col_header = clean_text(row.get("col_header"))
        text = join_non_empty(
            [
                f"表名：{source.table_name}" if source.table_name else "",
                f"指标：{metric_name}" if metric_name else "",
                f"期间：{period}" if period else "",
                f"单位：{unit}" if unit else "",
                f"数值：{value}" if value else "",
                f"行表头：{row_header}" if row_header else "",
                f"列表头：{col_header}" if col_header else "",
            ]
        )
        retrieval_text = join_non_empty(
            [
                source.title,
                source.issuer,
                source.publish_date,
                source.sheet_name,
                source.table_name,
                metric_name,
                period,
                unit,
                value,
                row_header,
                col_header,
            ]
        )
        chunk_id = f"{doc_id}_table_{counters[doc_id]:04d}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                chunk_type="table",
                doc_id=doc_id,
                text=text,
                retrieval_text=retrieval_text,
                source=source,
                metadata={
                    "sheet_name": source.sheet_name,
                    "table_name": source.table_name,
                    "metric_name": metric_name,
                    "period": period,
                    "unit": unit,
                    "value": value,
                    "row_header": row_header,
                    "col_header": col_header,
                    "cell_ref": source.cell_ref,
                },
            )
        )

    return chunks

