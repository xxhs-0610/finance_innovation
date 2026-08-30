from __future__ import annotations

import unittest

from scripts.qa_eval_common import (
    actual_behavior,
    build_behavior_metrics,
    build_retrieval_metrics,
    expected_behavior,
    retrieval_coverage,
)


class QAEvaluationBehaviorTest(unittest.TestCase):
    def test_behavior_labels_support_chinese_and_statuses(self) -> None:
        self.assertEqual(expected_behavior({"expected_behavior": "拒答"}), "refuse")
        self.assertEqual(expected_behavior({}), "answer")
        self.assertEqual(actual_behavior("needs_clarification"), "clarify")
        self.assertEqual(actual_behavior("request_error"), "error")

    def test_metrics_separate_false_refusals_from_errors(self) -> None:
        results = [
            {"expected_behavior": "answer", "actual_behavior": "answer"},
            {"expected_behavior": "answer", "actual_behavior": "refuse"},
            {"expected_behavior": "answer", "actual_behavior": "error"},
            {"expected_behavior": "refuse", "actual_behavior": "refuse"},
            {"expected_behavior": "clarify", "actual_behavior": "clarify"},
        ]

        metrics = build_behavior_metrics(results)

        self.assertEqual(metrics["false_refusal_count"], 1)
        self.assertEqual(metrics["false_refusal_rate"], 0.3333)
        self.assertEqual(metrics["refusal_precision"], 0.5)
        self.assertEqual(metrics["refusal_recall"], 1.0)
        self.assertEqual(metrics["clarification_precision"], 1.0)
        self.assertEqual(metrics["clarification_recall"], 1.0)

    def test_retrieval_metrics_report_target_coverage(self) -> None:
        response = {
            "diagnostics": {
                "multi_target": {
                    "diagnostics": {
                        "task_count": 4,
                        "covered_task_ids": ["CAND_A", "CAND_B", "CAND_C"],
                        "missing_task_ids": ["CAND_D"],
                    }
                }
            }
        }
        coverage = retrieval_coverage(response)
        metrics = build_retrieval_metrics([{"retrieval_coverage": coverage}])

        self.assertEqual(coverage["coverage_rate"], 0.75)
        self.assertFalse(coverage["full_coverage"])
        self.assertEqual(metrics["average_target_coverage"], 0.75)
        self.assertEqual(metrics["full_coverage_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
