"""Boundary Test Set & Automated Evaluation Suite for RegTrust-RAG Question Router & Verifier.

Evaluates 115 boundary questions across 6 key categories:
- A类：明显领域内 (DOMAIN_QA)
- B类：明显领域外 (OUT_OF_SCOPE)
- C类：银行金融相关但实际领域外 (OUT_OF_SCOPE) - 极关键测试类
- D类：系统自身问题 (SYSTEM_META)
- E类：信息不足 (NEED_CLARIFICATION)
- F类：属于领域内但知识库无充分证据 (Router: DOMAIN_QA, Verifier: answerable=False)

Outputs:
- Router Accuracy
- Per-category Precision, Recall, F1
- Confusion Matrix (4x4 intent matrix & 6-group breakdown)
- Class F Verifier Rejection Analysis
- Misclassified Samples Report
"""

from __future__ import annotations

import io
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.router.question_router import question_router
from app.services.rag_service import rag_service

BENCHMARK_DATASET_FILE = PROJECT_ROOT / "data" / "eval" / "boundary_benchmark_115.json"
REPORT_OUTPUT_FILE = PROJECT_ROOT / "data" / "eval" / "boundary_benchmark_report.json"


def load_dataset() -> list[dict[str, Any]]:
    if not BENCHMARK_DATASET_FILE.exists():
        raise FileNotFoundError(f"Benchmark file not found: {BENCHMARK_DATASET_FILE}")
    with BENCHMARK_DATASET_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(include_verifier_check: bool = True) -> dict[str, Any]:
    items = load_dataset()
    print(f"================================================================================")
    print(f"🚀 开始执行【可信问答 Question Router 边界测试集与自动化评测】(样本总数: {len(items)})")
    print(f"================================================================================")

    # Intents to evaluate
    intents = ["DOMAIN_QA", "OUT_OF_SCOPE", "SYSTEM_META", "NEED_CLARIFICATION"]
    confusion_matrix: dict[str, dict[str, int]] = {
        exp: {pred: 0 for pred in intents} for exp in intents
    }

    # Group statistics
    group_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "name": "",
        "total": 0,
        "correct": 0,
        "wrong": 0,
        "samples": [],
    })

    # Overall metrics
    total_samples = len(items)
    correct_router_count = 0
    misclassified_samples: list[dict[str, Any]] = []
    class_f_results: list[dict[str, Any]] = []

    start_time = time.perf_counter()

    for idx, item in enumerate(items, 1):
        qid = item["id"]
        category = item["category"]
        category_name = item["category_name"]
        question = item["question"]
        expected_intent = item["expected_intent"]

        # Run Question Router
        decision = question_router.route(question)
        predicted_intent = decision.intent
        is_router_correct = (predicted_intent == expected_intent)

        # Update confusion matrix
        if expected_intent in confusion_matrix and predicted_intent in confusion_matrix[expected_intent]:
            confusion_matrix[expected_intent][predicted_intent] += 1

        # Update group stats
        group = group_stats[category]
        group["name"] = category_name
        group["total"] += 1
        if is_router_correct:
            group["correct"] += 1
            correct_router_count += 1
        else:
            group["wrong"] += 1
            mis_entry = {
                "id": qid,
                "category": category,
                "category_name": category_name,
                "question": question,
                "expected_intent": expected_intent,
                "predicted_intent": predicted_intent,
                "qa_type": decision.qa_type,
                "router_reason": decision.reason,
            }
            misclassified_samples.append(mis_entry)

        # Special Check for Class F: DOMAIN_QA + Verifier answerable=False
        if category == "F_DOMAIN_QA_INSUFFICIENT_EVIDENCE" and include_verifier_check:
            rag_res = rag_service.ask(question, top_k=3)
            status = rag_res.get("status")
            ver_info = rag_res.get("verification", {}).get("evidence_verifier", {})
            verifier_answerable = ver_info.get("answerable") if ver_info else (False if status != "answered" else True)
            reason_code = ver_info.get("reason_code") if ver_info else None
            
            is_verifier_rejected = (verifier_answerable is False or status in ("refused", "needs_clarification"))
            class_f_results.append({
                "id": qid,
                "question": question,
                "router_intent": predicted_intent,
                "router_correct": (predicted_intent == "DOMAIN_QA"),
                "verifier_answerable": verifier_answerable,
                "verifier_reason_code": reason_code,
                "status": status,
                "verifier_properly_blocked": is_verifier_rejected,
            })

    total_latency_ms = int((time.perf_counter() - start_time) * 1000)
    router_accuracy = correct_router_count / total_samples if total_samples > 0 else 0.0

    # Calculate per-intent Precision, Recall, F1
    intent_metrics: dict[str, dict[str, float]] = {}
    for intent in intents:
        tp = confusion_matrix[intent][intent]
        fn = sum(confusion_matrix[intent][pred] for pred in intents if pred != intent)
        fp = sum(confusion_matrix[exp][intent] for exp in intents if exp != intent)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        intent_metrics[intent] = {
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "Precision": round(precision, 4),
            "Recall": round(recall, 4),
            "F1_score": round(f1, 4),
        }

    # Calculate 6-Group specific Accuracy
    category_metrics: dict[str, dict[str, Any]] = {}
    for cat_key, stat in sorted(group_stats.items()):
        acc = stat["correct"] / stat["total"] if stat["total"] > 0 else 0.0
        category_metrics[cat_key] = {
            "name": stat["name"],
            "total": stat["total"],
            "correct": stat["correct"],
            "accuracy": round(acc, 4),
        }

    # Build final report dict
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_samples": total_samples,
        "total_latency_ms": total_latency_ms,
        "router_accuracy": round(router_accuracy, 4),
        "intent_metrics": intent_metrics,
        "category_metrics": category_metrics,
        "confusion_matrix": confusion_matrix,
        "class_f_analysis": {
            "total": len(class_f_results),
            "router_domain_qa_count": sum(1 for r in class_f_results if r["router_correct"]),
            "verifier_blocked_count": sum(1 for r in class_f_results if r["verifier_properly_blocked"]),
            "details": class_f_results,
        },
        "misclassified_samples": misclassified_samples,
    }

    # Save to JSON report
    REPORT_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print Formatted Evaluation Report
    _print_formatted_report(report)

    return report


