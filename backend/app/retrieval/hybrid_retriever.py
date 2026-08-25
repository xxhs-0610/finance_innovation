from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from app.indexing.index_reader import KnowledgeBaseReader
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.evidence_selector import select_evidence
from app.retrieval.query_parser import parse_query
from app.retrieval.reranker import CandidateReranker, RuleBasedReranker
from app.retrieval.table_retriever import TableRetriever
from app.retrieval.vector_retriever import KnowledgeBaseVectorBackend, VectorRetriever
from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis, RetrievalResponse


class CandidateRetriever(Protocol):
    name: str

    def search(self, analysis: QueryAnalysis, top_k: int = 20) -> list[SearchResult]: ...


class HybridRetriever:
    def __init__(
        self,
        retrievers: Sequence[CandidateRetriever] | None = None,
        *,
        rrf_k: int = 60,
        reranker: CandidateReranker | None = None,
    ) -> None:
        self.retrievers = (
            list(retrievers)
            if retrievers is not None
            else [
                BM25Retriever(),
                VectorRetriever(KnowledgeBaseVectorBackend()),
                TableRetriever(),
            ]
        )
        names = [retriever.name for retriever in self.retrievers]
        if len(names) != len(set(names)):
            raise ValueError("Retriever names must be unique")
        self.rrf_k = rrf_k
        self.reranker = reranker

    def search(self, question: str, top_k: int = 5) -> RetrievalResponse:
        analysis = parse_query(question)
        candidate_top_k = max(top_k * 4, 20) if top_k > 0 else 0
        result_sets: dict[str, list[SearchResult]] = {}
        retriever_diagnostics: dict[str, dict[str, str | int]] = {}
        failures: list[dict[str, str]] = []
        skipped_retrievers: list[str] = []

        missing_entities = _missing_required_entities(analysis)
        if missing_entities:
            for retriever in self.retrievers:
                retriever_diagnostics[retriever.name] = {
                    "status": "skipped",
                    "candidate_count": 0,
                }
                skipped_retrievers.append(retriever.name)
            return RetrievalResponse(
                query=analysis.question,
                analysis=analysis,
                status="needs_clarification",
                evidence=[],
                diagnostics={
                    "routing": {
                        "query_type": analysis.query_type,
                        "skipped_retrievers": skipped_retrievers,
                    },
                    "retrievers": retriever_diagnostics,
                    "reranker": {"status": "skipped"},
                    "failures": [],
                },
                module4_guidance=_clarification_guidance(missing_entities),
            )

        if analysis.query_type in {"ambiguous", "unsupported"}:
            for retriever in self.retrievers:
                retriever_diagnostics[retriever.name] = {
                    "status": "skipped",
                    "candidate_count": 0,
                }
                skipped_retrievers.append(retriever.name)
            status = (
                "needs_clarification"
                if analysis.query_type == "ambiguous"
                else "no_evidence"
            )
            return RetrievalResponse(
                query=analysis.question,
                analysis=analysis,
                status=status,
                evidence=[],
                diagnostics={
                    "routing": {
                        "query_type": analysis.query_type,
                        "skipped_retrievers": skipped_retrievers,
                    },
                    "retrievers": retriever_diagnostics,
                    "reranker": {"status": "skipped"},
                    "failures": [],
                },
                module4_guidance=_module4_guidance(analysis, status, []),
            )

        for retriever in self.retrievers:
            supported_query_types = getattr(retriever, "supported_query_types", None)
            if (
                supported_query_types is not None
                and analysis.query_type not in supported_query_types
            ):
                retriever_diagnostics[retriever.name] = {
                    "status": "skipped",
                    "candidate_count": 0,
                }
                skipped_retrievers.append(retriever.name)
                continue
            try:
                results = retriever.search(analysis, top_k=candidate_top_k)
            except Exception as exc:  # A failed optional backend must not hide other evidence.
                retriever_diagnostics[retriever.name] = {
                    "status": "failed",
                    "candidate_count": 0,
                }
                failures.append(
                    {
                        "stage": "retrieval",
                        "component": retriever.name,
                        "error_type": type(exc).__name__,
                    }
                )
                continue
            result_sets[retriever.name] = results
            retriever_diagnostics[retriever.name] = {
                "status": "ok",
                "candidate_count": len(results),
            }

        fused = reciprocal_rank_fusion(result_sets, rrf_k=self.rrf_k)
        # Enforce critical entity constraints once more at the orchestration
        # boundary. This also protects callers that inject a custom retriever
        # which does not apply module 3's built-in post-filters.
        fused = apply_entity_filters(analysis, fused)
        reranker_diagnostics: dict[str, str] = {"status": "disabled"}
        if self.reranker:
            try:
                fused = self.reranker.rerank(
                    analysis,
                    fused,
                    top_k=candidate_top_k,
                )
            except Exception as exc:  # Preserve fused candidates if model scoring fails.
                reranker_diagnostics = {
                    "status": "failed",
                    "name": self.reranker.name,
                }
                failures.append(
                    {
                        "stage": "reranking",
                        "component": self.reranker.name,
                        "error_type": type(exc).__name__,
                    }
                )
            else:
                reranker_diagnostics = {
                    "status": "ok",
                    "name": self.reranker.name,
                }
        evidence = select_evidence(fused, top_k=top_k, analysis=analysis)
        status = _response_status(analysis, evidence, failures)
        return RetrievalResponse(
            query=analysis.question,
            analysis=analysis,
            status=status,
            evidence=evidence,
            diagnostics={
                "routing": {
                    "query_type": analysis.query_type,
                    "skipped_retrievers": skipped_retrievers,
                },
                "retrievers": retriever_diagnostics,
                "reranker": reranker_diagnostics,
                "failures": failures,
            },
            module4_guidance=_module4_guidance(analysis, status, evidence),
        )


