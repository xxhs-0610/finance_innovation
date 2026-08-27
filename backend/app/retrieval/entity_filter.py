from __future__ import annotations

import re

from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis
from app.retrieval.query_parser import METRICS
from app.retrieval.table_evidence import (
    candidate_year,
    requested_period,
    table_matches_period,
)


YEAR_RE = re.compile(r"(?:19|20)\d{2}")
BANK_TIER_RE = re.compile(r"第[一二三]档(?:商业)?银行")
TEXT_NORMALIZE_RE = re.compile(r"[^0-9A-Za-z%％\u4e00-\u9fff]+")


def apply_entity_filters(
    analysis: QueryAnalysis, candidates: list[SearchResult]
) -> list[SearchResult]:
    clause_no = analysis.entities.get("clause_no", "")
    start_year = _to_year(analysis.entities.get("start_year"))
    end_year = _to_year(analysis.entities.get("end_year"))
    exact_period = requested_period(analysis) if analysis.query_type == "table_lookup" else ""
    bank_tier = analysis.entities.get("bank_tier", "")
    subject_entity = analysis.entities.get("subject_entity", "")
    strict_metric = analysis.entities.get("metric", "") if analysis.query_type in {
        "table_lookup",
        "clause_threshold",
    } else ""
    if (
        not clause_no
        and start_year is None
        and end_year is None
        and not exact_period
        and not bank_tier
        and not subject_entity
        and not strict_metric
    ):
        return candidates

    filtered: list[SearchResult] = []
    for candidate in candidates:
        checked_fields: dict[str, str | int] = {}
        if clause_no:
            if candidate.chunk_type != "clause":
                continue
            if _normalize_clause(candidate.source.clause_no) != _normalize_clause(
                clause_no
            ):
                continue
            checked_fields["clause_no"] = clause_no

        if start_year is not None or end_year is not None:
            matched_year = _candidate_year(candidate)
            if matched_year is None:
                continue
            lower = start_year if start_year is not None else matched_year
            upper = end_year if end_year is not None else matched_year
            if matched_year < lower or matched_year > upper:
                continue
            checked_fields["candidate_year"] = matched_year
            if start_year is not None:
                checked_fields["start_year"] = start_year
            if end_year is not None:
                checked_fields["end_year"] = end_year

        if exact_period:
            if candidate.chunk_type != "table" or not table_matches_period(
                candidate, exact_period
            ):
                continue
            checked_fields["requested_period"] = exact_period
            exact_year = candidate_year(candidate)
            if exact_year:
                checked_fields["candidate_year"] = int(exact_year)

        if bank_tier:
            candidate_tiers = _candidate_bank_tiers(candidate)
            if analysis.query_type == "clause_threshold":
                # A tier-specific threshold must be proved by tier-specific
                # evidence. A generic or unlabelled clause may still be
                # relevant background, but it is not sufficient to answer a
                # question about one concrete regulatory tier.
                if bank_tier not in candidate_tiers:
                    continue
            elif candidate_tiers and bank_tier not in candidate_tiers:
                continue
            checked_fields["bank_tier"] = bank_tier
            if candidate_tiers:
                checked_fields["candidate_bank_tiers"] = ",".join(candidate_tiers)

        if subject_entity:
            expected_subject = _normalize_text(subject_entity)
            if not expected_subject or expected_subject not in _candidate_scope_text(candidate):
                continue
            checked_fields["subject_entity"] = subject_entity

        if strict_metric:
            if not _candidate_matches_metric(candidate, strict_metric):
                continue
            checked_fields["metric"] = strict_metric

        metadata = dict(candidate.metadata)
        metadata["entity_filtering"] = {
            "matched": True,
            "checked_fields": checked_fields,
        }
        filtered.append(
            SearchResult(
                chunk_id=candidate.chunk_id,
                chunk_type=candidate.chunk_type,
                score=candidate.score,
                text=candidate.text,
                source=candidate.source,
                metadata=metadata,
            )
        )
    return filtered


def _candidate_year(candidate: SearchResult) -> int | None:
    if candidate.chunk_type == "table":
        year = candidate_year(candidate)
        if year:
            return int(year)
    return _to_year(candidate.source.publish_date)


def _to_year(value: object) -> int | None:
    match = YEAR_RE.search(str(value or ""))
    return int(match.group(0)) if match else None


def _normalize_clause(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _candidate_bank_tiers(candidate: SearchResult) -> list[str]:
    scope_text = " ".join(
        [
            candidate.source.title,
            *candidate.source.section_path,
            candidate.text,
        ]
    )
    tiers: list[str] = []
    for match in BANK_TIER_RE.finditer(scope_text):
        value = match.group(0)
        if "第一档" in value:
            normalized = "第一档商业银行"
        elif "第二档" in value:
            normalized = "第二档商业银行"
        else:
            normalized = "第三档商业银行"
        if normalized not in tiers:
            tiers.append(normalized)
    return tiers


def _candidate_matches_metric(candidate: SearchResult, metric: str) -> bool:
    expected = _normalize_text(metric)
    if candidate.chunk_type == "table":
        actual = _normalize_text(
            str(
                candidate.metadata.get("metric_name")
                or candidate.metadata.get("row_header")
                or ""
            )
        )
        if not expected:
            return False
        if actual == expected:
            return True
        known_metrics = {_normalize_text(item) for item in METRICS}
        if actual in known_metrics:
            return False
        table_scope = _normalize_text(
            " ".join([candidate.source.title, candidate.source.table_name])
        )
        return expected in table_scope
    scope_text = " ".join(
        [candidate.source.title, *candidate.source.section_path, candidate.text]
    )
    return bool(expected and expected in _normalize_text(scope_text))


def _candidate_scope_text(candidate: SearchResult) -> str:
    metadata = candidate.metadata
    fields = [
        candidate.source.title,
        candidate.source.issuer,
        *candidate.source.section_path,
        candidate.text,
        str(metadata.get("institution") or ""),
        str(metadata.get("organization") or ""),
        str(metadata.get("bank_name") or ""),
    ]
    return _normalize_text(" ".join(fields))


def _normalize_text(value: str) -> str:
    return TEXT_NORMALIZE_RE.sub("", value or "").lower()
