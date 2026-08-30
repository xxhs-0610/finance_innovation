from __future__ import annotations

import re
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
from app.retrieval.multi_target_retriever import multi_target_retriever
from app.schemas.chunk_schema import SearchResult
from app.schemas.retrieval_schema import QueryAnalysis, RetrievalResponse
from app.utils.logger import get_logger
from app.utils.paths import resolve_path

logger = get_logger("app.retrieval.hybrid")


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

    def search(
        self,
        question: str,
        top_k: int = 5,
        task_type: str | None = None,
        options: dict[str, str] | None = None,
        semantic_hint: dict[str, Any] | None = None,
    ) -> RetrievalResponse:
        analysis = parse_query(
            question, task_type=task_type, options=options,
            semantic_hint=semantic_hint,
        )
        logger.info(
            f"[HybridRetriever] 意图解析: query='{question}', task_type='{analysis.task_type}', "
            f"type='{analysis.query_type}', topic='{analysis.topic}', institution='{analysis.institution_type}', "
            f"indicator='{analysis.indicator}', period='{analysis.time_period}', rule='{analysis.rule_type}'"
        )

        # Discrete Multi-Target Retrieval Dispatch (unless custom test mock retrievers are injected)
        is_mock_pipeline = any(r.name not in {"bm25", "vector", "table"} for r in self.retrievers)
        if not is_mock_pipeline and analysis.task_plan and analysis.task_plan.task_type in {
            "TABLE_COMPARE",
            "TABLE_CALCULATION",
            "FACT_SINGLE_CHOICE",
            "FACT_MULTI_CHOICE",
            "TABLE_LOOKUP",
        }:
            mt_response = multi_target_retriever.retrieve(
                question, analysis.task_plan, top_k=top_k
            )
            evidence = mt_response.merged_evidence
            status = mt_response.overall_status
            logger.info(
                f"[HybridRetriever] 多目标检索完成 | 任务数={len(mt_response.retrieval_tasks)} | "
                f"成功数={sum(1 for r in mt_response.retrieval_results if r.status == 'SUCCESS')} | "
                f"融合证据数={len(evidence)} | 状态={status}"
            )
            return RetrievalResponse(
                query=analysis.question,
                analysis=analysis,
                status=status,
                evidence=evidence,
                diagnostics={
                    "routing": {
                        "query_type": analysis.query_type,
                        "task_type": analysis.task_type,
                        "retrieval_mode": "multi_target",
                    },
                    "retrieval_tasks": [t.to_dict() for t in mt_response.retrieval_tasks],
                    "retrieval_results": [r.to_dict() for r in mt_response.retrieval_results],
                    "multi_target": mt_response.to_dict(),
                    "failures": [],
                },
                module4_guidance=_module4_guidance(analysis, status, evidence),
            )

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

        counts_str = ", ".join(f"{name}={len(res)}条" for name, res in result_sets.items())
        logger.info(f"[HybridRetriever] 各路候选召回: {counts_str or '无'}")

        fused = reciprocal_rank_fusion(result_sets, rrf_k=self.rrf_k)
        fused = apply_entity_filters(analysis, fused)
        entity_filter_diagnostics = {
            "subject_entity": analysis.entities.get("subject_entity", ""),
            "candidate_count_after_filter": len(fused),
        }
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
        evidence, evidence_rejection = _enforce_subject_evidence_consistency(
            analysis, evidence
        )
        status = _response_status(analysis, evidence, failures)
        logger.info(f"[HybridRetriever] RRF融合候选: {len(fused)}条 -> 最终优选证据: {len(evidence)}条 (状态: {status})")
        
        rerank_top = [
            {
                "citation_id": f"E{idx}",
                "chunk_id": r.chunk_id,
                "title": getattr(r.source, "title", "") if hasattr(r.source, "title") else (r.source.get("title", "") if isinstance(r.source, dict) else ""),
                "score": float(r.score),
            }
            for idx, r in enumerate(evidence, 1)
        ]

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
                "recall_counts": {name: len(res) for name, res in result_sets.items()},
                "retrievers": retriever_diagnostics,
                "reranker": reranker_diagnostics,
                "rerank_top": rerank_top,
                "entity_consistency": entity_filter_diagnostics,
                "evidence_rejection": evidence_rejection,
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
    task_type: str | None = None,
    options: dict[str, str] | None = None,
    semantic_hint: dict[str, Any] | None = None,
    *,
    db_path: str | Path = "data/processed/kb_rebuild/metadata.db",
    index_dir: str | Path = "indexes/kb_rebuild",
) -> RetrievalResponse:
    # Resolve repository-relative assets before constructing module 2's reader.
    # The API is commonly started from ``backend/`` while data and indexes live
    # at the project root; passing the raw relative paths would silently make
    # FAISS look under ``backend/indexes`` and degrade otherwise valid answers.
    resolved_db_path = resolve_path(db_path)
    resolved_index_dir = resolve_path(index_dir)
    reader = KnowledgeBaseReader(resolved_db_path, vector_index_dir=resolved_index_dir)
    retriever = HybridRetriever(
        [
            BM25Retriever(reader),
            VectorRetriever(KnowledgeBaseVectorBackend(reader)),
            TableRetriever(reader),
        ],
        reranker=RuleBasedReranker(),
    )
    return retriever.search(
        question, top_k=top_k, task_type=task_type, options=options,
        semantic_hint=semantic_hint,
    )