def reciprocal_rank_fusion(
    result_sets: Mapping[str, Sequence[SearchResult]],
    *,
    rrf_k: int = 60,
) -> list[SearchResult]:
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")

    scores: dict[str, float] = {}
    base_results: dict[str, SearchResult] = {}
    merged_metadata: dict[str, dict] = {}
    source_details: dict[str, dict[str, dict[str, float | int]]] = {}

    for retriever_name, results in result_sets.items():
        seen_in_retriever: set[str] = set()
        for rank, result in enumerate(results, start=1):
            if result.chunk_id in seen_in_retriever:
                continue
            seen_in_retriever.add(result.chunk_id)
            base_results.setdefault(result.chunk_id, result)
            metadata = merged_metadata.setdefault(result.chunk_id, {})
            _merge_metadata(metadata, result.metadata)
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (
                rrf_k + rank
            )
            source_details.setdefault(result.chunk_id, {})[retriever_name] = {
                "rank": rank,
                "score": result.score,
            }

    fused: list[SearchResult] = []
    for chunk_id, rrf_score in scores.items():
        base = base_results[chunk_id]
        metadata = dict(merged_metadata[chunk_id])
        metadata["retrieval"] = {
            "rrf_k": rrf_k,
            "rrf_score": rrf_score,
            "sources": source_details[chunk_id],
        }
        fused.append(
            SearchResult(
                chunk_id=base.chunk_id,
                chunk_type=base.chunk_type,
                score=rrf_score,
                text=base.text,
                source=base.source,
                metadata=metadata,
            )
        )

    return sorted(fused, key=lambda item: (-item.score, item.chunk_id))


def _merge_metadata(target: dict, incoming: dict) -> None:
    for key, value in incoming.items():
        current = target.get(key)
        if key not in target:
            target[key] = value
        elif isinstance(current, dict) and isinstance(value, dict):
            _merge_metadata(current, value)


def retrieve(
    question: str,
    top_k: int = 5,
    *,
    db_path: str | Path = "data/processed/kb_rebuild/metadata.db",
    index_dir: str | Path = "indexes/kb_rebuild",
) -> RetrievalResponse:
    reader = KnowledgeBaseReader(db_path, vector_index_dir=index_dir)
    retriever = HybridRetriever(
        [
            BM25Retriever(reader),
            VectorRetriever(KnowledgeBaseVectorBackend(reader)),
            TableRetriever(reader),
        ],
        reranker=RuleBasedReranker(),
    )
    return retriever.search(question, top_k=top_k)


