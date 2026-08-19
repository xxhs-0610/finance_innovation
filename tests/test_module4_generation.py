from __future__ import annotations

import unittest

from app.generation.answer_generator import generate_answer
from app.generation.prompt_builder import build_generation_prompt
from app.generation.verifier import extract_numeric_claims, verify_answer


def clause_evidence(text: str, *, chunk_id: str = "doc1_clause_0001") -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_type": "clause",
        "score": 1.2,
        "text": text,
        "source": {
            "doc_id": "doc1",
            "title": "商业银行资本管理办法",
            "issuer": "国家金融监督管理总局",
            "publish_date": "2023-11-01",
            "clause_no": "第十条",
            "source_url": "https://example.com/doc1",
        },
        "metadata": {},
    }


class Module4GenerationTest(unittest.TestCase):
    def test_default_generator_returns_cited_verified_answer(self) -> None:
        evidence = [
            clause_evidence(
                "商业银行核心一级资本充足率不得低于5%，一级资本充足率不得低于6%，"
                "资本充足率不得低于8%。"
            )
        ]
        result = generate_answer("资本充足率最低要求是多少？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertIn("[E1]", result["answer"])
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(result["citations"], ["E1"])
        self.assertGreater(result["confidence"], 0)

    def test_empty_or_unrelated_evidence_triggers_refusal(self) -> None:
        empty_result = generate_answer("资本充足率是多少？", [])
        unrelated_result = generate_answer(
            "资本充足率是多少？",
            [clause_evidence("银行业金融机构应当建立数据质量检查机制。")],
        )

        self.assertEqual(empty_result["status"], "refused")
        self.assertEqual(unrelated_result["status"], "refused")
        self.assertEqual(empty_result["confidence"], 0.0)

    def test_hallucinated_number_is_blocked(self) -> None:
        evidence = [clause_evidence("商业银行资本充足率不得低于8%。")]

        result = generate_answer(
            "资本充足率最低要求是多少？",
            evidence,
            generator=lambda _question, _evidence: "资本充足率不得低于10%。[E1]",
        )

        self.assertEqual(result["status"], "refused")
        self.assertFalse(result["verification"]["passed"])
        self.assertEqual(result["verification"]["unsupported_claims"][0]["raw"], "10%")

    def test_generator_failure_is_converted_to_safe_refusal(self) -> None:
        evidence = [clause_evidence("商业银行资本充足率不得低于8%。")]

        def broken_generator(_question, _evidence):
            raise RuntimeError("provider unavailable")

        result = generate_answer(
            "资本充足率最低要求是多少？",
            evidence,
            generator=broken_generator,
        )

        self.assertEqual(result["status"], "refused")
        self.assertIn("答案生成服务调用失败", result["refusal_reason"])

    def test_metadata_question_uses_traceable_source_fields(self) -> None:
        evidence = [clause_evidence("商业银行应当建立资本管理制度。")]

        result = generate_answer("这份文件由谁发布，发布日期是什么？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertIn("国家金融监督管理总局", result["answer"])
        self.assertIn("2023-11-01", result["answer"])
        self.assertTrue(result["verification"]["passed"])

    def test_multiple_evidence_list_markers_are_not_numeric_claims(self) -> None:
        evidence = [
            clause_evidence("商业银行应当建立资本管理制度。", chunk_id="c1"),
            clause_evidence("商业银行应当持续监测资本充足率。", chunk_id="c2"),
        ]

        result = generate_answer("商业银行如何管理资本充足率？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertNotIn("1", extract_numeric_claims(result["answer"]))
        self.assertNotIn("2", extract_numeric_claims(result["answer"]))

    def test_document_number_and_institution_are_verified(self) -> None:
        evidence = [
            clause_evidence(
                "根据银保监规〔2023〕1号，中国人民银行与有关监管部门按职责开展工作。"
            )
        ]
        passed = verify_answer(
            "中国人民银行依据银保监规〔2023〕1号开展相关工作。[E1]",
            evidence,
        )
        failed = verify_answer("工商银行负责批准该事项。[E1]", evidence)

        self.assertTrue(passed["passed"])
        self.assertEqual(passed["document_no_claims"][0]["raw"], "银保监规〔2023〕1号")
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["unsupported_claims"][0]["kind"], "institution")

    def test_prompt_contains_numbered_sources_and_output_contract(self) -> None:
        prompt = build_generation_prompt(
            "资本充足率最低要求是多少？",
            [clause_evidence("商业银行资本充足率不得低于8%。")],
        )

        self.assertIn("[E1]", prompt)
        self.assertIn("只能使用给定证据回答", prompt)
        self.assertIn('"status":"answered|refused"', prompt)


if __name__ == "__main__":
    unittest.main()
