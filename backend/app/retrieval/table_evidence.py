from __future__ import annotations

import re
from dataclasses import replace

from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis


YEAR_RE = re.compile(r"(?:19|20)\d{2}")
YEAR_MONTH_RE = re.compile(
    r"((?:19|20)\d{2})\s*(?:年|-)?\s*(0?[1-9]|1[0-2])(?:月)?"
)
MONTH_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])月")
QUARTER_RE = re.compile(r"第?([一二三四1234])季度")
Q_RE = re.compile(r"(?:19|20)\d{2}[Qq]([1-4])")
NORMALIZE_RE = re.compile(r"[\s，。！？?；;：:、（）()【】\[\]<>《》_-]+")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[%％])?$")
QUARTER_MAP = {"一": "1", "二": "2", "三": "3", "四": "4"}


def normalize_period(value: object, *, context_year: str = "") -> str:
    raw = str(value or "")
    year_month_match = YEAR_MONTH_RE.fullmatch(raw.strip())
    if year_month_match:
        return f"{year_month_match.group(1)}-{int(year_month_match.group(2)):02d}"
    context_month_match = MONTH_RE.search(raw)
    if context_month_match and context_year:
        return f"{context_year}-{int(context_month_match.group(1)):02d}"
    text = NORMALIZE_RE.sub("", raw).upper()
    year_match = YEAR_RE.search(text)
    year = year_match.group(0) if year_match else context_year
    q_match = Q_RE.search(text)
    if q_match and year:
        return f"{year}Q{q_match.group(1)}"
    quarter_match = QUARTER_RE.search(text)
    if quarter_match and year:
        quarter = QUARTER_MAP.get(quarter_match.group(1), quarter_match.group(1))
        return f"{year}Q{quarter}"
    return year or text


def requested_period(analysis: QueryAnalysis) -> str:
    normalized = analysis.entities.get("normalized_period", "")
    if normalized:
        return normalize_period(normalized)
    return normalize_period(analysis.entities.get("period", ""))


def candidate_year(candidate: SearchResult) -> str:
    metadata = candidate.metadata
    for value in (
        metadata.get("period"),
        metadata.get("col_header"),
        candidate.source.title,
        candidate.source.table_name,
        candidate.text,
        candidate.source.publish_date,
    ):
        match = YEAR_RE.search(str(value or ""))
        if match:
            return match.group(0)
    return ""


def matching_period_values(
    candidate: SearchResult, normalized_period: str
) -> list[dict]:
    if candidate.chunk_type != "table" or not normalized_period:
        return []
    year = candidate_year(candidate)
    matched: list[dict] = []
    for item in candidate.metadata.get("values") or []:
        if not isinstance(item, dict):
            continue
        item_year = _first_year(item.get("period")) or year
        item_periods = (
            normalize_period(item.get("period"), context_year=item_year),
            normalize_period(item.get("header"), context_year=item_year),
            normalize_period(item.get("col_header"), context_year=item_year),
        )
        if normalized_period in item_periods:
            matched.append(item)
    return matched


def table_matches_period(candidate: SearchResult, normalized_period: str) -> bool:
    if candidate.chunk_type != "table" or not normalized_period:
        return True
    metadata = candidate.metadata
    year = candidate_year(candidate)
    direct_periods = {
        normalize_period(metadata.get("period"), context_year=year),
        normalize_period(metadata.get("col_header"), context_year=year),
    }
    if normalized_period in direct_periods:
        return True
    if "Q" in normalized_period:
        return bool(matching_period_values(candidate, normalized_period))
    return year == normalized_period


