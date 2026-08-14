from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import groupby
from typing import Any

from app.parsing.common import clean_text, join_non_empty


GENERIC_HEADER_PARTS = {
    "时间",
    "项目",
    "指标",
    "单位",
    "地区",
    "序号",
    "备注",
}


def compact_header(value: Any, *, title: str = "", table_name: str = "") -> str:
    """Remove repeated title/unit prefixes while preserving useful header levels."""
    parts = [clean_text(part) for part in clean_text(value).split("/")]
    result: list[str] = []
    for part in parts:
        if not part or part in {title, table_name} or part.startswith("单位：") or part.startswith("单位:"):
            continue
        if part not in result:
            result.append(part)
    useful = [part for part in result if part not in GENERIC_HEADER_PARTS]
    selected = useful[-2:] if useful else result[-2:]
    return " / ".join(selected)[:240]


def _row_label(cells: list[dict[str, Any]], title: str, table_name: str) -> str:
    candidates: list[str] = []
    for cell in cells:
        row_header = compact_header(cell.get("row_header"), title=title, table_name=table_name)
        if row_header:
            candidates.append(row_header)
    if candidates:
        counts = Counter(candidates)
        return min(counts, key=lambda item: (-counts[item], len(item), item))

    leading: list[str] = []
    for cell in cells:
        if cell.get("normalized_value") is not None or clean_text(cell.get("formula")):
            break
        value = clean_text(cell.get("value"))
        if value and value not in leading:
            leading.append(value)
        if len(leading) >= 3:
            break
    return " / ".join(leading)[:500]


def _item_from_cell(cell: dict[str, Any], title: str, table_name: str) -> dict[str, Any]:
    header = compact_header(cell.get("col_header"), title=title, table_name=table_name)
    item = {
        "header": header or clean_text(cell.get("metric_name")) or clean_text(cell.get("cell_ref")),
        "value": clean_text(cell.get("value")),
        "cell_ref": clean_text(cell.get("cell_ref")),
    }
    for key in ("period", "unit", "formula"):
        value = clean_text(cell.get(key))
        if value:
            item[key] = value
    if cell.get("normalized_value") is not None:
        item["value_numeric"] = cell["normalized_value"]
    return item


def _segments(items: list[dict[str, Any]], max_cells: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), max_cells):
        yield items[start : start + max_cells]


def iter_table_evidence(
    cell_rows: Iterable[dict[str, Any]], *, max_cells_per_evidence: int = 20
) -> Iterator[dict[str, Any]]:
    """Group ordered database cell rows into retrieval-sized row evidence.

    Input must be ordered by ``table_id, row_index, col_index``. Header rows are
    intentionally omitted; table-level evidence is exported separately.
    """
    if max_cells_per_evidence < 1:
        raise ValueError("max_cells_per_evidence must be positive")

    key = lambda row: (clean_text(row.get("table_id")), int(row.get("row_index") or 0))
    for (table_id, row_index), group in groupby(cell_rows, key=key):
        cells = [row for row in group if clean_text(row.get("value"))]
        if not cells or all(bool(row.get("is_header")) for row in cells):
            continue

        first = cells[0]
        title = clean_text(first.get("title"))
        table_name = clean_text(first.get("table_name"))
        row_label = _row_label(cells, title, table_name)
        items = [_item_from_cell(cell, title, table_name) for cell in cells]
        for part_no, values in enumerate(_segments(items, max_cells_per_evidence), start=1):
            pairs = [
                f"{item['header']}={item['value']}" if item.get("header") else item["value"]
                for item in values
            ]
            periods = [clean_text(item.get("period")) for item in values if clean_text(item.get("period"))]
            units = [clean_text(item.get("unit")) for item in values if clean_text(item.get("unit"))]
            cell_refs = [item["cell_ref"] for item in values if item.get("cell_ref")]
            evidence_id = f"{table_id}_row_{row_index:06d}_part_{part_no:03d}"
            retrieval_text = join_non_empty(
                [
                    title,
                    clean_text(first.get("sheet_name")),
                    table_name,
                    row_label,
                    "；".join(pairs),
                    "期间：" + " / ".join(dict.fromkeys(periods)) if periods else "",
                    "单位：" + " / ".join(dict.fromkeys(units)) if units else "",
                ],
                separator=" | ",
            )
            yield {
                "evidence_id": evidence_id,
                "record_type": "table_row",
                "doc_id": clean_text(first.get("doc_id")),
                "title": title,
                "issuer": clean_text(first.get("issuer")),
                "publish_date": first.get("publish_date") or "",
                "source_url": first.get("source_url"),
                "local_path": clean_text(first.get("local_path")),
                "table_id": table_id,
                "sheet_name": clean_text(first.get("sheet_name")),
                "table_name": table_name,
                "page_no": first.get("page_no"),
                "row_index": row_index,
                "part_no": part_no,
                "metric_name": row_label,
                "row_header": row_label,
                "period": " / ".join(dict.fromkeys(periods)),
                "unit": " / ".join(dict.fromkeys(units)),
                "cell_range": f"{cell_refs[0]}:{cell_refs[-1]}" if cell_refs else "",
                "values": values,
                "retrieval_text": retrieval_text,
            }


def table_summary_evidence(row: dict[str, Any]) -> dict[str, Any]:
    table_id = clean_text(row.get("table_id"))
    title = clean_text(row.get("title"))
    sheet_name = clean_text(row.get("sheet_name"))
    table_name = clean_text(row.get("table_name"))
    period = clean_text(row.get("period"))
    unit = clean_text(row.get("unit"))
    range_ref = clean_text(row.get("range_ref"))
    retrieval_text = join_non_empty(
        [
            title,
            sheet_name,
            table_name,
            f"期间：{period}" if period else "",
            f"单位：{unit}" if unit else "",
            f"范围：{range_ref}" if range_ref else "",
            f"规模：{row.get('row_count', 0)}行×{row.get('column_count', 0)}列",
        ],
        separator=" | ",
    )
    return {
        "evidence_id": f"{table_id}_summary",
        "record_type": "table_summary",
        "doc_id": clean_text(row.get("doc_id")),
        "title": title,
        "issuer": clean_text(row.get("issuer")),
        "publish_date": row.get("publish_date") or "",
        "source_url": row.get("source_url"),
        "local_path": clean_text(row.get("local_path")),
        "table_id": table_id,
        "sheet_name": sheet_name,
        "table_name": table_name,
        "page_no": row.get("page_no"),
        "period": period,
        "unit": unit,
        "cell_range": range_ref,
        "row_count": int(row.get("row_count") or 0),
        "column_count": int(row.get("column_count") or 0),
        "retrieval_text": retrieval_text,
    }
