from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.evaluate_qa_http import evaluate, load_failed_ids, predicted, select_rows


def make_row(number: int) -> dict[str, str]:
    return {
        "id": f"Q{number:03d}",
        "question": f"第 {number} 题",
        "option_a": "正确",
        "option_b": "错误",
        "answer": "A",
    }


class QAHttpSelectionTest(unittest.TestCase):
    def test_selects_ids_ranges_and_previous_failures(self) -> None:
        rows = [make_row(number) for number in range(1, 21)]

        selected = select_rows(
            rows,
            ids="Q003, 7",
            ranges=["Q010-Q012"],
            failed_ids={"Q015"},
        )

        self.assertEqual(
            [row["id"] for row in selected],
            ["Q003", "Q007", "Q010", "Q011", "Q012", "Q015"],
        )

    def test_loads_only_problem_ids_from_previous_jsonl(self) -> None:
        records = [
            {"id": "Q001", "accurate": True, "refused": False},
            {"id": "Q002", "accurate": False, "refused": False},
            {"id": "Q003", "accurate": False, "refused": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa_results.jsonl"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            self.assertEqual(load_failed_ids(path), {"Q002", "Q003"})

    def test_empty_failed_selection_does_not_fall_back_to_all_rows(self) -> None:
        selected = select_rows(
            [make_row(1), make_row(2)],
            failed_ids=set(),
            selection_requested=True,
        )

        self.assertEqual(selected, [])


class QAHttpConcurrencyTest(unittest.TestCase):
    def test_parallel_evaluation_preserves_input_order(self) -> None:
        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def fake_post_json(url, payload, timeout):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {"status": "answered", "answer": "A"}

        rows = [make_row(number) for number in range(1, 5)]
        with patch("scripts.evaluate_qa_http.post_json", side_effect=fake_post_json):
            results = evaluate(rows, "http://example.invalid", None, 1, workers=3)

        self.assertGreaterEqual(maximum_active, 2)
        self.assertEqual([result["id"] for result in results], ["Q001", "Q002", "Q003", "Q004"])
        self.assertTrue(all(result["accurate"] for result in results))


class QAHttpAnswerParsingTest(unittest.TestCase):
    def test_visible_answer_takes_precedence_over_conflicting_metadata(self) -> None:
        response = {
            "answer": "B [E1]",
            "verification": {"option_verification": {"selected_options": ["C"]}},
        }

        self.assertEqual(predicted(response), ["B"])

    def test_parses_markdown_answer_prefix(self) -> None:
        self.assertEqual(predicted({"answer": "答案：**A. 123.45 亿元**"}), ["A"])


if __name__ == "__main__":
    unittest.main()
