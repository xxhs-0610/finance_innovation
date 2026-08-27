"""Intermediate Evidence Verification Engine (Prompt 8).

Performs intermediate evidence verification on multi-target tasks:
  - TABLE_COMPARE: Verifies all candidate values (A, B, C, D) prior to programmatic comparison
  - TABLE_CALCULATION: Verifies all operands (Op1, Op2) prior to arithmetic calculation
  - TABLE_LOOKUP: Verifies multi-target coordinate extraction
  - FACT_SINGLE_CHOICE / FACT_MULTI_CHOICE: Verifies discrete option grounding

Returns standardized structure:
{
  "task_complete": true/false,
  "missing_targets": [],
  "conflicting_targets": [],
  "verified_targets": [],
  "can_execute": true/false
}
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.schemas.intermediate_verification_schema import (
    IntermediateTargetItem,
    IntermediateVerificationResult,
)
from app.schemas.table_execution_schema import TableOperandResult
from app.schemas.task_plan_schema import TaskPlan
from app.utils.logger import get_logger

logger = get_logger("app.retrieval.intermediate_verifier")


class IntermediateEvidenceVerifier:
    """Intermediate Evidence Verifier for Multi-Target Tasks."""

    def verify_table_compare(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> tuple[IntermediateVerificationResult, list[TableOperandResult]]:
        """Verify that all comparison candidate values (A, B, C, D) are available and valid."""
        from app.retrieval.table_executor import _normalize_retrieval_input, extract_operand_value

        task_map, merged_evidence = _normalize_retrieval_input(retrieval_input)
        operands: list[TableOperandResult] = []
        target_items: list[IntermediateTargetItem] = []

        verified_names: list[str] = []
        missing_names: list[str] = []
        conflicting_names: list[str] = []

        candidates = task_plan.candidates
        if not candidates and task_plan.options:
            # Reconstruct candidates from options dict
            from app.schemas.task_plan_schema import TableCandidate
            candidates = [TableCandidate(label=k, target=v) for k, v in task_plan.options.items()]

        for cand in candidates:
            task_id = f"CAND_{cand.label}"
            evidence = task_map.get(task_id) or merged_evidence
            op = extract_operand_value(
                evidence,
                cand.target,
                row=cand.target,
                scope=task_plan.scope,
            )
            operands.append(op)

            cand_display = f"{cand.label}. {cand.target}" if cand.label else cand.target
            if op.verified and op.value is not None:
                verified_names.append(cand.label or cand.target)
                target_items.append(
                    IntermediateTargetItem(
                        name=cand_display,
                        target_type="CANDIDATE",
                        status="VERIFIED",
                        value=op.value,
                        unit=op.unit,
                        evidence_id=op.evidence_id,
                        reason=f"成功从表格提取候选值: {op.value} {op.unit}".strip(),
                    )
                )
            else:
                missing_names.append(cand.label or cand.target)
                target_items.append(
                    IntermediateTargetItem(
                        name=cand_display,
                        target_type="CANDIDATE",
                        status="MISSING",
                        value=None,
                        unit="",
                        reason=op.error or f"知识库表格中未包含候选项 [{cand_display}] 的数值",
                    )
                )

        # Unit compatibility check across verified candidates
        units = {op.unit for op in operands if op.verified and op.unit}
        if len(units) > 1 and not ("%" in units and any(u for u in units if u != "%")):
            # If completely disparate non-convertible units (e.g. 人数 vs 亿元)
            pass

        task_complete = len(missing_names) == 0 and len(operands) > 0
        can_execute = task_complete

        error_code = None
        explanation = ""
        if not task_complete:
            error_code = "MISSING_OPERAND"
            explanation = f"表格比较缺少以下必要候选项数值: {', '.join(missing_names)}"
        else:
            explanation = f"所有 {len(verified_names)} 项候选数值均已通过中间证据核验，可执行程序比较"

        res = IntermediateVerificationResult(
            task_complete=task_complete,
            can_execute=can_execute,
            verified_targets=verified_names,
            missing_targets=missing_names,
            conflicting_targets=conflicting_names,
            error_code=error_code,
            explanation=explanation,
            details=target_items,
            diagnostics={"candidate_count": len(candidates), "verified_count": len(verified_names)},
        )
        return res, operands

    def verify_table_calculation(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> tuple[IntermediateVerificationResult, list[TableOperandResult]]:
        """Verify that all calculation operands (Operand1, Operand2) are available and valid."""
        from app.retrieval.table_executor import _normalize_retrieval_input, extract_operand_value

        task_map, merged_evidence = _normalize_retrieval_input(retrieval_input)
        operands: list[TableOperandResult] = []
        target_items: list[IntermediateTargetItem] = []

        verified_names: list[str] = []
        missing_names: list[str] = []
        conflicting_names: list[str] = []

        for idx, op_item in enumerate(task_plan.operands, 1):
            task_id = f"OPERAND_{idx}"
            evidence = task_map.get(task_id) or merged_evidence
            op = extract_operand_value(
                evidence,
                op_item.name,
                row=op_item.row,
                column=op_item.column,
            )
            operands.append(op)

            if op.verified and op.value is not None:
                verified_names.append(op_item.name)
                target_items.append(
                    IntermediateTargetItem(
                        name=op_item.name,
                        target_type="OPERAND",
                        status="VERIFIED",
                        value=op.value,
                        unit=op.unit,
                        evidence_id=op.evidence_id,
                        reason=f"成功从表格提取操作数值: {op.value} {op.unit}".strip(),
                    )
                )
            else:
                missing_names.append(op_item.name)
                target_items.append(
                    IntermediateTargetItem(
                        name=op_item.name,
                        target_type="OPERAND",
                        status="MISSING",
                        value=None,
                        unit="",
                        reason=op.error or f"知识库表格中未提取到操作数 [{op_item.name}] 的有效数值",
                    )
                )

        task_complete = len(missing_names) == 0 and len(operands) > 0
        can_execute = task_complete

        error_code = None
        explanation = ""
        if not task_complete:
            error_code = "MISSING_OPERAND"
            explanation = f"表格计算缺少必要的操作数值: {', '.join(missing_names)}"
        else:
            explanation = f"所有 {len(verified_names)} 个操作数数值均已通过中间证据核验，可执行程序计算"

        res = IntermediateVerificationResult(
            task_complete=task_complete,
            can_execute=can_execute,
            verified_targets=verified_names,
            missing_targets=missing_names,
            conflicting_targets=conflicting_names,
            error_code=error_code,
            explanation=explanation,
            details=target_items,
            diagnostics={"operand_count": len(task_plan.operands), "verified_count": len(verified_names)},
        )
        return res, operands

    def verify_table_lookup(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> tuple[IntermediateVerificationResult, list[TableOperandResult]]:
        """Verify that table coordinate lookup targets are available."""
        from app.retrieval.table_executor import _normalize_retrieval_input, extract_operand_value

        task_map, merged_evidence = _normalize_retrieval_input(retrieval_input)
        operands: list[TableOperandResult] = []
        target_items: list[IntermediateTargetItem] = []

        verified_names: list[str] = []
        missing_names: list[str] = []
        conflicting_names: list[str] = []

        for idx, target_item in enumerate(task_plan.targets, 1):
            task_id = f"TARGET_{idx}"
            evidence = task_map.get(task_id) or merged_evidence
            name = target_item.indicator or target_item.row or f"Target_{idx}"
            op = extract_operand_value(
                evidence,
                name,
                row=target_item.row,
                column=target_item.column,
                scope=task_plan.scope,
            )
            operands.append(op)

            if op.verified and op.value is not None:
                verified_names.append(name)
                target_items.append(
                    IntermediateTargetItem(
                        name=name,
                        target_type="TABLE_CELL",
                        status="VERIFIED",
                        value=op.value,
                        unit=op.unit,
                        evidence_id=op.evidence_id,
                        reason=f"成功从表格提取坐标值: {op.value} {op.unit}".strip(),
                    )
                )
            else:
                missing_names.append(name)
                target_items.append(
                    IntermediateTargetItem(
                        name=name,
                        target_type="TABLE_CELL",
                        status="MISSING",
                        value=None,
                        unit="",
                        reason=op.error or f"知识库表格中未包含指标 [{name}] 的有效数值",
                    )
                )

        task_complete = len(missing_names) == 0 and len(operands) > 0
        can_execute = task_complete

        error_code = None
        explanation = ""
        if not task_complete:
            error_code = "MISSING_OPERAND"
            explanation = f"未能从表格中获取到以下指标数值: {', '.join(missing_names)}"
        else:
            explanation = f"表格取数指标均已通过核验"

        res = IntermediateVerificationResult(
            task_complete=task_complete,
            can_execute=can_execute,
            verified_targets=verified_names,
            missing_targets=missing_names,
            conflicting_targets=conflicting_names,
            error_code=error_code,
            explanation=explanation,
            details=target_items,
            diagnostics={"target_count": len(task_plan.targets), "verified_count": len(verified_names)},
        )
        return res, operands

    def verify_choice_options(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> IntermediateVerificationResult:
        """Verify intermediate discrete evidence grounding per choice option."""
        from app.retrieval.option_verifier import option_verifier

        opt_resp = option_verifier.verify(task_plan, retrieval_input)

        verified_names: list[str] = []
        missing_names: list[str] = []
        conflicting_names: list[str] = []
        target_items: list[IntermediateTargetItem] = []

        for vo in opt_resp.options_verification:
            if vo.verdict == "SUPPORTED":
                verified_names.append(vo.option)
                st = "VERIFIED"
            elif vo.verdict == "CONTRADICTED":
                conflicting_names.append(vo.option)
                st = "CONFLICTING"
            else:
                missing_names.append(vo.option)
                st = "MISSING"

            target_items.append(
                IntermediateTargetItem(
                    name=f"选项 {vo.option}",
                    target_type="OPTION",
                    status=st,
                    value=vo.claim,
                    unit="",
                    evidence_id=",".join(vo.evidence_ids),
                    reason=vo.reason,
                )
            )

        task_complete = opt_resp.status == "SUCCESS" and len(opt_resp.selected_options) > 0
        can_execute = task_complete
        error_code = None if can_execute else "INSUFFICIENT_EVIDENCE"

        return IntermediateVerificationResult(
            task_complete=task_complete,
            can_execute=can_execute,
            verified_targets=verified_names,
            missing_targets=missing_names,
            conflicting_targets=conflicting_names,
            error_code=error_code,
            explanation=opt_resp.explanation,
            details=target_items,
            diagnostics={"selected_options": opt_resp.selected_options, "status": opt_resp.status},
        )

    def verify(
        self,
        task_plan: TaskPlan,
        retrieval_input: Any,
    ) -> IntermediateVerificationResult:
        """Main dispatcher for intermediate evidence verification."""
        task_type = task_plan.task_type
        if task_type == "TABLE_COMPARE":
            res, _ = self.verify_table_compare(task_plan, retrieval_input)
            return res
        elif task_type == "TABLE_CALCULATION":
            res, _ = self.verify_table_calculation(task_plan, retrieval_input)
            return res
        elif task_type == "TABLE_LOOKUP":
            res, _ = self.verify_table_lookup(task_plan, retrieval_input)
            return res
        elif task_type in {"FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"}:
            return self.verify_choice_options(task_plan, retrieval_input)
        else:
            # DIRECT_FACT_QA default
            return IntermediateVerificationResult(
                task_complete=True,
                can_execute=True,
                verified_targets=["DIRECT_FACT"],
                explanation="单点事实问答进入端到端核验",
            )


intermediate_verifier = IntermediateEvidenceVerifier()
