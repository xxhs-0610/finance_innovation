"""Test Suite for COMPLIANCE_JUDGMENT dedicated workflow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.compliance.compliance_calculator import compliance_calculator
from app.compliance.compliance_engine import compliance_engine
from app.compliance.fact_extractor import scenario_fact_extractor
from app.generation.answer_generator import generate_answer
from app.services.rag_service import rag_service


def make_mock_evidence(text: str, doc_title: str = "商业银行大额风险暴露管理办法", clause_no: str = "第十五条") -> dict:
    return {
        "chunk_id": "chunk_compliance_001",
        "chunk_type": "clause",
        "score": 1.5,
        "text": text,
        "citation_id": "E1",
        "source": {
            "doc_id": "DOC-COMPLIANCE-01",
            "title": doc_title,
            "issuer": "国家金融监督管理总局",
            "publish_date": "2023-11-01",
            "clause_no": clause_no,
        },
        "metadata": {},
    }


class ComplianceJudgmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = [
            make_mock_evidence(
                "商业银行对非同业单一客户的贷款余额不得超过一级资本净额的10%。对单一集团客户授信总额不得超过资本净额的15%。"
            )
        ]

    def test_missing_net_capital_triggers_clarification(self) -> None:
        """Requirement: 监管规定与资本净额有关，但用户没有提供资本净额 -> 不能猜 -> 触发 NEED_CLARIFICATION"""
        q = "某商业银行拟向单一企业客户A发放贷款5000万元，是否合规？"
        res = generate_answer(q, self.evidence)

        self.assertEqual(res["status"], "needs_clarification")
        self.assertIn("资本净额", res["answer"])
        self.assertTrue("请补充" in res["answer"] or "请提供" in res["answer"])
        self.assertEqual(res["confidence"], 0.0)

    def test_compliant_loan_concentration_with_deterministic_calculation(self) -> None:
        """Loan 5000万, Capital 10亿 -> 5% <= 10% -> Compliant with 5 sections"""
        q = "某商业银行资本净额为10亿元，拟向单一企业客户A发放贷款5000万元，是否合规？"
        res = generate_answer(q, self.evidence)

        self.assertEqual(res["status"], "answered")
        ans = res["answer"]

        # Check all 5 required sections
        self.assertIn("【判断结论】", ans)
        self.assertIn("【监管规则】", ans)
        self.assertIn("【场景事实】", ans)
        self.assertIn("【对比过程】", ans)
        self.assertIn("【依据】", ans)

        # Check deterministic calculation details
        self.assertIn("5.00%", ans)
        self.assertIn("10.00%", ans)
        self.assertIn("合规", ans)
        self.assertIn("[E1]", ans)

    def test_non_compliant_loan_concentration_exceeding_threshold(self) -> None:
        """Loan 1.5亿, Capital 10亿 -> 15% > 10% -> Non-compliant (违规/超标)"""
        q = "某商业银行资本净额为10亿元，拟向单一企业客户B发放贷款1.5亿元，是否合规？"
        res = generate_answer(q, self.evidence)

        self.assertEqual(res["status"], "answered")
        ans = res["answer"]

        self.assertIn("【判断结论】", ans)
        self.assertTrue("违规" in ans or "超限额" in ans)
        self.assertIn("15.00%", ans)
        self.assertIn("10.00%", ans)
        self.assertIn("[E1]", ans)

    def test_related_party_credit_loan_prohibition(self) -> None:
        """Credit loan to bank director is strictly prohibited by Article 40 of Commercial Bank Law."""
        q = "某商业银行向本行董事李某发放500万元信用贷款，是否合规？"
        evidence = [
            make_mock_evidence(
                "商业银行不得向关系人发放信用贷款。向关系人发放担保贷款的条件不得优于其他借款人同类贷款的条件。",
                doc_title="中华人民共和国商业银行法",
                clause_no="第四十条",
            )
        ]
        res = generate_answer(q, evidence)

        self.assertEqual(res["status"], "answered")
        ans = res["answer"]

        self.assertIn("【判断结论】", ans)
        self.assertTrue("违规" in ans or "禁止" in ans)
        self.assertIn("第四十条", ans)
        self.assertIn("信用贷款", ans)

    def test_capital_adequacy_compliance_ratio_check(self) -> None:
        """Capital adequacy ratio below threshold -> Non-compliant"""
        q = "第一档商业银行，核心一级资本充足率为4.8%，是否合规？"
        evidence = [
            make_mock_evidence(
                "第一档商业银行核心一级资本充足率不得低于5%，一级资本充足率不得低于6%，资本充足率不得低于8%。",
                doc_title="商业银行资本管理办法",
                clause_no="第二十三条",
            )
        ]
        res = generate_answer(q, evidence)

        self.assertEqual(res["status"], "answered")
        ans = res["answer"]

        self.assertIn("【判断结论】", ans)
        self.assertTrue("不达标" in ans or "不合规" in ans)
        self.assertIn("4.80%", ans)
        self.assertIn("5.00%", ans)

    def test_end_to_end_rag_service_compliance_routing(self) -> None:
        """Verify end-to-end integration via rag_service.ask()."""
        q = "某商业银行拟向单一企业客户A发放贷款5000万元，是否合规？"
        with patch.object(rag_service, "retrieve", return_value=type("MockResp", (), {
            "evidence": self.evidence,
            "status": "answerable",
            "module4_guidance": {"action": "generate", "may_generate_answer": True},
            "diagnostics": {},
            "analysis": type("MockAnalysis", (), {"rule_type": "合规判断", "to_analyzer_dict": lambda *args, **kwargs: {}})(),
        })()):
            res = rag_service.ask(q)
            self.assertEqual(res["status"], "needs_clarification")
            self.assertIn("资本净额", res["answer"])


if __name__ == "__main__":
    unittest.main()
