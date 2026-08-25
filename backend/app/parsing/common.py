from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


WHITESPACE_RE = re.compile(r"[\t\r\f\v ]+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        # str(float) uses Python's shortest round-trip representation and does
        # not silently discard meaningful Excel binary-double precision.
        return str(value)
    text = str(value).replace("\u3000", " ").replace("\xa0", " ")
    return WHITESPACE_RE.sub(" ", text).strip()


def join_non_empty(values: Iterable[Any], separator: str = " / ") -> str:
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in result:
            result.append(text)
    return separator.join(result)


def normalize_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            decimal_value = Decimal(str(value))
            if decimal_value.is_finite():
                return decimal_value
        except (InvalidOperation, ValueError):
            return None
    text = clean_text(value).replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        return None
    try:
        decimal_value = Decimal(text)
        return decimal_value if decimal_value.is_finite() else None
    except InvalidOperation:
        return None


def infer_value_type(value: Any, formula: str = "") -> str:
    if formula:
        return "formula"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date)):
        return "date"
    if normalize_decimal(value) is not None:
        return "number"
    return "text"


def heading_rows_from_matrix(rows: list[list[Any]], max_scan: int = 30) -> list[int]:
    if not rows:
        return []
    data_start = None
    for index, row in enumerate(rows[:max_scan], start=1):
        nonempty = [value for value in row if clean_text(value)]
        numeric = [value for value in nonempty if normalize_decimal(value) is not None]
        text = [value for value in nonempty if normalize_decimal(value) is None]
        if len(nonempty) >= 2 and numeric and text:
            data_start = index
            break
    if data_start is None:
        return [1] if rows else []
    return list(range(1, min(max(1, data_start - 1), 10) + 1))
