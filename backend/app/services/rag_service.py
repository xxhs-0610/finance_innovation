"""RAG Business Service Layer.
Orchestrates Question Routing, Query Understanding, Hybrid Retrieval, Evidence Refinement, Generation, and Hallucination Verification.
"""
from __future__ import annotations

import time
from typing import Any

from app.generation.answer_generator import generate_answer
from app.generation.deepseek_client import deepseek_enabled, deepseek_generator
from app.retrieval.hybrid_retriever import retrieve
from app.router.question_router import question_router
from app.router.system_card import system_card
from app.router.router_prompts import (
    CLARIFICATION_HINTS,
    OUT_OF_SCOPE_RESPONSES,
    SYSTEM_META_CARD_CONTENT,
)
from app.schemas.router_schema import RouteDecision
from app.utils.logger import get_logger

logger = get_logger("app.services.rag")


class RAGService:
    """Core RAG pipeline service orchestrator with pre-retrieval Question Router."""

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        task_type: str | None = None,
        semantic_hint: dict[str, Any] | None = None,
    ):
        """Execute Module 3 hybrid retrieval."""
        logger.info(f"[RAG] 启动模块3检索: query='{question}', top_k={top_k}, task_type={task_type}")
        t0 = time.perf_counter()
        res = retrieve(
            question, top_k=top_k, task_type=task_type,
            semantic_hint=semantic_hint,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ev_count = len(res.evidence) if hasattr(res, "evidence") else 0
        status = getattr(res, "status", "unknown")
        logger.info(f"[RAG] 模块3检索完成 | 耗时: {elapsed_ms:.1f}ms | 状态: {status} | 命中证据: {ev_count}条")
        return res

    def ask(
        self,
        question: str,
        top_k: int = 5,
        *,
        retriever_fn: Any = None,
        generator_fn: Any = None,
        deepseek_enabled_fn: Any = None,
    ) -> dict[str, Any]:
        """Execute Question Routing -> (Optional RAG Retrieval) -> Verified Generation."""
        q = question.strip()
        if not q:
            logger.warning("[RAG] 收到空问题请求")
            raise ValueError("问题不能为空")

        start_time = time.perf_counter()
        logger.info(f"[RAG] 收到问答请求: question='{q}', top_k={top_k}")

        # =========================================================================
        # 1. Pre-RAG Question Router: Intent & Boundary Policy Classification
        # =========================================================================
        decision: RouteDecision = question_router.route(q)

        # -------------------------------------------------------------------------
        # Case A: SYSTEM_META (Questions about system capabilities, source, rules)
        # -------------------------------------------------------------------------
        if decision.intent == "SYSTEM_META":
            res = self._handle_system_meta(q, decision, start_time)
            self._record_flow_trace(q, decision, res, None, {"total": res.get("diagnostics", {}).get("total_latency_ms", 0)})
            return res

        # -------------------------------------------------------------------------
        # Case B: OUT_OF_SCOPE (Stocks, Investments, Recruitment, General Chat)
        # -------------------------------------------------------------------------
        if decision.intent == "OUT_OF_SCOPE":
            res = self._handle_out_of_scope(q, decision, start_time)
            self._record_flow_trace(q, decision, res, None, {"total": res.get("diagnostics", {}).get("total_latency_ms", 0)})
            return res

        # -------------------------------------------------------------------------
        # Case C: NEED_CLARIFICATION (Missing metrics, ambiguous pronouns)
        # -------------------------------------------------------------------------
        if decision.intent == "NEED_CLARIFICATION" or decision.need_clarification:
            res = self._handle_need_clarification(q, decision, start_time)
            self._record_flow_trace(q, decision, res, None, {"total": res.get("diagnostics", {}).get("total_latency_ms", 0)})
            return res

        # -------------------------------------------------------------------------
        # Case D: DOMAIN_QA (Banking Regulation & Statistics -> Enters RAG)
        # -------------------------------------------------------------------------
        t0 = time.perf_counter()
        retrieve_call = retriever_fn or self.retrieve
        semantic_hint = getattr(decision, "semantic", None)
        try:
            retrieval_response = retrieve_call(
                q, top_k=top_k, task_type=decision.task_type,
                semantic_hint=semantic_hint,
            )
        except TypeError:
            # Preserve compatibility with test/custom retrievers that expose
            # the older three-argument signature.
            try:
                retrieval_response = retrieve_call(q, top_k=top_k, task_type=decision.task_type)
            except TypeError:
                try:
                    retrieval_response = retrieve_call(q, top_k=top_k)
                except TypeError:
                    retrieval_response = retrieve_call(q)
        t1 = time.perf_counter()

        is_enabled = (deepseek_enabled_fn or deepseek_enabled)()
        generator = generator_fn if generator_fn is not None else (deepseek_generator if is_enabled else None)
        gen_backend = "DeepSeek-API" if generator else "Local Rule/Fallback Engine"
        logger.info(f"[RAG] 启动模块4可信生成与事后校验 | 生成后端: {gen_backend} | 任务类型: {decision.task_type or decision.qa_type}")

        answer_result = generate_answer(q, retrieval_response, generator=generator)
        t2 = time.perf_counter()

        retrieval_ms = int((t1 - t0) * 1000)
        gen_ms = int((t2 - t1) * 1000)
        total_ms = int((t2 - start_time) * 1000)

        if "diagnostics" not in answer_result or not isinstance(answer_result["diagnostics"], dict):
            answer_result["diagnostics"] = {}
        answer_result["diagnostics"]["router"] = decision.to_dict()
        if hasattr(retrieval_response, "analysis") and hasattr(retrieval_response.analysis, "to_analyzer_dict"):
            answer_result["diagnostics"]["analyzer"] = retrieval_response.analysis.to_analyzer_dict()
        if hasattr(retrieval_response, "analysis") and getattr(retrieval_response.analysis, "task_plan", None):
            answer_result["diagnostics"]["task_plan"] = retrieval_response.analysis.task_plan.to_dict()
        if hasattr(retrieval_response, "diagnostics") and isinstance(retrieval_response.diagnostics, dict):
            if "retrieval_tasks" in retrieval_response.diagnostics:
                answer_result["diagnostics"]["retrieval_tasks"] = retrieval_response.diagnostics["retrieval_tasks"]
            if "retrieval_results" in retrieval_response.diagnostics:
                answer_result["diagnostics"]["retrieval_results"] = retrieval_response.diagnostics["retrieval_results"]
        if "evidence_verifier" in answer_result.get("verification", {}):
            answer_result["diagnostics"]["evidence_verifier"] = answer_result["verification"]["evidence_verifier"]
        answer_result["diagnostics"]["retrieval_latency_ms"] = retrieval_ms
        answer_result["diagnostics"]["generation_latency_ms"] = gen_ms
        answer_result["diagnostics"]["total_latency_ms"] = total_ms

        ans_status = answer_result.get("status", "unknown")
        citations_count = len(answer_result.get("citations", []))
        confidence = answer_result.get("verification", {}).get("confidence", "N/A")
        logger.info(
            f"[RAG] 监管问答全流程完成 | 意图: {decision.intent}({decision.task_type or decision.qa_type}) | 状态: {ans_status} | 引用数: {citations_count} | 置信度: {confidence} | 检索: {retrieval_ms}ms | 生成校验: {gen_ms}ms | 总耗时: {total_ms}ms"
        )

        latencies = {
            "retrieval_ms": retrieval_ms,
            "generation_ms": gen_ms,
            "total_ms": total_ms,
        }
        self._record_flow_trace(q, decision, answer_result, retrieval_response, latencies)

        return answer_result

    def _record_flow_trace(
        self,
        q: str,
        decision: RouteDecision,
        result: dict[str, Any],
        retrieval_response: Any = None,
        latencies: dict[str, int] | None = None,
    ) -> None:
        """Construct structured QAFlowTrace and output multi-stage evaluation log."""
        from app.utils.audit_logger import audit_logger, QAFlowTrace

        trace_id = f"trace_{int(time.time() * 1000)}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        status = result.get("status", "unknown")

        # Determine final_action (ANSWER, REFUSE, CLARIFY, SYSTEM_META)
        if decision.intent == "SYSTEM_META":
            final_action = "SYSTEM_META"
        elif decision.intent == "OUT_OF_SCOPE":
            final_action = "REFUSE"
        elif status == "needs_clarification":
            final_action = "CLARIFY"
        elif status in ("answered", "degraded"):
            final_action = "ANSWER"
        elif status in ("refused", "no_evidence"):
            final_action = "REFUSE"
        else:
            final_action = "UNKNOWN"

        # Analyzer extraction
        analysis = getattr(retrieval_response, "analysis", None)
        analyzer_keywords = getattr(analysis, "keywords", []) if analysis else []
        analyzer_indicator = getattr(analysis, "indicator", None) if analysis else None
        analyzer_institution = getattr(analysis, "institution_type", None) if analysis else None
        analyzer_time_period = getattr(analysis, "time_period", None) if analysis else None
        analyzer_document_name = getattr(analysis, "document_name", None) if analysis else None
        analyzer_article_number = getattr(analysis, "article_number", None) if analysis else None
        analyzer_rule_type = getattr(analysis, "rule_type", None) if analysis else None
        analyzer_topic = getattr(analysis, "topic", None) if analysis else None

        # Plan extraction
        plan_obj = getattr(analysis, "task_plan", None) or result.get("diagnostics", {}).get("task_plan")
        plan_task_type = None
        plan_source = {}
        plan_targets = []
        plan_operands = []
        plan_options = {}
        plan_operation = None
        plan_scope = None

        if plan_obj:
            if isinstance(plan_obj, dict):
                plan_task_type = plan_obj.get("task_type")
                plan_source = plan_obj.get("source", {})
                plan_targets = plan_obj.get("targets", [])
                plan_operands = plan_obj.get("operands", [])
                plan_options = plan_obj.get("options", {})
                plan_operation = plan_obj.get("operation")
                plan_scope = plan_obj.get("scope")
            else:
                plan_task_type = getattr(plan_obj, "task_type", None)
                src = getattr(plan_obj, "source", None)
                plan_source = src.to_dict() if hasattr(src, "to_dict") else {}
                targets = getattr(plan_obj, "targets", [])
                plan_targets = [t.to_dict() if hasattr(t, "to_dict") else t for t in targets]
                operands = getattr(plan_obj, "operands", [])
                plan_operands = [op.to_dict() if hasattr(op, "to_dict") else op for op in operands]
                plan_options = getattr(plan_obj, "options", {}) or {}
                plan_operation = getattr(plan_obj, "operation", None)
                plan_scope = getattr(plan_obj, "scope", None)

        # Retrieval extraction
        ret_diag = getattr(retrieval_response, "diagnostics", {}) if retrieval_response else {}
        recall_counts = ret_diag.get("recall_counts", {})
        if not recall_counts and "retrievers" in ret_diag:
            recall_counts = {
                k: v.get("candidate_count", 0)
                for k, v in ret_diag["retrievers"].items()
                if isinstance(v, dict)
            }

        mt_diag = ret_diag.get("multi_target", {}) if isinstance(ret_diag, dict) else {}
        if not mt_diag and isinstance(result.get("diagnostics"), dict):
            mt_diag = result["diagnostics"].get("multi_target", {})

        raw_tasks = mt_diag.get("retrieval_tasks") or result.get("diagnostics", {}).get("retrieval_tasks", [])
        retrieval_tasks = [
            t.to_dict() if hasattr(t, "to_dict") else t
            for t in raw_tasks
        ]

        raw_results = mt_diag.get("retrieval_results") or result.get("diagnostics", {}).get("retrieval_results", [])
        retrieval_target_results = []
        for r in raw_results:
            if isinstance(r, dict):
                ev = r.get("evidence", [])
                retrieval_target_results.append({
                    "task_id": r.get("task_id", ""),
                    "target": r.get("target", ""),
                    "status": "SUCCESS" if ev else "EMPTY",
                    "evidence_count": len(ev),
                })
            elif hasattr(r, "task_id"):
                ev = getattr(r, "evidence", [])
                retrieval_target_results.append({
                    "task_id": getattr(r, "task_id", ""),
                    "target": getattr(r, "target", ""),
                    "status": "SUCCESS" if ev else "EMPTY",
                    "evidence_count": len(ev),
                })

        evidence_list = getattr(retrieval_response, "evidence", []) if retrieval_response else []
        top_k = len(evidence_list)
        def _display_source_title(e: Any) -> str:
            src = e.source if hasattr(e, "source") else (e.get("source", {}) if isinstance(e, dict) else {})
            title = getattr(src, "title", "") if not isinstance(src, dict) else src.get("title", "")
            path = getattr(src, "local_path", "") if not isinstance(src, dict) else src.get("local_path", "")
            metadata = getattr(e, "metadata", {}) if not isinstance(e, dict) else e.get("metadata", {})
            full_title = metadata.get("attachment_title") or metadata.get("source_page_title") or metadata.get("file_name") if isinstance(metadata, dict) else ""
            return str(full_title or title or (path.replace("\\", "/").rsplit("/", 1)[-1] if path else "监管文件"))

        sources = list(dict.fromkeys([_display_source_title(e) for e in evidence_list if _display_source_title(e)]))

        # Rerank results
        rerank_results = ret_diag.get("rerank_top", [])
        if not rerank_results and evidence_list:
            rerank_results = [
                {
                    "citation_id": f"E{idx}",
                    "chunk_id": getattr(e, "chunk_id", e.get("chunk_id", "") if isinstance(e, dict) else ""),
                    "title": _display_source_title(e),
                    "score": float(getattr(e, "score", e.get("score", 0.0) if isinstance(e, dict) else 0.0)),
                }
                for idx, e in enumerate(evidence_list, 1)
            ]

        # Verifier extraction
        ver_info = result.get("verification", {}).get("evidence_verifier", {})
        verifier_answerable = ver_info.get("answerable") if ver_info else (True if status == "answered" else None)
        verifier_reason_code = (
            result.get("error_code")
            or result.get("verification", {}).get("error_code")
            or (ver_info.get("reason_code") if ver_info else None)
            or result.get("refusal_reason")
        )
        verifier_reason = ver_info.get("reason") if ver_info else result.get("refusal_reason")
        verifier_supporting_ids = ver_info.get("supporting_evidence_ids", []) if ver_info else []
        verifier_missing_info = ver_info.get("missing_information", []) if ver_info else []

        # Executor & Calculation & Option Verification extraction
        ver_dict = result.get("verification", {})
        table_exec = ver_dict.get("table_execution") or result.get("table_execution") or {}
        opt_ver = ver_dict.get("option_verification") or result.get("option_verification") or {}

        executor_type = None
        executor_status = None
        executor_matched_option = None
        executor_detail = None
        calculation_operation = None
        calculation_operands = []
        calculation_result = None
        calculation_formula = None
        option_verdicts = []
        option_selected = []

        if table_exec and isinstance(table_exec, dict):
            executor_type = table_exec.get("task_type") or decision.task_type
            executor_status = table_exec.get("status")
            executor_matched_option = table_exec.get("matched_option")
            executor_detail = table_exec.get("explanation")
            calculation_operation = table_exec.get("operation")
            calculation_operands = table_exec.get("operands", [])
            calculation_result = table_exec.get("result")
            calculation_formula = table_exec.get("explanation")

        if opt_ver and isinstance(opt_ver, dict):
            executor_type = executor_type or decision.task_type or "OPTION_VERIFY"
            executor_status = executor_status or opt_ver.get("status")
            executor_detail = executor_detail or opt_ver.get("explanation")
            option_selected = opt_ver.get("selected_options", [])
            raw_ov = opt_ver.get("options_verification", [])
            option_verdicts = [v if isinstance(v, dict) else v.to_dict() for v in raw_ov]

        # Intermediate verify extraction
        inter_ver = (
            ver_dict.get("intermediate_verification")
            or (table_exec.get("intermediate_verification") if isinstance(table_exec, dict) else None)
            or (opt_ver.get("intermediate_verification") if isinstance(opt_ver, dict) else None)
            or {}
        )
        intermediate_can_execute = inter_ver.get("can_execute") if isinstance(inter_ver, dict) else None
        intermediate_verified_targets = inter_ver.get("verified_targets", []) if isinstance(inter_ver, dict) else []
        intermediate_missing_targets = inter_ver.get("missing_targets", []) if isinstance(inter_ver, dict) else []
        intermediate_conflicting_targets = inter_ver.get("conflicting_targets", []) if isinstance(inter_ver, dict) else []

        # Error Attribution and Pinpointed Failure Point
        attribution, failure_point = audit_logger.infer_failure_point(
            router_intent=decision.intent,
            router_task_type=decision.task_type or decision.qa_type,
            has_plan=bool(plan_obj),
            retrieval_count=top_k,
            retrieval_status=getattr(retrieval_response, "status", None) if retrieval_response else None,
            executor_status=executor_status,
            intermediate_missing=intermediate_missing_targets,
            option_status=opt_ver.get("status") if isinstance(opt_ver, dict) else None,
            verifier_answerable=verifier_answerable,
            verification_passed=result.get("verification", {}).get("passed", True),
            error_code=verifier_reason_code,
            final_status=status,
        )

        # Grounding & Regeneration Extraction
        initial_answer_preview = str(ver_dict.get("initial_answer") or "")
        core_claims = [str(c.get("raw", "")) for c in ver_dict.get("core_claims", []) if isinstance(c, dict)]
        supported_core_claims = [str(c.get("raw", "")) for c in ver_dict.get("supported_core_claims", []) if isinstance(c, dict)]
        unsupported_core_claims = [str(c.get("raw", "")) for c in ver_dict.get("unsupported_core_claims", []) if isinstance(c, dict)]
        unsupported_optional_claims = [str(c.get("raw", "")) for c in ver_dict.get("unsupported_optional_claims", []) if isinstance(c, dict)]
        grounding_action = str(ver_dict.get("grounding_action") or "PASS")
        regeneration_triggered = bool(ver_dict.get("regeneration_triggered", False))

        trace = QAFlowTrace(
            trace_id=trace_id,
            timestamp=timestamp,
            query=q,
            router_intent=decision.intent,
            router_task_type=decision.task_type or decision.qa_type,
            router_reason=decision.reason,
            router_qa_type=decision.qa_type,
            plan_task_type=plan_task_type,
            plan_source=plan_source,
            plan_targets=plan_targets,
            plan_operands=plan_operands,
            plan_options=plan_options,
            plan_operation=plan_operation,
            plan_scope=plan_scope,
            retrieval_tasks=retrieval_tasks,
            retrieval_target_results=retrieval_target_results,
            retrieval_recall_counts=recall_counts,
            retrieval_top_k=top_k,
            retrieval_sources=sources,
            retrieval_status=getattr(retrieval_response, "status", None) if retrieval_response else None,
            rerank_results=rerank_results,
            executor_type=executor_type,
            executor_status=executor_status,
            executor_matched_option=executor_matched_option,
            executor_detail=executor_detail,
            intermediate_verified_targets=intermediate_verified_targets,
            intermediate_missing_targets=intermediate_missing_targets,
            intermediate_conflicting_targets=intermediate_conflicting_targets,
            intermediate_can_execute=intermediate_can_execute,
            calculation_operation=calculation_operation,
            calculation_operands=calculation_operands,
            calculation_result=calculation_result,
            calculation_formula=calculation_formula,
            option_verdicts=option_verdicts,
            option_selected=option_selected,
            analyzer_keywords=analyzer_keywords,
            analyzer_indicator=analyzer_indicator,
            analyzer_institution=analyzer_institution,
            analyzer_time_period=analyzer_time_period,
            analyzer_document_name=analyzer_document_name,
            analyzer_article_number=analyzer_article_number,
            analyzer_rule_type=analyzer_rule_type,
            analyzer_topic=analyzer_topic,
            verifier_answerable=verifier_answerable,
            verifier_reason_code=verifier_reason_code,
            verifier_reason=verifier_reason,
            verifier_supporting_ids=verifier_supporting_ids,
            verifier_missing_info=verifier_missing_info,
            core_claims=core_claims,
            supported_core_claims=supported_core_claims,
            unsupported_core_claims=unsupported_core_claims,
            unsupported_optional_claims=unsupported_optional_claims,
            grounding_action=grounding_action,
            regeneration_triggered=regeneration_triggered,
            initial_answer_preview=initial_answer_preview,
            final_action=final_action,
            final_status=status,
            final_answer_preview=result.get("answer", "")[:200],
            citations=result.get("citations", []),
            latency_ms=latencies or {},
            stage_attribution=attribution,
            failure_point=failure_point,
            diagnostic_notes=failure_point,
        )

        audit_logger.record_trace(trace)
        if "diagnostics" not in result or not isinstance(result["diagnostics"], dict):
            result["diagnostics"] = {}
        result["diagnostics"]["flow_trace"] = trace.to_dict()

    def _handle_system_meta(self, q: str, decision: RouteDecision, start_time: float) -> dict[str, Any]:
        """Handle system self-reflection and capability introduction via System Card."""
        total_ms = int((time.perf_counter() - start_time) * 1000)
        answer_text = system_card.generate_response(q)
        return {
            "status": "answered",
            "answer": answer_text,
            "evidence": [],
            "risk_tips": ["本回答属于系统自身定位与功能说明，未调用监管知识库检索。"],
            "confidence": 1.0,
            "citations": [],
            "verification": {
                "passed": True,
                "type": "system_meta",
                "issues": [],
            },
            "diagnostics": {
                "router": decision.to_dict(),
                "retrieval_latency_ms": 0,
                "generation_latency_ms": total_ms,
                "total_latency_ms": total_ms,
            },
            "question": q,
        }

    def _handle_out_of_scope(self, q: str, decision: RouteDecision, start_time: float) -> dict[str, Any]:
        """Handle out-of-scope queries (stocks, general encyclopedias, recruitment) directly."""
        total_ms = int((time.perf_counter() - start_time) * 1000)
        
        # Choose specific friendly refusal text based on keywords
        if any(w in q for w in ("股票", "股价", "行情", "走势", "大盘", "炒股")):
            answer_text = OUT_OF_SCOPE_RESPONSES["stock_prediction"]
        elif any(w in q for w in ("理财", "投资", "基金", "收益率", "赚钱")):
            answer_text = OUT_OF_SCOPE_RESPONSES["investment_advice"]
        elif any(w in q for w in ("招聘", "校招", "社招", "求职", "薪资", "简历")):
            answer_text = OUT_OF_SCOPE_RESPONSES["recruitment"]
        else:
            answer_text = OUT_OF_SCOPE_RESPONSES["general"]

        return {
            "status": "refused",
            "answer": answer_text,
            "evidence": [],
            "risk_tips": [
                f"系统已拦截领域外问题：{decision.reason}",
                "建议提问银行业监管制度（如《资本管理办法》）、资本充足率监管要求、主要监管指标统计报表等相关业务。",
            ],
            "confidence": 0.0,
            "citations": [],
            "verification": {
                "passed": False,
                "issues": [decision.reason],
            },
            "refusal_reason": decision.reason,
            "diagnostics": {
                "router": decision.to_dict(),
                "retrieval_latency_ms": 0,
                "generation_latency_ms": total_ms,
                "total_latency_ms": total_ms,
            },
            "question": q,
        }

    def _handle_need_clarification(self, q: str, decision: RouteDecision, start_time: float) -> dict[str, Any]:
        """Handle underspecified questions with targeted minimal necessary clarification."""
        total_ms = int((time.perf_counter() - start_time) * 1000)
        
        if any(w in q for w in ("比例", "指标", "数值", "是多少", "为多少")):
            hint = CLARIFICATION_HINTS["metric_missing"]
        elif any(w in q for w in ("资本充足率", "最低要求", "底线要求")) and not any(w in q for w in ("第一档", "第二档", "第三档")):
            hint = CLARIFICATION_HINTS["bank_tier_missing"]
        elif any(w in q for w in ("合规吗", "是否合规", "违规吗", "可以吗", "行不行")):
            hint = CLARIFICATION_HINTS["scenario_missing"]
        elif any(w in q for w in ("哪年", "哪个季度", "什么时候", "期间")):
            hint = CLARIFICATION_HINTS["period_missing"]
        else:
            hint = CLARIFICATION_HINTS["general"]

        return {
            "status": "needs_clarification",
            "answer": f"💡 **请补充查询条件**：\n{hint}",
            "evidence": [],
            "risk_tips": [
                f"问题要素不足：{decision.reason}",
                "请在问题中补充明确的适用机构、监管指标名称或具体业务场景条件后再试。",
            ],
            "confidence": 0.0,
            "citations": [],
            "error_code": "AMBIGUOUS_QUERY",
            "verification": {
                "passed": False,
                "error_code": "AMBIGUOUS_QUERY",
                "issues": [decision.reason],
            },
            "refusal_reason": "AMBIGUOUS_QUERY",
            "diagnostics": {
                "router": decision.to_dict(),
                "retrieval_latency_ms": 0,
                "generation_latency_ms": total_ms,
                "total_latency_ms": total_ms,
            },
            "question": q,
        }


rag_service = RAGService()
