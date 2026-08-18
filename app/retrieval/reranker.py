from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Protocol

from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis


THRESHOLD_MARKERS = ("不得低于", "不低于", "不得高于", "不高于", "至少", "至多")
CONDITIONAL_THRESHOLD_MARKERS = (
    "可划分",
    "触发",
    "恢复到",
    "披露",
    "评级",
    "分类",
)
BANK_TIERS = ("第一档商业银行", "第二档商业银行", "第三档商业银行")


PairScorer = Callable[[Sequence[tuple[str, str]]], Sequence[float]]


class CandidateReranker(Protocol):
    name: str

    def rerank(
        self,
        analysis: QueryAnalysis,
        candidates: Sequence[SearchResult],
        *,
        top_k: int,
    ) -> list[SearchResult]: ...


class PairwiseReranker:
    def __init__(self, scorer: PairScorer, *, name: str = "pairwise") -> None:
        self.scorer = scorer
        self.name = name

    def rerank(
        self,
        analysis: QueryAnalysis,
        candidates: Sequence[SearchResult],
        *,
        top_k: int,
    ) -> list[SearchResult]:
        if top_k <= 0 or not candidates:
            return []

        pairs = [(analysis.question, candidate.text) for candidate in candidates]
        scores = list(self.scorer(pairs))
        if len(scores) != len(candidates):
            raise ValueError(
                "Pair scorer must return exactly one score for each candidate"
            )

        reranked: list[tuple[int, SearchResult]] = []
        for original_rank, (candidate, raw_score) in enumerate(
            zip(candidates, scores), start=1
        ):
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError("Pair scorer returned a non-finite score")
            metadata = dict(candidate.metadata)
            metadata["reranking"] = {
                "reranker": self.name,
                "score": score,
                "previous_score": candidate.score,
            }
            reranked.append(
                (
                    original_rank,
                    SearchResult(
                        chunk_id=candidate.chunk_id,
                        chunk_type=candidate.chunk_type,
                        score=score,
                        text=candidate.text,
                        source=candidate.source,
                        metadata=metadata,
                    ),
                )
            )

        reranked.sort(key=lambda item: (-item[1].score, item[0], item[1].chunk_id))
        return [item[1] for item in reranked[:top_k]]


class RuleBasedReranker:
    """Deterministic business reranker used before module 4 answer generation."""

    name = "module3-business-rules"

    def rerank(
        self,
        analysis: QueryAnalysis,
        candidates: Sequence[SearchResult],
        *,
        top_k: int,
    ) -> list[SearchResult]:
        reranked: list[tuple[int, SearchResult]] = []
        for original_rank, candidate in enumerate(candidates, start=1):
            bonus, reasons = _business_bonus(analysis, candidate)
            score = candidate.score + bonus
            metadata = dict(candidate.metadata)
            metadata["reranking"] = {
                "reranker": self.name,
                "score": score,
                "previous_score": candidate.score,
                "business_bonus": bonus,
                "reasons": reasons,
            }
            reranked.append(
                (
                    original_rank,
                    SearchResult(
                        chunk_id=candidate.chunk_id,
                        chunk_type=candidate.chunk_type,
                        score=score,
                        text=candidate.text,
                        source=candidate.source,
                        metadata=metadata,
                    ),
                )
            )
        reranked.sort(key=lambda item: (-item[1].score, item[0], item[1].chunk_id))
        return [item[1] for item in reranked[:top_k]]


def _business_bonus(
    analysis: QueryAnalysis, candidate: SearchResult
) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []
    text = " ".join(
        [candidate.source.title, *candidate.source.section_path, candidate.text]
    )
    metric = analysis.entities.get("metric", "")
    if metric and metric in candidate.text:
        bonus += 1.0
        reasons.append("metric_exact")
    if analysis.query_type == "clause_threshold" and any(
        marker in candidate.text for marker in THRESHOLD_MARKERS
    ):
        bonus += 0.8
        reasons.append("threshold_expression")
    if analysis.query_type == "clause_threshold" and any(
        marker in text for marker in CONDITIONAL_THRESHOLD_MARKERS
    ):
        bonus -= 1.0
        reasons.append("conditional_threshold_context")
    query_tier = analysis.entities.get("bank_tier", "")
    candidate_tiers = [tier for tier in BANK_TIERS if tier in text]
    if query_tier and query_tier in candidate_tiers:
        bonus += 1.2
        reasons.append("bank_tier_exact")
    elif not query_tier and candidate_tiers:
        bonus -= 0.25
        reasons.append("narrower_bank_tier_than_query")
    table_matches = set(
        candidate.metadata.get("table_matching", {}).get("matched_fields", [])
    )
    if "metric_exact" in table_matches:
        bonus += 1.0
        reasons.append("table_metric_exact")
    if "period_exact" in table_matches:
        bonus += 1.0
        reasons.append("table_period_exact")
    return bonus, reasons
