"""Unit tests for Answer Composer (Prompt 9)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.generation.answer_composer import answer_composer
from app.retrieval.task_planner import task_planner
from app.schemas.option_verification_schema import (
    OptionVerificationItem,
    OptionVerificationResponse,
)
from app.schemas.table_execution_schema import TableExecutionResult, TableOperandResult
from app.schemas.task_plan_schema import (
    ChoiceOption,
    SourceConstraints,
    TableCandidate,
    TableOperand,
    TableSource,
    TableTarget,
    TaskPlan,
)
from app.services.rag_service import RAGService


class AnswerComposerTest(unittest.TestCase):
    """Test suite for Natural Language Answer Composer."""

    def setUp(self):
        self.composer = answer_composer
        self.rag_service = RAGService()

    def test_compose_table_compare_answer(self):
        """Test composition of TABLE_COMPARE answer matching Prompt 9 specification."""
        plan = TaskPlan(
            task_type="TABLE_COMPARE",
            source=TableSource(file_name="2023年4季度保险业资金运用情况表", sheet_name="资金运用表"),
            scope="截至当期-账面余额",
            candidates=[
                TableCandidate(label="A", target="年化综合收益率"),
                TableCandidate(label="B", target="年化财务收益率"),
                TableCandidate(label="C", target="资金运用余额"),
                TableCandidate(label="D", target="银行存款"),
            ],
            need_clarification=False,
        )
        exec_res = TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_COMPARE",
            operation="MAX",
            matched_option="C",
            result=281594.88,
            unit="亿元",
            operands=[
                TableOperandResult(name="年化综合收益率", value=3.22, unit="%", verified=True),
                TableOperandResult(name="年化财务收益率", value=2.81, unit="%", verified=True),
                TableOperandResult(name="资金运用余额", value=281594.88, unit="亿元", verified=True),
                TableOperandResult(name="银行存款", value=27154.34, unit="亿元", verified=True),
            ],
        )

        ans = self.composer.compose_table_compare_answer(exec_res, plan)
        self.assertIn("答案：**C. 资金运用余额**。", ans)
        self.assertIn("在“截至当期-账面余额”口径下", ans)
        self.assertIn("四个选项中【资金运用余额】数值最高", ans)
        self.assertIn("依据：《2023年4季度保险业资金运用情况表》", ans)

    def test_compose_table_calculation_answer(self):
        """Test composition of TABLE_CALCULATION answer matching Prompt 9 specification."""
        plan = TaskPlan(
            task_type="TABLE_CALCULATION",
            source=TableSource(file_name="2023年10月财产险情况表"),
            operation="SUBTRACT",
            expression="健康险 - 合计",
            operands=[
                TableOperand(name="合计", row="全国合计", column="合计"),
                TableOperand(name="健康险", row="全国合计", column="健康险"),
            ],
            options={"A": "1000", "B": "-25310.62", "C": "25310.62"},
            need_clarification=False,
        )
        exec_res = TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_CALCULATION",
            operation="SUBTRACT",
            matched_option="B",
            result=-25310.62,
            unit="亿元",
            operands=[
                TableOperandResult(name="合计", value=31739.18, unit="亿元", verified=True),
                TableOperandResult(name="健康险", value=6428.56, unit="亿元", verified=True),
            ],
        )

        ans = self.composer.compose_table_calculation_answer(exec_res, plan)
        self.assertIn("答案：**B. -25310.62 亿元**。", ans)
        self.assertIn("计算：", ans)
        self.assertIn("健康险 6428.56 - 合计 31739.18 = -25310.62 亿元", ans)
        self.assertIn("依据：《2023年10月财产险情况表》", ans)

    def test_compose_fact_single_choice_answer(self):
        """Test composition of FACT_SINGLE_CHOICE answer matching Prompt 9 specification."""
        plan = TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            source_constraints=SourceConstraints(document_name="消费金融公司管理办法"),
            choice_mode="SINGLE",
            need_clarification=False,
        )
        verify_resp = OptionVerificationResponse(
            status="SUCCESS",
            choice_mode="SINGLE",
            question_intent_target="CORRECT",
            selected_options=["A"],
            explanation=(
                "题目要求找出【正确】的表述，逐项验证结论如下：\n"
                "- **选项 A** [✅ 正确/有依据支持]（依据: nfra_att_396_clause_0003）：与条款原文高度吻合。\n"
                "- **选项 B** [⚠️ 证据不足/非该文件规定]：在知识库中未检索到支持证据。\n"
                "- **选项 C** [⚠️ 证据不足/非该文件规定]：在知识库中未检索到支持证据。\n"
                "- **选项 D** [⚠️ 证据不足/非该文件规定]：在知识库中未检索到支持证据。"
            ),
        )

        ans = self.composer.compose_fact_choice_answer(verify_resp, plan)
        self.assertIn("答案：**A**。", ans)
        self.assertIn("选项 A** [✅ 正确/有依据支持]", ans)
        self.assertIn("依据：《消费金融公司管理办法》", ans)

    def test_rag_service_table_compare_composed(self):
        """End-to-end RAGService test verifying composed answer on table compare question."""
        q = (
            "在《2023年4季度保险业资金运用情况表》中，在“截至当期-账面余额”口径下，以下哪项最高？\n"
            "A.年化综合收益率\n"
            "B.年化财务收益率\n"
            "C.资金运用余额\n"
            "D.银行存款"
        )
        res = self.rag_service.ask(q)
        self.assertEqual(res["status"], "answered")
        self.assertIn("答案：**C. 资金运用余额**", res["answer"])
        self.assertIn("数值最高", res["answer"])
        self.assertIn("依据", res["answer"])

    def test_rag_service_table_calculation_composed(self):
        """End-to-end RAGService test verifying composed answer on table calculation question."""
        q = "根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？A: 42212.17 B: -42212.17 C: -46433.39 D: -37990.95"
        res = self.rag_service.ask(q)
        self.assertEqual(res["status"], "answered")
        self.assertIn("答案：**B. -42212.17", res["answer"])
        self.assertIn("计算：", res["answer"])
        self.assertIn("依据", res["answer"])


if __name__ == "__main__":
    unittest.main()
