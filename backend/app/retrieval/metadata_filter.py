from __future__ import annotations

from dataclasses import dataclass

from app.schemas.chunk_schema import SearchResult


SUPPORTED_FILTERS = ("doc_id", "title", "issuer", "publish_date")


@dataclass(frozen=True, slots=True)
class FilterAttempt:
    name: str
    filters: dict[str, str]
    relaxed_filters: tuple[str, ...] = ()


def build_filter_attempts(filters: dict[str, str]) -> list[FilterAttempt]:
    strict_filters = {
        key: value
        for key in SUPPORTED_FILTERS
        if (value := filters.get(key))
    }
    attempts = [FilterAttempt(name="strict", filters=strict_filters)]

    # A question year may describe the applicable period rather than publication date.
    # Keep explicit document and issuer constraints when retrying.
    if "publish_date" in strict_filters:
        relaxed = dict(strict_filters)
        relaxed.pop("publish_date")
        attempts.append(
            FilterAttempt(
                name="relaxed_publish_date",
                filters=relaxed,
                relaxed_filters=("publish_date",),
            )
        )
    return attempts


def attach_filter_diagnostics(
    result: SearchResult, attempt: FilterAttempt
) -> SearchResult:
    metadata = dict(result.metadata)
    metadata["filtering"] = {
        "applied_filters": dict(attempt.filters),
        "relaxed_filters": list(attempt.relaxed_filters),
        "attempt": attempt.name,
    }
    return SearchResult(
        chunk_id=result.chunk_id,
        chunk_type=result.chunk_type,
        score=result.score,
        text=result.text,
        source=result.source,
        metadata=metadata,
    )
