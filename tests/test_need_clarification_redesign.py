"""Unit tests for Redesigned NEED_CLARIFICATION (Prompt 7)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.router.question_router import question_router
from app.services.rag_service import RAGService
from app.schemas.task_plan_schema import TableOperand, TableSource, TaskPlan
from app.retrieval.table_executor import table_executor


class NeedClarificationRedesignTest(unittest.TestCase):
    """Rigorous verification of redesigned NEED_CLARIFICATION boundary conditions."""

    def setUp(self):
        self.router = question_router
        self.rag_service = RAGService()
        self.table_executor = table_executor

    # =========================================================================
    # Group 1: ALLOWED Clarification Triggers (3 Legitimate Conditions)
    # =========================================================================
    def test_allowed_incomplete_user_expression(self):
        """Condition 1: User expression itself is incomplete without referent."""
        cases = [
            "这个比例是多少？",
            "指标是多少？",
            "这个达到监管标准了吗？",
            "这项监管惩罚措施是什么？",
            "某机构这项指标超标了吗？",
            "这个指标的计算公式是什么？",
        ]
        for q in cases:
            decision = self.router.route(q)
            self.assertEqual(
                decision.intent,
                "NEED_CLARIFICATION",
                f"Query '{q}' should be classified as NEED_CLARIFICATION",
            )
            self.assertTrue(decision.need_clarification)

    def test_allowed_dangling_demonstratives(self):
        """Condition 2: Unresolved demonstrative pronouns missing context."""
        cases = [
            "它去年是多少？",
            "办理这个业务需要几天时间？",
            "满足这个要求需要多少资本？",
            "那个报表什么时候发布？",
            "申请这个许可证要满足什么条件？",
        ]
        for q in cases:
            decision = self.router.route(q)
            self.assertEqual(
                decision.intent,
                "NEED_CLARIFICATION",
                f"Query '{q}' should trigger NEED_CLARIFICATION",
            )

    def test_allowed_compliance_judgment_missing_user_business_facts(self):
        """Condition 3: Compliance judgment lacks mandatory business facts."""
        q = "某银行向单一客户发放贷款10亿元，合规吗？"
        ans = self.rag_service.ask(q)
        # Must require clarification for customer net capital
        self.assertEqual(ans["status"], "needs_clarification")
        self.assertIn("资本净额", ans["answer"])

    # =========================================================================
    # Group 2: FORBIDDEN Clarification Triggers (Must NEVER Trigger Clarification)
    # =========================================================================
    def test_forbidden_multi_comparison_objects(self):
        """Forbidden Case 1: Multiple comparison objects (A/B/C/D) is NOT ambiguity."""
        q = (
            "在截至当期-账面余额口径下，以下哪一项最高？\n"
            "A.年化综合收益率\n"
            "B.年化财务收益率\n"
            "C.资金运用余额\n"
            "D.银行存款"
        )
        decision = self.router.route(q)
        self.assertEqual(decision.intent, "DOMAIN_QA")
        self.assertEqual(decision.task_type, "TABLE_COMPARE")
        self.assertFalse(decision.need_clarification)

    def test_forbidden_multi_calculation_objects(self):
        """Forbidden Case 2: Multiple calculation objects is NOT ambiguity."""
        q = "“全国合计”从“合计”到“健康险”的数值变化约为多少？"
        decision = self.router.route(q)
        self.assertEqual(decision.intent, "DOMAIN_QA")
        self.assertEqual(decision.task_type, "TABLE_CALCULATION")
        self.assertFalse(decision.need_clarification)

    def test_forbidden_choice_options(self):
        """Forbidden Case 3: Multiple choice options is NOT ambiguity."""
        q = (
            "根据《消费金融公司管理办法》，下列哪项表述正确？\n"
            "A: 消费金融公司是经国家金融监督管理总局批准设立...\n"
            "B: 核心数据遭到泄露属于特别重大事件\n"
            "C: 重要数据泄露属于特别重大事件\n"
            "D: 重要数据泄露属于重大事件"
        )
        decision = self.router.route(q)
        self.assertEqual(decision.intent, "DOMAIN_QA")
        self.assertEqual(decision.task_type, "FACT_SINGLE_CHOICE")
        self.assertFalse(decision.need_clarification)

    def test_forbidden_multi_sub_claims_choice(self):
        """Forbidden Case 3b: Multi-choice paired sub-claims is NOT ambiguity."""
        q = (
            "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？\n"
            "A: 银行函证工作操作指引用于进一步明确...；消费贷款是消费金融公司贷款...\n"
            "C: 银行函证工作操作指引用于进一步明确...；会计师事务所在实施银行函证过程中..."
        )
        decision = self.router.route(q)
        self.assertEqual(decision.intent, "DOMAIN_QA")
        self.assertEqual(decision.task_type, "FACT_MULTI_CHOICE")
        self.assertFalse(decision.need_clarification)

    def test_forbidden_specified_query_with_failed_retrieval(self):
        """Forbidden Case 4: Clear query with no evidence in KB must return NO_EVIDENCE, NOT CLARIFICATION."""
        # Query specifies exact non-existent document/clause clearly
        q1 = "《商业银行资本管理办法》附件99关于量子计算资产的计量规定是什么？"
        ans1 = self.rag_service.ask(q1)
        self.assertEqual(ans1["status"], "no_evidence")
        self.assertNotEqual(ans1["status"], "needs_clarification")

        q2 = "2024年和2025年火星开发金融租赁公司的总资产分别是多少？"
        ans2 = self.rag_service.ask(q2)
        self.assertEqual(ans2["status"], "no_evidence")
        self.assertNotEqual(ans2["status"], "needs_clarification")

        q3 = "《消费金融公司管理办法》第九百九十九条规定了什么？"
        ans3 = self.rag_service.ask(q3)
        self.assertEqual(ans3["status"], "no_evidence")
        self.assertNotEqual(ans3["status"], "needs_clarification")

    def test_forbidden_table_missing_operand_returns_missing_operand_not_clarification(self):
        """Forbidden Case 4b: Table missing operand must return MISSING_OPERAND / no_evidence, never clarification."""
        plan = TaskPlan(
            task_type="TABLE_CALCULATION",
            source=TableSource(file_name="2023年4季度保险业资金运用情况表"),
            operation="SUBTRACT",
            expression="不存在的指标B - 不存在的指标A",
            operands=[
                TableOperand(name="不存在的指标A", row="不存在的行A", column="账面余额"),
                TableOperand(name="不存在的指标B", row="不存在的行B", column="账面余额"),
            ],
            need_clarification=False,
        )
        res = self.table_executor.execute(plan, [])
        self.assertEqual(res.status, "MISSING_OPERAND")

        ans = self.rag_service.ask("在《2023年4季度保险业资金运用情况表》中，不存在的指标A与不存在的指标B相差多少？")
        self.assertEqual(ans["status"], "no_evidence")
        self.assertEqual(ans.get("refusal_reason"), "MISSING_OPERAND")


if __name__ == "__main__":
    unittest.main()
