"""Shared behavior labels and metrics for QA evaluation scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_BEHAVIORS = {"answer", "refuse", "clarify"}
ANSWERED_STATUSES = {"answered", "success", "degraded"}
CLARIFY_STATUSES = {"needs_clarification", "clarify", "clarification"}
ERROR_STATUSES = {"error", "request_error", "http_error", "timeout"}
DEFAULT_LABEL_CORRECTIONS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "eval" / "qa_label_corrections.json"
)
CORRECTABLE_FIELDS = {
    "question",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "answer",
    "answer_text",
    "evidence",
    "expected_behavior",
}


def load_label_corrections(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the versioned QA correction overlay."""

    correction_path = path or DEFAULT_LABEL_CORRECTIONS_PATH
    if not correction_path.exists():
        return {"version": "", "corrections": {}, "path": str(correction_path)}

    payload = json.loads(correction_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("corrections"), dict):
        raise ValueError(f"QA 修正文件格式无效: {correction_path}")
    for question_id, correction in payload["corrections"].items():
        if not isinstance(correction, dict):
            raise ValueError(f"QA 修正项 {question_id} 必须是对象")
        unknown = set(correction) - CORRECTABLE_FIELDS - {"reason", "source_cells"}
        if unknown:
            raise ValueError(
                f"QA 修正项 {question_id} 包含未知字段: {', '.join(sorted(unknown))}"
            )
        if not str(correction.get("reason") or "").strip():
            raise ValueError(f"QA 修正项 {question_id} 缺少 reason")
    return {**payload, "path": str(correction_path)}


def apply_label_corrections(
    rows: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Apply corrections without mutating workbook-derived rows."""

    corrections = payload.get("corrections")
    if not isinstance(corrections, Mapping):
        raise ValueError("QA 修正数据缺少 corrections 对象")
    version = str(payload.get("version") or "")
    corrected_rows: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        question_id = str(row.get("id") or "").strip().upper()
        correction = corrections.get(question_id)
        row["label_correction_applied"] = False
        if not isinstance(correction, Mapping):
            corrected_rows.append(row)
            continue

        changed_fields: list[str] = []
        for field in CORRECTABLE_FIELDS:
            if field not in correction:
                continue
            row[f"original_{field}"] = row.get(field)
            row[field] = correction[field]
            changed_fields.append(field)
        row["label_correction_applied"] = True
        row["label_correction_version"] = version
        row["label_correction_reason"] = str(correction.get("reason") or "")
        row["label_correction_source_cells"] = list(correction.get("source_cells") or [])
        row["label_correction_fields"] = sorted(changed_fields)
        corrected_rows.append(row)
    return corrected_rows


def expected_behavior(row: Mapping[str, Any]) -> str:
    raw = next(
        (
            str(row.get(key) or "").strip().lower()
            for key in ("expected_behavior", "expected_action", "预期行为")
            if str(row.get(key) or "").strip()
        ),
        "answer",
    )
    aliases = {
        "回答": "answer",
        "应答": "answer",
        "拒答": "refuse",
        "拒绝": "refuse",
        "追问": "clarify",
        "澄清": "clarify",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in EXPECTED_BEHAVIORS else "answer"


def actual_behavior(status: Any) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in ANSWERED_STATUSES:
        return "answer"
    if normalized in CLARIFY_STATUSES:
        return "clarify"
    if normalized in ERROR_STATUSES:
        return "error"
    return "refuse"


def retrieval_coverage(response: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = response.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}
    multi_target = diagnostics.get("multi_target")
    if isinstance(multi_target, Mapping):
        target_diagnostics = multi_target.get("diagnostics")
    else:
        target_diagnostics = diagnostics
    if not isinstance(target_diagnostics, Mapping):
        target_diagnostics = {}

    task_count = int(target_diagnostics.get("task_count") or 0)
    covered = list(target_diagnostics.get("covered_task_ids") or [])
    missing = list(target_diagnostics.get("missing_task_ids") or [])
    covered_count = len(covered)
    if not covered and task_count:
        covered_count = int(target_diagnostics.get("success_count") or 0)
    coverage_rate = round(covered_count / task_count, 4) if task_count else None
    return {
        "task_count": task_count,
        "covered_task_count": covered_count,
        "covered_task_ids": covered,
        "missing_task_ids": missing,
        "coverage_rate": coverage_rate,
        "full_coverage": coverage_rate == 1.0 if coverage_rate is not None else None,
    }


def build_retrieval_metrics(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    coverages = [
        item.get("retrieval_coverage")
        for item in results
        if isinstance(item.get("retrieval_coverage"), Mapping)
        and item["retrieval_coverage"].get("coverage_rate") is not None
    ]
    if not coverages:
        return {
            "evaluated_count": 0,
            "average_target_coverage": None,
            "full_coverage_count": 0,
            "full_coverage_rate": None,
        }
    full_count = sum(bool(item.get("full_coverage")) for item in coverages)
    return {
        "evaluated_count": len(coverages),
        "average_target_coverage": round(
            sum(float(item["coverage_rate"]) for item in coverages) / len(coverages),
            4,
        ),
        "full_coverage_count": full_count,
        "full_coverage_rate": round(full_count / len(coverages), 4),
    }


def build_behavior_metrics(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(results)
    expected_counts = {label: 0 for label in EXPECTED_BEHAVIORS}
    actual_counts = {label: 0 for label in (*sorted(EXPECTED_BEHAVIORS), "error")}
    correct = 0
    for item in results:
        expected = str(item.get("expected_behavior") or "answer")
        actual = str(item.get("actual_behavior") or "error")
        expected_counts[expected] = expected_counts.get(expected, 0) + 1
        actual_counts[actual] = actual_counts.get(actual, 0) + 1
        correct += int(expected == actual)

    def division(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    expected_refuse = expected_counts.get("refuse", 0)
    actual_refuse = actual_counts.get("refuse", 0)
    true_refuse = sum(
        item.get("expected_behavior") == "refuse" and item.get("actual_behavior") == "refuse"
        for item in results
    )
    expected_clarify = expected_counts.get("clarify", 0)
    actual_clarify = actual_counts.get("clarify", 0)
    true_clarify = sum(
        item.get("expected_behavior") == "clarify" and item.get("actual_behavior") == "clarify"
        for item in results
    )
    expected_answer = expected_counts.get("answer", 0)
    false_refusals = sum(
        item.get("expected_behavior") == "answer" and item.get("actual_behavior") == "refuse"
        for item in results
    )

    return {
        "expected_counts": expected_counts,
        "actual_counts": actual_counts,
        "behavior_accuracy": division(correct, total),
        "false_refusal_count": false_refusals,
        "false_refusal_rate": division(false_refusals, expected_answer),
        "refusal_precision": division(true_refuse, actual_refuse),
        "refusal_recall": division(true_refuse, expected_refuse),
        "clarification_precision": division(true_clarify, actual_clarify),
        "clarification_recall": division(true_clarify, expected_clarify),
    }