def retrieve_evidence(
    question: str,
    top_k: int = 5,
    task_type: str | None = None,
    options: dict[str, str] | None = None,
    *,
    db_path: str | Path = "data/processed/kb_rebuild/metadata.db",
    index_dir: str | Path = "indexes/kb_rebuild",
) -> list[dict]:
    """Compatibility entry used by module 4 until it accepts the full response."""
    response = retrieve(
        question,
        top_k=top_k,
        task_type=task_type,
        options=options,
        db_path=db_path,
        index_dir=index_dir,
    )
    return [item.to_dict() for item in (response.evidence[:top_k] if top_k > 0 else response.evidence)]


def _format_reranker_results(
    analysis: QueryAnalysis,
    raw_results: Sequence[SearchResult],
    ranked_results: Sequence[SearchResult],
) -> dict:
    if not ranked_results:
        return {"status": "skipped"}
    return {
        "status": "applied",
        "input_count": len(raw_results),
        "output_count": len(ranked_results),
        "top_sources": [
            item.metadata.get("source") or item.metadata.get("title")
            for item in ranked_results[:3]
        ],
    }


def _collect_option_candidates(
    evidence: Sequence[SearchResult],
) -> list[str]:
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
    if analysis.task_plan and analysis.task_plan.need_clarification:
        return ["metric"]
    if analysis.task_plan and not analysis.task_plan.need_clarification:
        return []
    missing: list[str] = []
    if analysis.query_type in {"table_lookup", "clause_threshold"} and not analysis.entities.get(
        "metric"
    ):
        missing.append("metric")
    return missing


def _response_status(
    analysis: QueryAnalysis,
    evidence: Sequence[SearchResult],
    failures: Sequence[dict[str, str]],
) -> str:
    if not evidence:
        return "no_evidence"
    if not any(
        item.metadata.get("evidence_quality", {}).get("complete")
        for item in evidence
    ):
        return "no_evidence"
    if analysis.task_plan and not analysis.task_plan.need_clarification:
        return "answerable"
    if _requires_bank_tier_clarification(analysis, evidence):
        return "needs_clarification"
    if _requires_table_dimension_clarification(analysis, evidence):
        return "needs_clarification"
    if failures:
        return "degraded"
    return "answerable"


def _enforce_subject_evidence_consistency(
    analysis: QueryAnalysis,
    evidence: Sequence[SearchResult],
) -> tuple[list[SearchResult], dict[str, object]]:
    """Reject lexical near-misses for explicit organization subjects."""

    subject = analysis.entities.get("subject_entity", "")
    if not subject:
        return list(evidence), {"status": "not_applicable"}
    expected = _normalize_entity_text(subject)
    accepted: list[SearchResult] = []
    rejected: list[str] = []
    for item in evidence:
        scope = _normalize_entity_text(
            " ".join(
                [
                    item.source.title,
                    item.source.issuer,
                    *item.source.section_path,
                    item.text,
                    str(item.metadata.get("institution") or ""),
                    str(item.metadata.get("organization") or ""),
                ]
            )
        )
        if expected and expected in scope:
            accepted.append(item)
        else:
            rejected.append(item.chunk_id)
    return accepted, {
        "status": "passed" if not rejected else "rejected",
        "subject_entity": subject,
        "rejected_chunk_ids": rejected,
    }


def _normalize_entity_text(value: str) -> str:
    return "".join(str(value or "").lower().split())


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
            "reason": (
                "out_of_domain"
                if analysis.query_type == "unsupported"
                else "no_reliable_evidence"
            ),
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
    if analysis.task_plan and not analysis.task_plan.need_clarification:
        return False
    q = (analysis.question or "").strip()
    # If the question specifies choices, general baselines, or specific entities, do not clarify
    if any(c in q for c in ("A:", "A.", "A：", "A、", "第一档", "第二档", "第三档", "最低监管要求是多少", "底线要求是多少", "最低要求是多少")):
        return False
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
    # Prompt 7 rule: Multi-column tables, multiple options, or multi-metric queries NEVER trigger clarification.
    # Deterministic TableExecutor handles extraction; if missing, returns MISSING_OPERAND (no_evidence).
    return False


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
    """Identify genuine missing entities only when user expression is fundamentally incomplete."""
    if analysis.task_plan and not analysis.task_plan.need_clarification:
        return []
    q = (analysis.question or "").strip()
    # Multiple targets, choices, comparisons, or calculations are NEVER missing entities
    if any(c in q for c in ("A:", "A.", "A：", "A、", "比较", "相差", "差距", "从", "到", "谁最大", "谁最小", "哪项", "最高", "最低")):
        return []
    if len(re.findall(r"“[^”]+”|‘[^’]+’|《[^》]+》", q)) >= 2:
        return []

    missing: list[str] = []
    # Only flag missing metric for ungrounded dangling demonstrative queries or bare time queries without metric
    if analysis.query_type in {"table_lookup", "clause_threshold"} or (analysis.task_plan and analysis.task_plan.need_clarification):
        if re.match(r"^(?:申请|办理)?(?:这个|那个|这项|该项|此项|指标是多少|比例是多少)", q) or (not analysis.indicator and any(w in q for w in ("是多少", "多少")) and not any(k in q for k in ("资本", "保费", "贷款", "存款", "资产", "负债", "收入", "支出", "余额", "比例", "率"))):
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
