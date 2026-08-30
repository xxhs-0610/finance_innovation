from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.generation.answer_generator import generate_answer
from app.generation.evidence_verifier import evidence_verifier
from app.schemas.verifier_schema import ALLOWED_REASON_CODES


def make_evidence(text: str, *, chunk_id: str = "doc1_clause_0001", doc_id: str = "doc1", title: str = "商业银行资本管理办法") -> dict:
    return {
        "chunk_id": chunk_id,
        "citation_id": "E1",
        "chunk_type": "clause",
        "score": 1.2,
        "text": text,
        "source": {
            "doc_id": doc_id,
            "title": title,
            "issuer": "国家金融监督管理总局",
            "publish_date": "2023-11-01",
            "clause_no": "第十条",
            "source_url": "https://example.com/doc1",
        },
        "metadata": {},
    }


class EvidenceVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = evidence_verifier

    def test_sufficient_evidence_passes(self) -> None:
        """RELEVANCE & SPECIFICITY: Evidence directly and specifically answers the question."""
        q = "第三档商业银行核心一级资本充足率最低要求是多少？"
        evidence = [
            make_evidence("第三档商业银行核心一级资本充足率不得低于7.5%，一级资本充足率不得低于8.5%。")
        ]
        res = self.verifier.verify(q, evidence)

        self.assertTrue(res.answerable)
        self.assertTrue(res.evidence_sufficient)
        self.assertFalse(res.need_clarification)
        self.assertEqual(res.reason_code, "SUFFICIENT")
        self.assertIn("E1", res.supporting_evidence_ids)
        self.assertEqual(res.missing_information, [])
        self.assertIn(res.reason_code, ALLOWED_REASON_CODES)

    def test_coverage_failure_for_multi_year_question(self) -> None:
        """COVERAGE: Question asks for 2024 and 2025, but evidence only has 2024 data."""
        q = "2024年和2025年商业银行资本充足率分别是多少？"
        evidence = [
            make_evidence("2024年商业银行资本充足率为15.60%。")
        ]
        res = self.verifier.verify(q, evidence)

        self.assertFalse(res.answerable)
        self.assertFalse(res.evidence_sufficient)
        self.assertEqual(res.reason_code, "INSUFFICIENT_COVERAGE")
        self.assertTrue(any("2025" in item for item in res.missing_information))
        self.assertIn(res.reason_code, ALLOWED_REASON_CODES)

    def test_option_values_are_not_treated_as_requested_years(self) -> None:
        q = (
            "根据《2023年08月人身险公司经营情况表》，原保险保费收入是多少？\n"
            "A. 27679.08\nB. 5362.28\nC. 21995.55\nD. 321.25"
        )
        evidence = [
            make_evidence(
                "2023年08月人身险公司经营情况表，原保险保费收入为27679.08亿元。",
                title="2023年08月人身险公司经营情况表",
            )
        ]

        res = self.verifier.verify(q, evidence, use_llm=False)

        self.assertTrue(res.answerable)
        self.assertEqual(res.reason_code, "SUFFICIENT")
        self.assertFalse(any("1995" in item for item in res.missing_information))

    def test_specificity_failure_for_vague_duration(self) -> None:
        """SPECIFICITY: Question asks '保存几年', but evidence only says '按规定期限保存'."""
        q = "银行业监管统计资料保存几年？"
        evidence = [
            make_evidence("银行业金融机构应当按照国家有关规定期限保存监管统计资料。")
        ]
        res = self.verifier.verify(q, evidence)

        self.assertFalse(res.answerable)
        self.assertFalse(res.evidence_sufficient)
        self.assertEqual(res.reason_code, "MISSING_NUMERIC_EVIDENCE")
        self.assertTrue(any(any(w in item for w in ("保存年限", "保存期限", "年限", "期限", "数值")) for item in res.missing_information))
        self.assertIn(res.reason_code, ALLOWED_REASON_CODES)

    def test_scenario_condition_ambiguity_requires_clarification(self) -> None:
        """CONSISTENCY & SCOPE: Bank tiers differ and query lacks tier specification."""
        q = "商业银行资本充足率最低监管要求是多少？"
        evidence = [
            make_evidence("第一档商业银行资本充足率不得低于8%，第二档为6.5%，第三档为7.5%。")
        ]
        res = self.verifier.verify(q, evidence)

        self.assertFalse(res.answerable)
        self.assertTrue(res.need_clarification)
        self.assertEqual(res.reason_code, "MISSING_SCENARIO_CONDITION")
        self.assertIn(res.reason_code, ALLOWED_REASON_CODES)

    def test_zero_evidence_fails_with_no_relevant_evidence(self) -> None:
        """AUTHORITY & RELEVANCE: Empty evidence returns NO_RELEVANT_EVIDENCE."""
        q = "商业银行资本充足率最低监管要求是多少？"
        res = self.verifier.verify(q, [])

        self.assertFalse(res.answerable)
        self.assertFalse(res.evidence_sufficient)
        self.assertEqual(res.reason_code, "NO_RELEVANT_EVIDENCE")
        self.assertIn(res.reason_code, ALLOWED_REASON_CODES)

    def test_end_to_end_generation_refusal_when_coverage_fails(self) -> None:
        """End-to-end integration: generator refuses without hallucinating missing years."""
        q = "2024年和2025年商业银行资本充足率分别是多少？"
        evidence = [
            make_evidence("2024年商业银行资本充足率为15.60%。")
        ]
        result = generate_answer(
            q,
            evidence,
            generator=lambda _q, _e: "2024年为15.6%，2025年预计为16.0%。[E1]",
        )

        self.assertEqual(result["status"], "refused")
        self.assertIn("evidence_verifier", result["verification"])
        self.assertEqual(result["verification"]["evidence_verifier"]["reason_code"], "INSUFFICIENT_COVERAGE")
        self.assertIn("当前检索证据仅覆盖了部分问题要求", result["answer"])
        self.assertIn("2025", result["answer"])

    def test_refusal_text_for_missing_numeric_evidence(self) -> None:
        """Verify distinct refusal text for MISSING_NUMERIC_EVIDENCE."""
        q = "银行业监管统计资料保存几年？"
        evidence = [
            make_evidence("银行业金融机构应当按照国家有关规定期限保存监管统计资料。")
        ]
        result = generate_answer(
            q,
            evidence,
            generator=lambda _q, _e: "应当保存5年。[E1]",
        )
        self.assertEqual(result["status"], "refused")
        self.assertIn("暂不提供确定数值", result["answer"])

    def test_refusal_text_for_no_relevant_evidence(self) -> None:
        """Verify distinct refusal text for NO_RELEVANT_EVIDENCE."""
        q = "商业银行资本充足率最低监管要求是多少？"
        result = generate_answer(q, [])
        self.assertEqual(result["status"], "refused")
        self.assertIn("未检索到能够支持可靠回答的相关依据", result["answer"])


if __name__ == "__main__":
    unittest.main()
