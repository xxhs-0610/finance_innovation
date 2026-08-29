"""Trustworthy Q&A Evaluation & Error Attribution Audit Logger (Prompt 12).

Provides end-to-end trace logging for every question answering session:
[QUERY] -> [ROUTER] -> [PLAN] -> [RETRIEVAL_TASKS] -> [RETRIEVAL_RESULTS]
-> [EXECUTOR] -> [INTERMEDIATE_VERIFY] -> [CALCULATION] -> [OPTION_VERIFY]
-> [FINAL_VERIFY] -> [FINAL_ACTION]

Facilitates pinpointing whether an error is caused by:
  1. Router 错 (misclassified intent/task_type)
  2. Planner 错 (task plan parsing/target generation error)
  3. 检索错 (recall miss or retrieval service error)
  4. 取数错 (missing table operand/row/column value)
  5. 计算错 (arithmetic execution error)
  6. Option Verify 错 (choice option unverified or conflicting)
  7. 最终回答/事后核验错 (post-generation grounding failure)
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.utils.logger import get_logger

logger = get_logger("app.audit")


def get_audit_log_path() -> Path:
    """Return persistent audit log file path in logs directory."""
    try:
        ws_root = Path(__file__).resolve().parents[3]
        log_dir = ws_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "qa_audit.jsonl"
    except Exception:
        return Path("logs/qa_audit.jsonl")


AUDIT_LOG_FILE = get_audit_log_path()


@dataclass
class QAFlowTrace:
    """Comprehensive structured audit trail for a single Q&A session (Prompt 12)."""
    trace_id: str
    timestamp: str

    # [QUERY]
    query: str

    # [ROUTER]
    router_intent: str | None = None
    router_task_type: str | None = None
    router_reason: str | None = None
    router_qa_type: str | None = None  # alias for backward compatibility

    # [PLAN]
    plan_task_type: str | None = None
    plan_source: dict[str, Any] = field(default_factory=dict)
    plan_targets: list[dict[str, Any]] = field(default_factory=list)
    plan_operands: list[dict[str, Any]] = field(default_factory=list)
    plan_options: dict[str, str] = field(default_factory=dict)
    plan_operation: str | None = None
    plan_scope: str | None = None

    # [RETRIEVAL_TASKS]
    retrieval_tasks: list[dict[str, Any]] = field(default_factory=list)

    # [RETRIEVAL_RESULTS]
    retrieval_target_results: list[dict[str, Any]] = field(default_factory=list)
    retrieval_recall_counts: dict[str, int] = field(default_factory=dict)
    retrieval_top_k: int = 0
    retrieval_sources: list[str] = field(default_factory=list)
    retrieval_status: str | None = None

    # [RERANK]
    rerank_results: list[dict[str, Any]] = field(default_factory=list)

    # [EXECUTOR]
    executor_type: str | None = None
    executor_status: str | None = None
    executor_matched_option: str | None = None
    executor_detail: str | None = None

    # [INTERMEDIATE_VERIFY]
    intermediate_verified_targets: list[str] = field(default_factory=list)
    intermediate_missing_targets: list[str] = field(default_factory=list)
    intermediate_conflicting_targets: list[str] = field(default_factory=list)
    intermediate_can_execute: bool | None = None

    # [CALCULATION]
    calculation_operation: str | None = None
    calculation_operands: list[dict[str, Any]] = field(default_factory=list)
    calculation_result: Any = None
    calculation_formula: str | None = None

    # [OPTION_VERIFY]
    option_verdicts: list[dict[str, Any]] = field(default_factory=list)
    option_selected: list[str] = field(default_factory=list)

    # [ANALYZER] (Legacy metadata)
    analyzer_keywords: list[str] = field(default_factory=list)
    analyzer_indicator: str | None = None
    analyzer_institution: str | None = None
    analyzer_time_period: str | None = None
    analyzer_document_name: str | None = None
    analyzer_article_number: str | None = None
    analyzer_rule_type: str | None = None
    analyzer_topic: str | None = None

    # [FINAL_VERIFY]
    verifier_answerable: bool | None = None
    verifier_reason_code: str | None = None
    verifier_reason: str | None = None
    verifier_supporting_ids: list[str] = field(default_factory=list)
    verifier_missing_info: list[str] = field(default_factory=list)
    core_claims: list[str] = field(default_factory=list)
    supported_core_claims: list[str] = field(default_factory=list)
    unsupported_core_claims: list[str] = field(default_factory=list)
    unsupported_optional_claims: list[str] = field(default_factory=list)
    grounding_action: str = "PASS"
    regeneration_triggered: bool = False
    initial_answer_preview: str = ""

    # [FINAL_ACTION]
    final_action: Literal["ANSWER", "REFUSE", "CLARIFY", "SYSTEM_META", "UNKNOWN"] = "UNKNOWN"
    final_status: str = "unknown"
    final_answer_preview: str = ""
    citations: list[str] = field(default_factory=list)

    # Performance / Latencies
    latency_ms: dict[str, int] = field(default_factory=dict)

    # Error Attribution Diagnostic
    stage_attribution: str | None = None
    failure_point: str | None = None
    diagnostic_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_formatted_log(self) -> str:
        """Format the exact multi-tag block required for visual & file inspection (Prompt 12)."""
        lines = [
            "\n" + "=" * 80,
            "【TRUSTWORTHY Q&A AUDIT LOG】",
            f"Trace ID: {self.trace_id} | Time: {self.timestamp}",
            "-" * 80,
            "[QUERY]",
            f"原始问题: {self.query}",
            "",
            "[ROUTER]",
            f"intent: {self.router_intent}",
            f"task_type: {self.router_task_type or self.router_qa_type or 'None'}",
            f"reason: {self.router_reason or 'None'}",
            "",
            "[PLAN]",
            f"task_type: {self.plan_task_type or 'N/A'}",
            f"source: {self.plan_source if self.plan_source else '未限定'}",
            f"operation: {self.plan_operation or 'N/A'}",
            f"targets: {self._format_plan_targets()}",
            f"operands: {self._format_plan_operands()}",
            f"options: {self.plan_options if self.plan_options else '无'}",
            "",
            "[RETRIEVAL_TASKS]",
            f"{self._format_retrieval_tasks()}",
            "",
            "[RETRIEVAL_RESULTS]",
            f"{self._format_retrieval_target_results()}",
            f"总体状态: {self.retrieval_status or 'N/A'} | 来源文件: {self.retrieval_sources if self.retrieval_sources else '无'}",
            "",
            "[EXECUTOR]",
            f"执行器类型: {self.executor_type or 'DIRECT_QA'}",
            f"执行状态: {self.executor_status or 'N/A'}",
            f"匹配选项/详情: {self.executor_matched_option or self.executor_detail or 'N/A'}",
            "",
            "[INTERMEDIATE_VERIFY]",
            f"是否允许执行 (can_execute): {self.intermediate_can_execute if self.intermediate_can_execute is not None else 'N/A'}",
            f"已验证数据: {self.intermediate_verified_targets if self.intermediate_verified_targets else '无'}",
            f"缺失项 (missing): {self.intermediate_missing_targets if self.intermediate_missing_targets else '无'}",
            f"冲突项 (conflicting): {self.intermediate_conflicting_targets if self.intermediate_conflicting_targets else '无'}",
            "",
            "[CALCULATION]",
            f"运算类型: {self.calculation_operation or 'N/A'}",
            f"输入操作数: {self._format_calculation_operands()}",
            f"计算公式/过程: {self.calculation_formula or 'N/A'}",
            f"计算结果: {self.calculation_result if self.calculation_result is not None else 'N/A'}",
            "",
            "[OPTION_VERIFY]",
            f"{self._format_option_verdicts()}",
            f"最终选定选项: {self.option_selected if self.option_selected else '无'}",
            "",
            "[FINAL_VERIFY]",
            f"是否满足回答条件 (answerable): {self.verifier_answerable}",
            f"错误码 (error_code): {self.verifier_reason_code or 'None'}",
            f"拦截原因 (issues): {self.verifier_reason or self.verifier_missing_info or '无'}",
            f"Grounding Action: {self.grounding_action} (RegenTriggered: {self.regeneration_triggered})",
            "",
            "[FINAL_ACTION]",
            f"ACTION: {self.final_action} (status={self.final_status})",
            f"引用标识 (citations): {self.citations}",
            f"耗时明细 (ms): {self.latency_ms}",
            f"故障定位诊断 (failure_point): {self.failure_point or '无错误 (正常执行)'}",
            f"故障归因推断 (attribution): {self.stage_attribution or 'NORMAL_EXECUTION'}",
            f"答案摘要: {self.final_answer_preview[:150]}...",
            "=" * 80,
        ]
        return "\n".join(lines)

    def _format_plan_targets(self) -> str:
        if not self.plan_targets:
            return "无"
        items = []
        for t in self.plan_targets:
            if isinstance(t, dict):
                row = t.get("row") or t.get("indicator") or ""
                col = t.get("column") or ""
                items.append(f"{row} ({col})" if col else row)
            else:
                items.append(str(t))
        return ", ".join(items) if items else "无"

    def _format_plan_operands(self) -> str:
        if not self.plan_operands:
            return "无"
        items = []
        for op in self.plan_operands:
            if isinstance(op, dict):
                items.append(op.get("name") or str(op))
            else:
                items.append(str(op))
        return ", ".join(items) if items else "无"

    def _format_retrieval_tasks(self) -> str:
        if not self.retrieval_tasks:
            return "无子检索任务 (单目标直检)"
        lines = []
        for t in self.retrieval_tasks:
            tid = t.get("task_id", "")
            target = t.get("target", "")
            query = t.get("query", "")
            lines.append(f"  - {tid}: target='{target}', query='{query}'")
        return "\n".join(lines)

    def _format_retrieval_target_results(self) -> str:
        if not self.retrieval_target_results:
            return f"召回总数: {self.retrieval_top_k} 条切片"
        lines = []
        for r in self.retrieval_target_results:
            tid = r.get("task_id", "")
            target = r.get("target", "")
            status = r.get("status", "SUCCESS")
            cnt = r.get("evidence_count", 0)
            lines.append(f"  - {tid} ({target}): {status} (命中 {cnt} 条切片)")
        return "\n".join(lines)

    def _format_calculation_operands(self) -> str:
        if not self.calculation_operands:
            return "N/A"
        items = []
        for op in self.calculation_operands:
            if isinstance(op, dict):
                name = op.get("name", "")
                val = op.get("value", "")
                unit = op.get("unit", "")
                items.append(f"{name}={val}{unit}")
            else:
                items.append(str(op))
        return ", ".join(items)

    def _format_option_verdicts(self) -> str:
        if not self.option_verdicts:
            return "N/A (非选择题任务)"
        lines = []
        for v in self.option_verdicts:
            lbl = v.get("option", "")
            verdict = v.get("verdict", "")
            ev_ids = v.get("evidence_ids", [])
            reason = v.get("reason", "")
            lines.append(f"  - {lbl}: {verdict} (evidence={ev_ids}, reason={reason})")
        return "\n".join(lines)


class AuditLogger:
    """Manages recording of trustworthy Q&A traces to disk and structured output."""

    @staticmethod
    def record_trace(trace: QAFlowTrace) -> None:
        """Write trace to application logger and persistent jsonl audit file."""
        # 1. Human-readable formatted console & app.log
        formatted_log = trace.to_formatted_log()
        logger.info(formatted_log)

        # 2. Append to JSONL audit file for automated benchmark evaluation
        try:
            target_path = get_audit_log_path()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[AuditLogger] 写入审计日志文件失败: {e}")

    @staticmethod
    def infer_failure_point(
        router_intent: str | None,
        router_task_type: str | None,
        has_plan: bool,
        retrieval_count: int,
        retrieval_status: str | None,
        executor_status: str | None,
        intermediate_missing: list[str],
        option_status: str | None,
        verifier_answerable: bool | None,
        verification_passed: bool,
        error_code: str | None,
        final_status: str,
    ) -> tuple[str, str]:
        """Infer pinpointed failure stage and attribution to aid debugging (Prompt 12).
        
        Distinguishes whether the failure occurred at:
          - Router 错
          - Planner 错
          - 检索错
          - 取数错
          - 计算错
          - Option Verify 错
          - 最终回答/事后核验错
        """
        # Case 1: Router
        if router_intent == "SYSTEM_META":
            return "SYSTEM_META", "正常命中系统定位与元信息 [Stage: ROUTER]"
        if router_intent == "OUT_OF_SCOPE":
            return "ROUTER_OUT_OF_SCOPE", "由 Router 直接拒答领域外问题 [Stage: ROUTER]"
        if router_intent == "NEED_CLARIFICATION" or error_code == "AMBIGUOUS_QUERY" or final_status == "needs_clarification":
            return "AMBIGUOUS_QUERY", "Router 判定需澄清：问题表述模糊或缺少必要判断条件 [Stage: ROUTER]"

        # Case 2: Planner
        if router_task_type in {"TABLE_COMPARE", "TABLE_CALCULATION", "TABLE_LOOKUP", "FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"} and not has_plan:
            return "PLANNER_ERROR", "Planner 错：未能为任务生成有效执行计划 [Stage: PLANNER]"

        # Case 3: Retrieval
        if retrieval_count == 0 or retrieval_status == "no_evidence" or error_code == "RETRIEVAL_FAILED":
            return "RETRIEVAL_FAILED", "检索错：检索模块未召回任何有效知识切片 [Stage: RETRIEVAL]"

        # Case 4: Table Lookup / Extraction
        is_table_task = router_task_type in {"TABLE_COMPARE", "TABLE_CALCULATION", "TABLE_LOOKUP"}
        if is_table_task and (error_code == "MISSING_OPERAND" or executor_status == "MISSING_OPERAND" or intermediate_missing):
            return "MISSING_OPERAND", "取数错：表格中未定位或未能提取指定候选指标/操作数 [Stage: TABLE_EXECUTION]"

        # Case 5: Table Calculation
        if is_table_task and (error_code == "CALCULATION_FAILED" or executor_status == "CALCULATION_ERROR"):
            return "CALCULATION_FAILED", "计算错：算术执行器遭遇异常（如除零、数学执行错误） [Stage: TABLE_EXECUTION]"

        # Case 6: Option Verification
        if error_code in {"OPTION_NOT_VERIFIED", "INSUFFICIENT_OPTIONS"} or option_status in {"NO_DECISION", "FAILED", "CONFLICTING"}:
            return "OPTION_VERIFY_ERROR", "Option Verify 错：选项在知识库中未找到充分支持或存在冲突 [Stage: OPTION_VERIFICATION]"

        # Case 7: KB Missing Evidence
        if verifier_answerable is False or error_code in {"MISSING_EVIDENCE", "NO_RELEVANT_EVIDENCE"}:
            return "MISSING_EVIDENCE", "知识库缺失：知识库中未收录对应法规条款依据 [Stage: RETRIEVAL/VERIFIER]"

        # Case 8: Post-generation Grounding / Hallucination Interception
        if verifier_answerable is True and not verification_passed:
            return "GROUNDING_FAILED", "最终回答错：事后事实一致性核验拦截（包含未证实推测或幻觉） [Stage: POST_VERIFICATION]"

        if not verification_passed:
            return "GROUNDING_FAILED", "最终回答错：答案未能通过事实一致性核验 [Stage: POST_VERIFICATION]"

        if final_status in ("answered", "degraded"):
            return "SUCCESS_ANSWERED", "无错误 (全流程成功执行)"

        return "UNKNOWN_STAGE", "未明确阶段"

    @staticmethod
    def infer_stage_attribution(
        router_intent: str | None,
        retrieval_count: int,
        verifier_answerable: bool | None,
        verifier_reason_code: str | None,
        final_status: str,
        verification_passed: bool,
    ) -> tuple[str, str]:
        """Backward-compatible stage attribution wrapper."""
        return AuditLogger.infer_failure_point(
            router_intent=router_intent,
            router_task_type=None,
            has_plan=True,
            retrieval_count=retrieval_count,
            retrieval_status=None,
            executor_status=None,
            intermediate_missing=[],
            option_status=None,
            verifier_answerable=verifier_answerable,
            verification_passed=verification_passed,
            error_code=verifier_reason_code,
            final_status=final_status,
        )


audit_logger = AuditLogger()
