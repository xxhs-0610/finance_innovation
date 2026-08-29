"""Table Executor for RegTrust-RAG (Prompt 5).

Provides deterministic table execution for:
  - TABLE_LOOKUP: File -> Sheet -> Row -> Column coordinate extraction and verification
  - TABLE_COMPARE: Multi-candidate value extraction -> unit checking -> programmatic MAX/MIN/SORT -> option matching
  - TABLE_CALCULATION: Multi-operand value extraction -> programmatic arithmetic calculation (ADD, SUBTRACT, ABS_DIFFERENCE, SUM, RATIO, CHANGE_RATE, MAX, MIN, AVERAGE) -> option matching

Strictly avoids LLM free hallucination on math/comparisons.
Returns MISSING_OPERAND (never NEED_CLARIFICATION) when evidence is incomplete.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from app.schemas.chunk_schema import SearchResult
from app.schemas.multi_target_retrieval_schema import (
    MultiTargetRetrievalResponse,
    TargetRetrievalResult,
)
from app.schemas.table_execution_schema import (
    TableExecutionResult,
    TableOperandResult,
)
from app.schemas.task_plan_schema import TaskPlan
from app.utils.logger import get_logger

logger = get_logger("app.retrieval.table_executor")


def parse_table_chunk_kv(text: str) -> tuple[dict[str, float | str], str]:
    """Parse text formatted key-value pairs and unit from a table chunk."""
    kv_map: dict[str, float | str] = {}
    unit = ""

    m_unit = re.search(r"单位[：:]\s*([^\s\|\n]+)", text)
    if m_unit:
        unit = m_unit.group(1).strip()

    parts = re.split(r"[\|\n]+", text)
    for part in parts:
        part = part.strip()
        if (
            not part
            or part.startswith("期间：")
            or part.startswith("期间:")
            or part.startswith("单位：")
            or part.startswith("单位:")
            or part.startswith("规模：")
            or part.startswith("规模:")
            or part.startswith("范围：")
            or part.startswith("范围:")
            or part.startswith("行：")
            or part.startswith("行:")
            or part.startswith("行=")
        ):
            continue
        entries = re.split(r"[；;]", part)
        for entry in entries:
            entry = entry.strip()
            if "=" in entry:
                k, v = entry.split("=", 1)
                k = k.strip()
                v = v.strip()
                clean_v = v.replace(",", "")
                num_match = re.search(r"^[-+]?\d+(?:\.\d+)?", clean_v)
                if num_match:
                    try:
                        kv_map[k] = float(num_match.group(0))
                    except ValueError:
                        kv_map[k] = v
                else:
                    kv_map[k] = v
    return kv_map, unit


def extract_operand_value(
    evidence_list: Sequence[Any],
    target_name: str,
    *,
    row: str | None = None,
    column: str | None = None,
    scope: str | None = None,
) -> TableOperandResult:
    """Extract a numeric value for an operand or candidate from UnifiedEvidence or raw chunks across Excel, Word, PDF."""
    from app.retrieval.evidence_adapter import evidence_adapter

    adapted_list = evidence_adapter.adapt_list(evidence_list)
    for chunk in adapted_list:
        text = chunk.content
        chunk_id = chunk.evidence_id

        # If row is specified, ensure chunk relates to the row
        if row and row not in text:
            loc_row = str(chunk.location.get("row", ""))
            if row not in loc_row:
                row_clean = row.replace(" ", "")
                text_clean = text.replace(" ", "")
                if row_clean not in text_clean:
                    continue

        if isinstance(chunk.structured_value, dict) and "kv" in chunk.structured_value:
            kv_map = chunk.structured_value["kv"]
            unit = chunk.structured_value.get("unit", "")
        else:
            kv_map, unit = parse_table_chunk_kv(text)

        if not kv_map:
            # Word / PDF regulatory text numeric fallback (e.g. 注册资本不低于3亿元)
            m_target = re.search(
                re.escape(target_name) + r"[^\d]*?([-+]?\d+(?:\.\d+)?)\s*([%|亿元|万元|千元|元|个|家|月|年]*)",
                text,
            )
            if m_target:
                try:
                    val = float(m_target.group(1))
                    u = m_target.group(2).strip()
                    return TableOperandResult(
                        name=target_name,
                        value=val,
                        unit=u or unit,
                        verified=True,
                        evidence_id=chunk_id,
                        row_header=row or "",
                        col_header=column or "",
                    )
                except ValueError:
                    pass
            continue

        search_keys = [t for t in (column, target_name) if t]

        # 1. Exact or composite key matching with scope/column
        for sk in search_keys:
            for k, val in kv_map.items():
                if isinstance(val, (int, float)):
                    # Case A: scope and sk both in k (e.g. 截至当期 / 账面余额)
                    if scope and scope in k and (sk in k or k.endswith(sk)):
                        return TableOperandResult(
                            name=target_name,
                            value=val,
                            unit=unit,
                            verified=True,
                            evidence_id=chunk_id,
                            row_header=row or "",
                            col_header=k,
                        )
                    # Case B: k exactly equals or ends with sk
                    if k == sk or k.endswith(f"/ {sk}") or k.endswith(sk):
                        return TableOperandResult(
                            name=target_name,
                            value=val,
                            unit=unit,
                            verified=True,
                            evidence_id=chunk_id,
                            row_header=row or "",
                            col_header=k,
                        )

        # 2. Relaxed match with scope tokens (must ensure target is in chunk text)
        target_in_chunk = any(sk in text for sk in search_keys)
        if scope and target_in_chunk:
            scope_tokens = [t for t in re.split(r"[-/\s]", scope) if t]
            for k, val in kv_map.items():
                if isinstance(val, (int, float)):
                    if all(st in k for st in scope_tokens):
                        return TableOperandResult(
                            name=target_name,
                            value=val,
                            unit=unit,
                            verified=True,
                            evidence_id=chunk_id,
                            row_header=row or "",
                            col_header=k,
                        )

        # 3. Single numeric key fallback ONLY if target explicitly appears in chunk text
        if target_in_chunk:
            num_items = [(k, v) for k, v in kv_map.items() if isinstance(v, (int, float))]
            if len(num_items) == 1:
                k, v = num_items[0]
                return TableOperandResult(
                    name=target_name,
                    value=v,
                    unit=unit,
                    verified=True,
                    evidence_id=chunk_id,
                    row_header=row or "",
                    col_header=k,
                )

    return TableOperandResult(
        name=target_name,
        verified=False,
        error=f"未能从证据中提取到 [{target_name}] 的有效数值",
    )


def _normalize_retrieval_input(
    retrieval_input: Any,
) -> tuple[dict[str, list[Any]], list[Any]]:
    """Helper returning (task_id -> evidence_list, merged_evidence)."""
    task_map: dict[str, list[Any]] = {}
    merged: list[Any] = []

    if retrieval_input is None:
        return task_map, merged

    if isinstance(retrieval_input, MultiTargetRetrievalResponse):
        for r in retrieval_input.retrieval_results:
            task_map[r.task_id] = list(r.evidence)
        merged = list(retrieval_input.merged_evidence)
        return task_map, merged

    if hasattr(retrieval_input, "diagnostics") and isinstance(retrieval_input.diagnostics, dict):
        diag = retrieval_input.diagnostics
        if "multi_target" in diag and isinstance(diag["multi_target"], dict):
            mt = diag["multi_target"]
            for r in mt.get("retrieval_results", []):
                task_map[r.get("task_id", "")] = r.get("evidence", [])
            merged = mt.get("merged_evidence", [])
        elif "retrieval_results" in diag:
            for r in diag.get("retrieval_results", []):
                task_map[r.get("task_id", "")] = r.get("evidence", [])
        if not merged and hasattr(retrieval_input, "evidence"):
            merged = list(retrieval_input.evidence)

    if isinstance(retrieval_input, dict):
        # Case A: direct multi_target dict with "retrieval_results"
        if "retrieval_results" in retrieval_input:
            for r in retrieval_input.get("retrieval_results", []):
                task_map[r.get("task_id", "")] = r.get("evidence", [])
            merged = retrieval_input.get("merged_evidence", [])
        # Case B: dict containing diagnostics.multi_target
        diag = retrieval_input.get("diagnostics", {})
        if isinstance(diag, dict) and "multi_target" in diag:
            mt = diag["multi_target"]
            if isinstance(mt, dict):
                for r in mt.get("retrieval_results", []):
                    task_map[r.get("task_id", "")] = r.get("evidence", [])
                if not merged:
                    merged = mt.get("merged_evidence", [])
        if not merged:
            merged = retrieval_input.get("evidence", [])

    if isinstance(retrieval_input, (list, tuple)):
        merged = list(retrieval_input)

    # Fallback: if task_map is incomplete, partition merged evidence by matched_target_task
    if merged:
        for item in merged:
            meta = item.get("metadata", {}) if isinstance(item, dict) else getattr(item, "metadata", {})
            if isinstance(meta, dict):
                tid = meta.get("matched_target_task")
                if tid:
                    task_map.setdefault(tid, []).append(item)

    return task_map, merged


def match_numeric_option(
    result_value: float, options: Mapping[str, str] | None
) -> tuple[str | None, float]:
    """Find the best matching multiple-choice option (A, B, C, D) by numerical proximity."""
    if not options or not isinstance(options, dict):
        return None, 0.0

    best_label: str | None = None
    min_diff = float("inf")

    for label, text in options.items():
        # Match float or int or negative numbers
        nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
        if not nums:
            continue
        try:
            opt_val = float(nums[0])
            diff = abs(opt_val - result_value)
            if diff < min_diff:
                min_diff = diff
                best_label = label
        except ValueError:
            continue

    # Never force a choice when all candidates are materially different from
    # the extracted value. Accept exact/display rounding (absolute tolerance)
    # or a small relative rounding difference only.
    tolerance = max(0.01, abs(float(result_value)) * 0.001)
    if best_label is None or min_diff > tolerance:
        return None, min_diff
    return best_label, min_diff


class TableExecutor:
    """Deterministic Table Execution Engine."""

    def execute(
        self,
        task_plan: TaskPlan,
        retrieval_response: Any,
    ) -> TableExecutionResult:
        """Execute deterministic table operation based on task_plan."""
        task_type = task_plan.task_type

        if task_type == "TABLE_LOOKUP":
            return self.execute_lookup(task_plan, retrieval_response)
        elif task_type == "TABLE_COMPARE":
            return self.execute_compare(task_plan, retrieval_response)
        elif task_type == "TABLE_CALCULATION":
            return self.execute_calculation(task_plan, retrieval_response)
        else:
            return TableExecutionResult(
                status="FAILED",
                task_type=task_type,
                explanation=f"TableExecutor 不支持的任务类型: {task_type}",
            )

    def execute_lookup(
        self,
        task_plan: TaskPlan,
        retrieval_response: Any,
    ) -> TableExecutionResult:
        """Execute TABLE_LOOKUP: single or multi-target coordinate extraction."""
        from app.retrieval.intermediate_verifier import intermediate_verifier

        interm_res, operands = intermediate_verifier.verify_table_lookup(
            task_plan, retrieval_response
        )
        if not interm_res.can_execute:
            return TableExecutionResult(
                status="MISSING_OPERAND",
                task_type="TABLE_LOOKUP",
                operands=operands,
                intermediate_verification=interm_res.to_dict(),
                explanation=interm_res.explanation,
                diagnostics={"intermediate_verification": interm_res.to_dict()},
            )

        main_op = operands[0]
        result_val = main_op.value
        matched_opt, _ = match_numeric_option(result_val, task_plan.options)

        return TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_LOOKUP",
            operation="LOOKUP",
            operands=operands,
            result=result_val,
            unit=main_op.unit,
            matched_option=matched_opt,
            explanation=f"成功从表格提取指标【{main_op.name}】数值为 {result_val} {main_op.unit}".strip(),
            intermediate_verification=interm_res.to_dict(),
            diagnostics={"target_count": len(operands), "intermediate_verification": interm_res.to_dict()},
        )

    def execute_compare(
        self,
        task_plan: TaskPlan,
        retrieval_response: Any,
    ) -> TableExecutionResult:
        """Execute TABLE_COMPARE: extract candidate values -> programmatic MAX/MIN/SORT."""
        from app.retrieval.intermediate_verifier import intermediate_verifier

        interm_res, operands = intermediate_verifier.verify_table_compare(
            task_plan, retrieval_response
        )
        if not interm_res.can_execute:
            return TableExecutionResult(
                status="MISSING_OPERAND",
                task_type="TABLE_COMPARE",
                operation=task_plan.operation or "MAX",
                operands=operands,
                intermediate_verification=interm_res.to_dict(),
                explanation=interm_res.explanation,
                diagnostics={"intermediate_verification": interm_res.to_dict()},
            )

        operation = (task_plan.operation or "MAX").upper()

        # Deterministic programmatic comparison
        if operation == "MIN":
            best_idx = min(range(len(operands)), key=lambda i: operands[i].value)  # type: ignore
        else:  # Default MAX
            best_idx = max(range(len(operands)), key=lambda i: operands[i].value)  # type: ignore

        best_op = operands[best_idx]
        candidates = task_plan.candidates
        if not candidates and task_plan.options:
            from app.schemas.task_plan_schema import TableCandidate
            candidates = [TableCandidate(label=k, target=v) for k, v in task_plan.options.items()]

        best_label = candidates[best_idx].label if best_idx < len(candidates) else "A"
        scope_str = f"在【{task_plan.scope}】口径下，" if task_plan.scope else ""

        explanation = (
            f"{scope_str}候选项数值比较如下：\n"
            + "\n".join(
                f"- {c.label}. {c.target}: {op.value} {op.unit}".strip()
                for c, op in zip(candidates, operands)
            )
            + f"\n经程序确定性比较，{'数值最高' if operation != 'MIN' else '数值最低'}的是 {best_label}. {best_op.name}（数值为 {best_op.value}）。"
        )

        return TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_COMPARE",
            operation=operation,
            operands=operands,
            result=best_op.value,
            unit=best_op.unit,
            matched_option=best_label,
            explanation=explanation,
            intermediate_verification=interm_res.to_dict(),
            diagnostics={
                "candidate_count": len(operands),
                "operation": operation,
                "winner": best_label,
                "intermediate_verification": interm_res.to_dict(),
            },
        )

    def execute_calculation(
        self,
        task_plan: TaskPlan,
        retrieval_response: Any,
    ) -> TableExecutionResult:
        """Execute TABLE_CALCULATION: arithmetic calculation across operands."""
        from app.retrieval.intermediate_verifier import intermediate_verifier

        interm_res, operands = intermediate_verifier.verify_table_calculation(
            task_plan, retrieval_response
        )
        if not interm_res.can_execute:
            return TableExecutionResult(
                status="MISSING_OPERAND",
                task_type="TABLE_CALCULATION",
                operation=task_plan.operation or "SUBTRACT",
                operands=operands,
                intermediate_verification=interm_res.to_dict(),
                explanation=interm_res.explanation,
                diagnostics={"intermediate_verification": interm_res.to_dict()},
            )

        operation = (task_plan.operation or "SUBTRACT").upper()
        values = [op.value for op in operands if op.value is not None]

        # Programmatic deterministic calculation
        try:
            if operation in {"SUBTRACT", "MINUS"}:
                if len(values) >= 2:
                    # In questions like "从合计到健康险的数值变化", change = 健康险 - 合计
                    # If operands were [合计, 健康险], expression is 健康险 - 合计 (values[1] - values[0])
                    if task_plan.expression and f"{operands[1].name} - {operands[0].name}" in task_plan.expression:
                        calc_val = values[1] - values[0]
                        calc_expr = f"{operands[1].name}({values[1]}) - {operands[0].name}({values[0]})"
                    else:
                        calc_val = values[1] - values[0] if len(values) == 2 else values[0] - values[1]
                        calc_expr = f"{operands[1].name}({values[1]}) - {operands[0].name}({values[0]})"
                else:
                    calc_val = values[0]
                    calc_expr = str(values[0])

            elif operation in {"ADD", "SUM"}:
                calc_val = sum(values)
                calc_expr = " + ".join(f"{op.name}({op.value})" for op in operands)

            elif operation in {"ABS_DIFFERENCE", "DIFF"}:
                calc_val = abs(values[0] - values[1]) if len(values) >= 2 else 0.0
                calc_expr = f"|{operands[0].name}({values[0]}) - {operands[1].name}({values[1]})|"

            elif operation == "RATIO":
                calc_val = values[0] / values[1] if len(values) >= 2 and values[1] != 0 else 0.0
                calc_expr = f"{operands[0].name}({values[0]}) / {operands[1].name}({values[1]})"

            elif operation == "CHANGE_RATE":
                calc_val = (values[1] - values[0]) / values[0] if len(values) >= 2 and values[0] != 0 else 0.0
                calc_expr = f"({operands[1].name}({values[1]}) - {operands[0].name}({values[0]})) / {operands[0].name}({values[0]})"

            elif operation == "AVERAGE":
                calc_val = sum(values) / len(values) if values else 0.0
                calc_expr = f"平均值({', '.join(str(v) for v in values)})"

            elif operation == "MAX":
                calc_val = max(values)
                calc_expr = f"max({', '.join(str(v) for v in values)})"

            elif operation == "MIN":
                calc_val = min(values)
                calc_expr = f"min({', '.join(str(v) for v in values)})"

            else:
                calc_val = values[0]
                calc_expr = str(values[0])

        except Exception as e:
            return TableExecutionResult(
                status="CALCULATION_ERROR",
                task_type="TABLE_CALCULATION",
                operation=operation,
                operands=operands,
                explanation=f"数学计算执行失败: {e}",
            )

        calc_val_rounded = round(calc_val, 4)
        # Match option
        matched_opt, _ = match_numeric_option(calc_val_rounded, task_plan.options)

        unit = operands[0].unit if operands else ""
        explanation = (
            f"根据表格取数，操作数数值为：\n"
            + "\n".join(f"- {op.name}: {op.value} {op.unit}" for op in operands)
            + f"\n执行运算【{operation}】: {calc_expr} = {calc_val_rounded} {unit}。"
        )
        if matched_opt:
            explanation += f"\n对应选项为 【{matched_opt}】。"

        return TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_CALCULATION",
            operation=operation,
            operands=operands,
            result=calc_val_rounded,
            unit=unit,
            matched_option=matched_opt,
            explanation=explanation,
            diagnostics={
                "expression": calc_expr,
                "raw_result": calc_val,
                "rounded_result": calc_val_rounded,
            },
        )


table_executor = TableExecutor()

__all__ = [
    "TableExecutor",
    "table_executor",
    "parse_table_chunk_kv",
    "extract_operand_value",
    "match_numeric_option",
]