def narrow_table_evidence(
    candidate: SearchResult, analysis: QueryAnalysis
) -> SearchResult:
    normalized_period = requested_period(analysis)
    if candidate.chunk_type != "table" or not normalized_period:
        return candidate
    matched_values = matching_period_values(candidate, normalized_period)
    selectable_values = usable_table_value_items(
        candidate.metadata, values=matched_values
    )
    # A quarter row usually has one cell for the requested quarter. Monthly
    # regional tables may carry several values for the same month; without a
    # requested column dimension, selecting the first cell would be unsafe.
    if len(selectable_values) > 1:
        metadata = dict(candidate.metadata)
        metadata["table_cell_selection"] = {
            "status": "ambiguous_dimension",
            "requested_period": normalized_period,
            "original_cell_ref": candidate.source.cell_ref,
            "candidate_value_count": len(selectable_values),
            "dimension_options": _dimension_options(selectable_values),
            "value_preserved_as_source": True,
        }
        return SearchResult(
            chunk_id=candidate.chunk_id,
            chunk_type=candidate.chunk_type,
            score=candidate.score,
            text=candidate.text,
            source=candidate.source,
            metadata=metadata,
        )
    if len(selectable_values) != 1:
        return candidate

    selected = selectable_values[0]
    cell_ref = str(selected.get("cell_ref") or candidate.source.cell_ref)
    metadata = dict(candidate.metadata)
    original_cell_ref = candidate.source.cell_ref
    metadata["values"] = [dict(selected)]
    metadata["value"] = str(selected.get("value") or "")
    if selected.get("value_numeric") is not None:
        metadata["value_numeric"] = str(selected["value_numeric"])
    metadata["period"] = normalized_period
    metadata["col_header"] = str(
        selected.get("header") or selected.get("col_header") or ""
    )
    if selected.get("unit"):
        metadata["unit"] = str(selected["unit"])
    metadata["table_cell_selection"] = {
        "status": "exact_period_cell",
        "requested_period": normalized_period,
        "original_cell_ref": original_cell_ref,
        "selected_cell_ref": cell_ref,
        "selected_value_count": 1,
        "value_preserved_as_source": True,
    }

    metric = str(metadata.get("metric_name") or metadata.get("row_header") or "")
    table_name = candidate.source.table_name or candidate.source.title
    unit = str(metadata.get("unit") or "")
    value = metadata["value"]
    text_parts = [table_name, metric, normalized_period, f"{cell_ref}={value}"]
    if unit:
        text_parts.append(f"单位：{unit}")
    return SearchResult(
        chunk_id=candidate.chunk_id,
        chunk_type=candidate.chunk_type,
        score=candidate.score,
        text=" | ".join(part for part in text_parts if part),
        source=replace(candidate.source, cell_ref=cell_ref),
        metadata=metadata,
    )


def _first_year(value: object) -> str:
    match = YEAR_RE.search(str(value or ""))
    return match.group(0) if match else ""


def usable_table_value_items(
    metadata: dict, *, values: list[dict] | None = None
) -> list[dict]:
    """Return actual data cells while excluding row-label cells.

    Module 1 may preserve a row label as the first item in ``values``. Numeric
    cells are preferred; if no numeric cells exist, non-empty values that do
    not merely repeat the metric/row label are retained.
    """

    raw_values = values if values is not None else metadata.get("values") or []
    items = [item for item in raw_values if isinstance(item, dict)]
    labels = {
        _normalize_value(metadata.get("metric_name")),
        _normalize_value(metadata.get("row_header")),
    }
    labels.discard("")

    numeric_items = [item for item in items if _is_numeric_item(item)]
    if numeric_items:
        return numeric_items

    return [
        item
        for item in items
        if _normalize_value(item.get("value"))
        and _normalize_value(item.get("value")) not in labels
    ]


def has_usable_table_value(metadata: dict) -> bool:
    direct_value = _normalize_value(metadata.get("value"))
    labels = {
        _normalize_value(metadata.get("metric_name")),
        _normalize_value(metadata.get("row_header")),
    }
    if direct_value and direct_value not in labels:
        return True
    return bool(usable_table_value_items(metadata))


def _is_numeric_item(item: dict) -> bool:
    if item.get("value_numeric") is not None:
        return True
    value = str(item.get("value") or "").replace(",", "").strip()
    return bool(NUMBER_RE.fullmatch(value))


def _normalize_value(value: object) -> str:
    return NORMALIZE_RE.sub("", str(value or "")).lower()


def _dimension_options(values: list[dict]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for item in values:
        label = str(item.get("header") or item.get("col_header") or "").strip()
        cell_ref = str(item.get("cell_ref") or "").strip()
        option = {"label": label or cell_ref, "cell_ref": cell_ref}
        if option not in options:
            options.append(option)
    return options
