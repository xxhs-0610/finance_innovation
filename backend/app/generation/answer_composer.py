"""Answer Composer Module for RegTrust-RAG (Prompt 9 & 10).

The Answer Composer formats and renders natural language responses from
deterministic execution results and verified evidence.
Decoupled from raw file formats via UnifiedEvidence and EvidenceAdapter.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from app.schemas.option_verification_schema import OptionVerificationResponse
from app.schemas.table_execution_schema import TableExecutionResult
from app.schemas.task_plan_schema import TaskPlan
from app.utils.logger import get_logger

logger = get_logger("app.generation.answer_composer")


class AnswerComposer:
    """Natural Language Response Composer from verified structured results."""

    def _build_evidence_citation(
        self,
        default_title: str,
        evidence: Sequence[Any] | None,
        default_suffix: str = "相关统计数据",
    ) -> str:
        """Format citation based on UnifiedEvidence source type and location (PDF, Word, Excel)."""
        if evidence:
            from app.retrieval.evidence_adapter import evidence_adapter
            adapted = evidence_adapter.adapt_list(evidence)
            if adapted:
                e = adapted[0]
                title = e.source_title or default_title
                loc = e.location or {}
                if e.source_type == "pdf" and loc.get("page"):
                    loc_desc = f"（第 {loc['page']} 页）"
                elif e.source_type == "word" and loc.get("article"):
                    loc_desc = f"{loc['article']}"
                elif e.source_type == "excel" and loc.get("sheet"):
                    loc_desc = f"（{loc['sheet']}）"
                else:
                    loc_desc = ""
                cid = e.citation_id or "E1"
                return f"\n依据：《{title}》{loc_desc}{default_suffix}。 [{cid}]"

        return f"\n依据：《{default_title}》{default_suffix}。 [E1]"

    def compose_table_compare_answer(
        self,
        exec_result: TableExecutionResult,
        task_plan: TaskPlan,
        evidence: Sequence[Any] | None = None,
    ) -> str:
        """Compose answer for TABLE_COMPARE tasks."""
        operation = (exec_result.operation or task_plan.operation or "MAX").upper()
        op_cn = "数值最高" if operation != "MIN" else "数值最低"

        winner_label = exec_result.matched_option or "A"
        winner_op = next((op for op in exec_result.operands if op.name), None)
        winner_name = winner_op.name if winner_op else ""
        winner_val = exec_result.result
        unit_str = f" {exec_result.unit}" if exec_result.unit else ""

        # Find winner candidate object
        candidates = task_plan.candidates
        if not candidates and task_plan.options:
            from app.schemas.task_plan_schema import TableCandidate
            candidates = [TableCandidate(label=k, target=v) for k, v in task_plan.options.items()]

        for c, op in zip(candidates, exec_result.operands):
            if c.label == winner_label:
                winner_name = c.target
                winner_val = op.value
                unit_str = f" {op.unit}" if op.unit else unit_str
                break

        scope_str = f"在“{task_plan.scope}”口径下，" if task_plan.scope else ""
        source_name = task_plan.source.file_name or "监管统计报表"
        sheet_desc = f"（{task_plan.source.sheet_name}）" if task_plan.source.sheet_name else ""

        lines = [
            f"答案：**{winner_label}. {winner_name}**。\n",
            f"{scope_str}四个选项中【{winner_name}】{op_cn}（数值为 {winner_val}{unit_str}）。\n",
            "**各项候选数据明细**：",
        ]

        for c, op in zip(candidates, exec_result.operands):
            val_display = f"{op.value}" if op.value is not None else "未提取"
            op_unit = f" {op.unit}" if op.unit else ""
            lines.append(f"- {c.label}. {c.target}: {val_display}{op_unit}")

        if task_plan.source.sheet_name:
            lines.append(f"\n依据：《{source_name}》{sheet_desc}相关统计数据。 [E1]")
        else:
            lines.append(self._build_evidence_citation(source_name, evidence, "相关统计数据"))
        return "\n".join(lines)

    def compose_table_calculation_answer(
        self,
        exec_result: TableExecutionResult,
        task_plan: TaskPlan,
        evidence: Sequence[Any] | None = None,
    ) -> str:
        """Compose answer for TABLE_CALCULATION tasks."""
        val = exec_result.result
        unit_str = f" {exec_result.unit}" if exec_result.unit else ""

        # Determine answer prefix
        if exec_result.matched_option:
            ans_header = f"答案：**{exec_result.matched_option}. {val}{unit_str}**。"
        else:
            ans_header = f"答案：**{val}{unit_str}**。"

        source_name = task_plan.source.file_name or "监管统计报表"
        sheet_desc = f"（{task_plan.source.sheet_name}）" if task_plan.source.sheet_name else ""

        # Extract calculation expression from operands
        calc_expr = exec_result.explanation or ""
        if "执行运算" in calc_expr:
            calc_expr = calc_expr.split("执行运算")[1].strip("：:\n ")

        lines = [
            ans_header,
            "\n计算：",
        ]

        if exec_result.operands and len(exec_result.operands) >= 2:
            op1, op2 = exec_result.operands[0], exec_result.operands[1]
            op_type = (task_plan.operation or exec_result.operation or "SUBTRACT").upper()
            if op_type in {"SUBTRACT", "MINUS"}:
                lines.append(f"{op2.name} {op2.value} - {op1.name} {op1.value} = {val}{unit_str}。")
            elif op_type in {"ADD", "SUM"}:
                lines.append(f"{op1.name} {op1.value} + {op2.name} {op2.value} = {val}{unit_str}。")
            elif op_type == "ABS_DIFFERENCE":
                lines.append(f"|{op1.name} {op1.value} - {op2.name} {op2.value}| = {val}{unit_str}。")
            elif op_type == "RATIO":
                lines.append(f"{op1.name} {op1.value} / {op2.name} {op2.value} = {val}{unit_str}。")
            elif op_type == "CHANGE_RATE":
                lines.append(f"({op2.name} {op2.value} - {op1.name} {op1.value}) / {op1.name} {op1.value} = {val}{unit_str}。")
            else:
                lines.append(f"{calc_expr} = {val}{unit_str}。")
        else:
            lines.append(f"{calc_expr}")

        lines.append("\n**取数明细**：")
        for op in exec_result.operands:
            op_unit = f" {op.unit}" if op.unit else ""
            lines.append(f"- {op.name}: {op.value}{op_unit}")

        lines.append(f"\n依据：《{source_name}》{sheet_desc}相关统计报表。 [E1]")
        return "\n".join(lines)

    def compose_table_lookup_answer(
        self,
        exec_result: TableExecutionResult,
        task_plan: TaskPlan,
        evidence: Sequence[Any] | None = None,
    ) -> str:
        """Compose answer for TABLE_LOOKUP tasks."""
        val = exec_result.result
        unit_str = f" {exec_result.unit}" if exec_result.unit else ""
        main_op = exec_result.operands[0] if exec_result.operands else None
        target_name = main_op.name if main_op else "目标指标"

        if exec_result.matched_option:
            ans_header = f"答案：**{exec_result.matched_option}. {val}{unit_str}**。"
        else:
            ans_header = f"答案：**{val}{unit_str}**。"

        source_name = task_plan.source.file_name or "监管统计报表"
        sheet_desc = f"（{task_plan.source.sheet_name}）" if task_plan.source.sheet_name else ""
        scope_str = f"在“{task_plan.scope}”口径下，" if task_plan.scope else ""

        lines = [
            ans_header,
            f"\n根据相关监管统计报表，{scope_str}指标【{target_name}】数值为 **{val}{unit_str}**。",
            f"\n依据：《{source_name}》{sheet_desc}相关统计数据。 [E1]",
        ]
        return "\n".join(lines)

    def compose_fact_choice_answer(
        self,
        verify_response: OptionVerificationResponse,
        task_plan: TaskPlan,
        evidence: Sequence[Any] | None = None,
    ) -> str:
        """Compose answer for FACT_SINGLE_CHOICE / FACT_MULTI_CHOICE tasks."""
        winner_str = "、".join(verify_response.selected_options)
        source_name = (
            task_plan.source_constraints.document_name
            if task_plan.source_constraints
            else None
        ) or "监管制度文件"

        lines = [
            f"答案：**{winner_str}**。\n",
            verify_response.explanation,
            f"\n依据：《{source_name}》官方规定条款。 [E1]",
        ]
        return "\n".join(lines)


answer_composer = AnswerComposer()