def _print_formatted_report(report: dict[str, Any]) -> None:
    acc_pct = report["router_accuracy"] * 100
    print(f"\n" + "=" * 80)
    print(f"📊 【RegTrust-RAG Question Router 边界评测综合报告】")
    print(f"测试样本总数: {report['total_samples']} | 评测耗时: {report['total_latency_ms']}ms | 全局准确率: {acc_pct:.2f}%")
    print(f"=" * 80)

    # 1. Category Breakdown Table
    print("\n### 一、六大边界类别准确率分析 (Category Breakdown)")
    print("| 类别编号 | 类别名称 | 样本量 | 正确数 | 准确率 (Accuracy) |")
    print("| :--- | :--- | :---: | :---: | :---: |")
    for cat_key, m in report["category_metrics"].items():
        print(f"| `{cat_key}` | **{m['name']}** | {m['total']} | {m['correct']} | **{m['accuracy']*100:.1f}%** |")

    # 2. Intent Precision / Recall / F1 Table
    print("\n### 二、各意图 Precision / Recall / F1-Score")
    print("| 意图分类 (Intent) | TP | FP | FN | 精准率 (Precision) | 召回率 (Recall) | F1-Score |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for intent, m in report["intent_metrics"].items():
        print(f"| **{intent}** | {m['TP']} | {m['FP']} | {m['FN']} | {m['Precision']*100:.1f}% | {m['Recall']*100:.1f}% | **{m['F1_score']:.4f}** |")

    # 3. Confusion Matrix Table
    print("\n### 三、混淆矩阵 (Confusion Matrix)")
    cm = report["confusion_matrix"]
    intents = ["DOMAIN_QA", "OUT_OF_SCOPE", "SYSTEM_META", "NEED_CLARIFICATION"]
    header = "| 真实标签 (Expected) \\ 预测 (Predicted) | " + " | ".join(intents) + " |"
    print(header)
    print("| :--- | " + " | ".join([":---:"] * len(intents)) + " |")
    for exp in intents:
        row = [str(cm[exp][pred]) for pred in intents]
        print(f"| **{exp}** | " + " | ".join(row) + " |")

    # 4. Class F Special Verification Table
    f_analysis = report["class_f_analysis"]
    print(f"\n### 四、F类（领域内但证据不足）双重防御核验 (Class F Guard Analysis)")
    print(f"- **Router 识别为 DOMAIN_QA（未误拒答）率**: {f_analysis['router_domain_qa_count']}/{f_analysis['total']} ({f_analysis['router_domain_qa_count']/max(1, f_analysis['total'])*100:.1f}%)")
    print(f"- **Evidence Verifier 成功拦截（拒绝脑补）率**: {f_analysis['verifier_blocked_count']}/{f_analysis['total']} ({f_analysis['verifier_blocked_count']/max(1, f_analysis['total'])*100:.1f}%)")

    # 5. Misclassifications List
    mis = report["misclassified_samples"]
    print(f"\n### 五、主要误分类样本 (Misclassified Samples: {len(mis)}条)")
    if not mis:
        print("🎉 **太棒了！115 条边界测试用例全部分类正确，无任何误分类样本！**")
    else:
        for idx, m in enumerate(mis, 1):
            print(f"{idx}. [{m['id']}] 问题: {m['question']}")
            print(f"   - 类别: {m['category_name']}")
            print(f"   - 预期: {m['expected_intent']} | 实际预测: {m['predicted_intent']} (qa_type: {m['qa_type']})")
            print(f"   - 原因: {m['router_reason']}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    run_evaluation(include_verifier_check=True)
