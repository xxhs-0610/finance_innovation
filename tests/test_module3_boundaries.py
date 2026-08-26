from __future__ import annotations

import unittest

from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.entity_filter import apply_entity_filters
from app.retrieval.query_classifier import classify_query
from app.retrieval.query_parser import parse_query
from app.schemas.chunk_schema import SearchResult, SourceInfo


class Module3BoundaryTest(unittest.TestCase):
    OUT_OF_DOMAIN_QUESTIONS = (
        "江西财经大学的校长是谁",
        "今天天气怎么样",
        "推荐一部金融题材电影",
        "招商银行客服电话是多少",
        "工商银行几点下班",
        "建设银行今年校园招聘多少人",
        "招商银行董事长是谁",
        "平安银行今天股价是多少",
        "哪所大学金融专业最好",
        "帮我写一段 Python 代码",
    )

    def test_out_of_domain_suite_is_rejected_before_retrieval(self) -> None:
        decisions = [classify_query(question) for question in self.OUT_OF_DOMAIN_QUESTIONS]
        refusal_rate = decisions.count("unsupported") / len(decisions)
        self.assertGreaterEqual(refusal_rate, 0.8)
        self.assertGreaterEqual(refusal_rate, 0.8)

    def test_regulatory_context_is_not_over_rejected(self) -> None:
        self.assertNotEqual(
            classify_query("商业银行董事长任职资格需要谁核准"),
            "unsupported",
        )
        self.assertNotEqual(
            classify_query("银行与大学合作是否有监管规定"),
            "unsupported",
        )

    def test_open_domain_university_question_is_unsupported(self) -> None:
        question = "江西财经大学的校长是谁"
        self.assertEqual(classify_query(question), "unsupported")
        analysis = parse_query(question)
        self.assertEqual(analysis.entities["subject_entity"], "江西财经大学")

    def test_unsupported_query_skips_all_retrievers(self) -> None:
        class FailingRetriever:
            name = "must-not-run"

            def search(self, analysis, top_k=20):
                raise AssertionError("unsupported questions must not retrieve")

        response = HybridRetriever([FailingRetriever()]).search(
            "江西财经大学的校长是谁"
        )
        self.assertEqual(response.status, "no_evidence")
        self.assertEqual(response.module4_guidance["reason"], "out_of_domain")
        self.assertFalse(response.module4_guidance["may_generate_answer"])

    def test_specific_bank_requires_exact_subject_evidence(self) -> None:
        analysis = parse_query("招商银行资本充足率是多少")
        wrong = SearchResult(
            "wrong-bank",
            "clause",
            1.0,
            "云南银行资本充足率保持稳定。",
            SourceInfo(
                doc_id="wrong-bank",
                title="云南银行年度报告",
                local_path="wrong.pdf",
                section_path=["资本管理"],
            ),
        )
        self.assertEqual(apply_entity_filters(analysis, [wrong]), [])

        correct = SearchResult(
            "right-bank",
            "clause",
            1.0,
            "招商银行资本充足率保持稳定。",
            SourceInfo(
                doc_id="right-bank",
                title="招商银行年度报告",
                local_path="right.pdf",
                section_path=["资本管理"],
            ),
        )
        filtered = apply_entity_filters(analysis, [correct])
        self.assertEqual([item.chunk_id for item in filtered], ["right-bank"])
        self.assertEqual(
            filtered[0].metadata["entity_filtering"]["checked_fields"]["subject_entity"],
            "招商银行",
        )

    def test_generic_commercial_bank_query_has_no_specific_subject(self) -> None:
        analysis = parse_query("2025年三季度商业银行资本充足率是多少？")
        self.assertNotIn("subject_entity", analysis.entities)

    def test_degraded_mode_requires_relevant_remaining_evidence(self) -> None:
        class FixedRetriever:
            name = "bm25"

            def search(self, analysis, top_k=20):
                return [
                    SearchResult(
                        "right-bank",
                        "clause",
                        1.0,
                        "招商银行资本充足率保持稳定。",
                        SourceInfo(
                            doc_id="right-bank",
                            title="招商银行年度报告",
                            local_path="right.pdf",
                            section_path=["资本管理"],
                        ),
                    )
                ]

        class BrokenRetriever:
            name = "vector"

            def search(self, analysis, top_k=20):
                raise FileNotFoundError("vector backend unavailable")

        response = HybridRetriever([FixedRetriever(), BrokenRetriever()]).search(
            "招商银行资本充足率是多少"
        )
        self.assertEqual(response.status, "degraded")
        self.assertTrue(response.module4_guidance["may_generate_answer"])

        class WrongRetriever(FixedRetriever):
            def search(self, analysis, top_k=20):
                result = super().search(analysis, top_k)[0]
                result.chunk_id = "wrong-bank"
                result.text = "云南银行资本充足率保持稳定。"
                result.source.title = "云南银行年度报告"
                return [result]

        refused = HybridRetriever([WrongRetriever(), BrokenRetriever()]).search(
            "招商银行资本充足率是多少"
        )
        self.assertEqual(refused.status, "no_evidence")
        self.assertFalse(refused.module4_guidance["may_generate_answer"])


if __name__ == "__main__":
    unittest.main()
