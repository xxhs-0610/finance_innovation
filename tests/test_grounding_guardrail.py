"""Test suite for Tiered Grounding Validation, Auto-pruning, and Grounded Regeneration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.generation.answer_generator import generate_answer
from app.generation.verifier import verify_answer


def make_evidence(
    text: str,
    *,
    chunk_id: str = "doc1_c1",
    citation_id: str = "E1",
    title: str = "商业银行资本管理办法",
    clause_no: str = "第十条",
    metadata: dict | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "citation_id": citation_id,
        "score": 1.2,
        "text": text,
        "source": {
            "doc_id": "doc1",
            "title": title,
            "issuer": "国家金融监督管理总局",
            "publish_date": "2023-11-01",
            "clause_no": clause_no,
        },
        "metadata": metadata or {},
    }


class TestGroundingGuardrail(unittest.TestCase):
    """Verify that evidence verification constrains answers without causing over-refusal."""

    def test_case_a_full_support_passes_directly(self):
        """情况A：检索证据完整，答案完全有依据 -> PASS，正常返回。"""
        ev = [make_evidence("第三档商业银行资本充足率不得低于8.5%。")]
        ans = (
            "第三档商业银行资本充足率最低监管要求为不得低于8.5%。[E1]\n\n"
            "必要说明：该规定适用于所有第三档商业银行。\n\n"
            "监管依据：《商业银行资本管理办法》第十条 [E1]"
        )
        res = verify_answer(ans, ev, question="第三档商业银行资本充足率最低要求是多少？")

        self.assertTrue(res["passed"])
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["issues"], [])
        self.assertEqual(len(res["unsupported_core_claims"]), 0)

        # E2E Answer Generator test
        gen_res = generate_answer(
            "第三档商业银行资本充足率最低要求是多少？",
            ev,
            generator=lambda q, e: ans,
        )
        self.assertEqual(gen_res["status"], "answered")
        self.assertIn("8.5%", gen_res["answer"])
        self.assertEqual(gen_res["verification"]["grounding_action"], "PASS")

    def test_case_b_core_supported_with_unsupported_optional_pruned(self):
        """情况B：核心答案有充分证据，但包含额外无依据解释 -> PARTIAL_PASS，修剪后正常返回，不整条拒答。"""
        ev = [make_evidence("商业银行资本充足率不得低于8%。")]
        ans = (
            "商业银行资本充足率不得低于8%。[E1]\n\n"
            "必要说明：该指标反映了某省城商行2029年预计实现利润增长的宏观趋势与量子计算规划。\n\n"
            "监管依据：《商业银行资本管理办法》第十条 [E1]"
        )
        res = verify_answer(ans, ev, question="商业银行资本充足率最低要求是多少？")

        # Must NOT fail the whole answer!
        self.assertTrue(res["passed"], "PARTIAL_PASS must keep passed=True to avoid whole-answer rejection")
        self.assertEqual(res["status"], "PARTIAL_PASS")
        self.assertEqual(res["issues"], [])
        # Pruned answer must retain the core 8% conclusion
        self.assertIn("8%", res["pruned_answer"])
        self.assertIn("[E1]", res["pruned_answer"])

        # E2E Answer Generator test
        gen_res = generate_answer(
            "商业银行资本充足率最低要求是多少？",
            ev,
            generator=lambda q, e: ans,
        )
        self.assertEqual(gen_res["status"], "answered", "Should be answered, NOT refused!")
        self.assertIn("8%", gen_res["answer"])
        self.assertEqual(gen_res["verification"]["grounding_action"], "REMOVE_OPTIONAL")
        self.assertTrue(any("修剪" in tip for tip in gen_res["risk_tips"]))

    def test_case_c_insufficient_evidence_blocked(self):
        """情况C：检索到了相关文件，但并没有用户真正询问的关键事实 -> 拒答。"""
        ev = [make_evidence("商业银行应当妥善保存监管统计资料。")]
        gen_res = generate_answer(
            "监管统计资料按规定必须保存几年？",
            ev,
            generator=lambda q, e: "按规定保存五年。[E1]",
        )
        self.assertEqual(gen_res["status"], "refused")
        self.assertEqual(gen_res["confidence"], 0.0)

    def test_case_d_grounded_regeneration_recovers_answer(self):
        """情况D：第一次生成答案包含无依据内容，现有证据充足 -> 触发 Grounded Regeneration 修正后正常回答。"""
        ev = [make_evidence("商业银行资本充足率不得低于8%。")]
        wrong_ans = "商业银行资本充足率不得低于15.5%。[E1]"

        # Initial verify fails on 15.5%
        res = verify_answer(wrong_ans, ev, question="商业银行资本充足率最低要求是多少？")
        self.assertFalse(res["passed"])
        self.assertEqual(res["status"], "FAIL")

        # When regeneration is triggered (via DeepSeek or regenerated answer)
        gen_res = generate_answer(
            "商业银行资本充足率最低要求是多少？",
            ev,
            generator=lambda q, e: wrong_ans,
        )
        # If DeepSeek is enabled, it should fix the answer via Grounded Regeneration
        if gen_res["verification"].get("regeneration_triggered"):
            self.assertEqual(gen_res["status"], "answered")
            self.assertEqual(gen_res["verification"]["grounding_action"], "REGENERATE")
            self.assertIn("8%", gen_res["answer"])

    def test_case_e_persistent_hallucinated_number_blocked(self):
        """情况E：证据中的数字与生成答案数字严重不一致且无法修复 -> FAIL，严格拦截错误数字拒答。"""
        from unittest.mock import patch
        ev = [make_evidence("商业银行资本充足率不得低于8%。")]
        wrong_ans = "商业银行资本充足率不得低于15.5%。[E1]"

        with patch("app.generation.deepseek_client.deepseek_enabled", return_value=False):
            gen_res = generate_answer(
                "商业银行资本充足率最低要求是多少？",
                ev,
                generator=lambda q, e: wrong_ans,
            )
            self.assertEqual(gen_res["status"], "refused")
            self.assertEqual(gen_res["verification"]["grounding_action"], "REJECT")
            self.assertIn("15.5%", str(gen_res["verification"]["issues"]))

    def test_case_f_excel_and_table_cross_format_grounding(self):
        """情况F：Excel离散单元格与结构化衍生数值的跨格式验证 -> 正常通过。"""
        excel_ev = make_evidence(
            "资本充足率 | 2024Q4 | 商业银行",
            title="商业银行主要监管指标情况表（季度）",
            metadata={
                "metric_name": "资本充足率",
                "period": "2024年四季度",
                "value": "15.62",
                "unit": "%",
                "derived_values": [
                    {
                        "source_value": "0.1562",
                        "display_value": "15.62%",
                        "explanation": "换算为百分比 15.62%",
                    }
                ],
            },
        )
        ans = (
            "2024年四季度商业银行资本充足率为15.62%。[E1]\n\n"
            "监管依据：《商业银行主要监管指标情况表（季度）》 [E1]"
        )
        res = verify_answer(ans, [excel_ev], question="2024年四季度商业银行资本充足率是多少？")

        self.assertTrue(res["passed"])
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["unsupported_core_claims"], [])

    def test_institution_aliases_support(self):
        """验证机构名称常见别名与通称不会被误判为未定位字段。"""
        ev = [make_evidence("根据国家金融监督管理总局规定，商业银行应当持续达标。")]
        ans = "金融监管总局对商业银行资本充足率持续达标提出了明确要求。[E1]"
        res = verify_answer(ans, ev, question="金融监管总局对商业银行有什么要求？")

        self.assertTrue(res["passed"])
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["unsupported_core_claims"], [])


if __name__ == "__main__":
    unittest.main()