def retrieve_evidence(
    question: str,
    top_k: int = 5,
    *,
    db_path: str | Path = "data/processed/kb_rebuild/metadata.db",
    index_dir: str | Path = "indexes/kb_rebuild",
) -> list[dict]:
    """Compatibility entry used by module 4 until it accepts the full response."""
    response = retrieve(
        question,
        top_k=top_k,
        db_path=db_path,
        index_dir=index_dir,
    )
    if not response.module4_guidance.get("may_generate_answer", False):
        return []
    return [item.to_dict() for item in response.evidence]


def _response_status(
    analysis: QueryAnalysis,
    evidence: Sequence[SearchResult],
    failures: Sequence[dict[str, str]],
) -> str:
    if not evidence:
        return "no_evidence"
    if _requires_bank_tier_clarification(analysis, evidence):
        return "needs_clarification"
    if _requires_table_dimension_clarification(analysis, evidence):
        return "needs_clarification"
    if not any(
        item.metadata.get("evidence_quality", {}).get("complete")
        for item in evidence
    ):
        return "no_evidence"
    if failures:
        return "degraded"
    return "answerable"


def _module4_guidance(
    analysis: QueryAnalysis,
    status: str,
    evidence: Sequence[SearchResult],
) -> dict:
    if status == "needs_clarification":
        missing_entities = []
        clarification_question = "请补充问题中的适用对象或条件。"
        if _requires_bank_tier_clarification(analysis, evidence):
            missing_entities.append("bank_tier")
            clarification_question = "请明确是第一档、第二档还是第三档商业银行。"
        elif _requires_table_dimension_clarification(analysis, evidence):
            missing_entities.append("table_dimension")
            options = _table_dimension_options(evidence)
            option_text = "、".join(options)
            clarification_question = "同一期间匹配到多个数值列，请明确要查询的统计口径"
            if option_text:
                clarification_question += f"（{option_text}）"
            clarification_question += "。"
        return {
            "action": "clarify",
            "may_generate_answer": False,
            "missing_entities": missing_entities,
            "clarification_question": clarification_question,
            **(
                {"clarification_options": _table_dimension_options(evidence)}
                if "table_dimension" in missing_entities
                else {}
            ),
        }
    if status == "no_evidence":
        return {
            "action": "refuse",
            "may_generate_answer": False,
            "reason": "no_reliable_evidence",
        }
    return {
        "action": "answer" if status == "answerable" else "answer_with_warning",
        "may_generate_answer": True,
        "require_citations": True,
        "preserve_numeric_source_value": True,
    }


def _requires_bank_tier_clarification(
    analysis: QueryAnalysis, evidence: Sequence[SearchResult]
) -> bool:
    if analysis.query_type != "clause_threshold" or analysis.entities.get("bank_tier"):
        return False
    scope_text = " ".join(
        " ".join([item.source.title, *item.source.section_path, item.text])
        for item in evidence
    )
    return any(tier in scope_text for tier in ("第一档商业银行", "第二档商业银行", "第三档商业银行"))


def _requires_table_dimension_clarification(
    analysis: QueryAnalysis, evidence: Sequence[SearchResult]
) -> bool:
    if analysis.query_type != "table_lookup":
        return False
    return any(
        item.metadata.get("table_cell_selection", {}).get("status")
        == "ambiguous_dimension"
        for item in evidence
    )


def _table_dimension_options(evidence: Sequence[SearchResult]) -> list[str]:
    options: list[str] = []
    for item in evidence:
        selection = item.metadata.get("table_cell_selection", {})
        for option in selection.get("dimension_options", []):
            if isinstance(option, dict):
                label = str(option.get("label") or option.get("cell_ref") or "")
            else:
                label = str(option or "")
            if label and label not in options:
                options.append(label)
    return options


def _missing_required_entities(analysis: QueryAnalysis) -> list[str]:
    missing: list[str] = []
    if analysis.query_type in {"table_lookup", "clause_threshold"} and not analysis.entities.get(
        "metric"
    ):
        missing.append("metric")
    return missing


def _clarification_guidance(missing_entities: Sequence[str]) -> dict:
    questions = {
        "metric": "请补充要查询的具体监管指标，例如资本充足率或不良贷款率。",
    }
    first = missing_entities[0] if missing_entities else ""
    return {
        "action": "clarify",
        "may_generate_answer": False,
        "missing_entities": list(missing_entities),
        "clarification_question": questions.get(
            first, "请补充问题中的适用对象或查询条件。"
        ),
    }
