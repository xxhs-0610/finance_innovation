"""Unit tests for Intermediate Evidence Verification (Prompt 8)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.intermediate_verifier import intermediate_verifier
from app.retrieval.task_planner import task_planner
from app.retrieval.table_executor import table_executor
from app.services.rag_service import RAGService
from app.schemas.task_plan_schema import TableCandidate, TableOperand, TableSource, TaskPlan


class IntermediateVerifierTest(unittest.TestCase):
    """Test suite for Intermediate Evidence Verification across complex multi-target tasks."""

    def setUp(self):
        self.verifier = intermediate_verifier
        self.planner = task_planner
        self.table_executor = table_executor
        self.rag_service = RAGService()

    def test_output_schema_structure(self):
        """Verify that IntermediateVerificationResult complies exactly with Prompt 8 format."""
        plan = TaskPlan(
            task_type="TABLE_COMPARE",
            source=TableSource(file_name="2023年4季度保险业资金运用情况表"),
            scope="账面余额",
            candidates=[
                TableCandidate(label="A", target="年化综合收益率"),
                TableCandidate(label="B", target="银行存款"),
            ],
            need_clarification=False,
        )
        res = self.verifier.verify(plan, [])
        d = res.to_dict()

        # Assert mandatory Prompt 8 fields
        self.assertIn("task_complete", d)
        self.assertIn("missing_targets", d)
        self.assertIn("conflicting_targets", d)
        self.assertIn("verified_targets", d)
        self.assertIn("can_execute", d)
        self.assertIsInstance(d["task_complete"], bool)
        self.assertIsInstance(d["can_execute"], bool)
        self.assertIsInstance(d["missing_targets"], list)
        self.assertIsInstance(d["conflicting_targets"], list)
        self.assertIsInstance(d["verified_targets"], list)

    def test_table_compare_all_candidates_verified(self):
        """Test TABLE_COMPARE where all candidate values A, B, C, D are verified."""
        mock_evidence = [
            {"text": "【2023年4季度保险资金运用情况表】\n行=年化综合收益率\n账面余额 = 3.22\n单位: %", "chunk_id": "C1"},
            {"text": "【2023年4季度保险资金运用情况表】\n行=年化财务收益率\n账面余额 = 2.81\n单位: %", "chunk_id": "C2"},
            {"text": "【2023年4季度保险资金运用情况表】\n行=资金运用余额\n账面余额 = 281594.88\n单位: 亿元", "chunk_id": "C3"},
            {"text": "【2023年4季度保险资金运用情况表】\n行=银行存款\n账面余额 = 27154.34\n单位: 亿元", "chunk_id": "C4"},
        ]
        plan = TaskPlan(
            task_type="TABLE_COMPARE",
            source=TableSource(file_name="2023年4季度保险业资金运用情况表"),
            scope="账面余额",
            candidates=[
                TableCandidate(label="A", target="年化综合收益率"),
                TableCandidate(label="B", target="年化财务收益率"),
                TableCandidate(label="C", target="资金运用余额"),
                TableCandidate(label="D", target="银行存款"),
            ],
            need_clarification=False,
        )

        res, operands = self.verifier.verify_table_compare(plan, mock_evidence)
        self.assertTrue(res.task_complete)
        self.assertTrue(res.can_execute)
        self.assertEqual(len(res.verified_targets), 4)
        self.assertEqual(res.missing_targets, [])
        self.assertEqual(len(operands), 4)
        self.assertTrue(all(op.verified for op in operands))

        exec_res = self.table_executor.execute(plan, mock_evidence)
        self.assertEqual(exec_res.status, "SUCCESS")
        self.assertEqual(exec_res.matched_option, "C")
        self.assertIsNotNone(exec_res.intermediate_verification)
        self.assertTrue(exec_res.intermediate_verification["task_complete"])

    def test_table_compare_candidate_d_missing(self):
        """Test TABLE_COMPARE where Candidate D is missing -> returns MISSING_OPERAND, not clarification."""
        # Evidence only contains A, B, C; D is missing
        mock_evidence = [
            {"text": "【2023年4季度保险资金运用情况表】\n行=年化综合收益率\n账面余额 = 3.22\n单位: %", "chunk_id": "C1"},
            {"text": "【2023年4季度保险资金运用情况表】\n行=年化财务收益率\n账面余额 = 2.81\n单位: %", "chunk_id": "C2"},
            {"text": "【2023年4季度保险资金运用情况表】\n行=资金运用余额\n账面余额 = 281594.88\n单位: 亿元", "chunk_id": "C3"},
        ]
        plan = TaskPlan(
            task_type="TABLE_COMPARE",
            source=TableSource(file_name="2023年4季度保险业资金运用情况表"),
            scope="账面余额",
            candidates=[
                TableCandidate(label="A", target="年化综合收益率"),
                TableCandidate(label="B", target="年化财务收益率"),
                TableCandidate(label="C", target="资金运用余额"),
                TableCandidate(label="D", target="银行存款"),
            ],
            need_clarification=False,
        )

        res, operands = self.verifier.verify_table_compare(plan, mock_evidence)
        self.assertFalse(res.task_complete)
        self.assertFalse(res.can_execute)
        self.assertIn("D", res.missing_targets)
        self.assertEqual(res.error_code, "MISSING_OPERAND")
        self.assertIn("D", res.explanation)

        exec_res = self.table_executor.execute(plan, mock_evidence)
        self.assertEqual(exec_res.status, "MISSING_OPERAND")
        self.assertIn("D", exec_res.explanation)
        self.assertFalse(exec_res.intermediate_verification["can_execute"])

    def test_table_calculation_intermediate_verification(self):
        """Test TABLE_CALCULATION operand intermediate verification."""
        # Case 1: Both operands verified
        mock_evidence_complete = [
            {"text": "【2023年10月财产险情况表】\n行=全国合计\n本年累计 / 合计 = 31739.18 亿元", "chunk_id": "C1"},
            {"text": "【2023年10月财产险情况表】\n行=全国合计\n本年累计 / 健康险 = 6428.56 亿元", "chunk_id": "C2"},
        ]
        plan_complete = TaskPlan(
            task_type="TABLE_CALCULATION",
            source=TableSource(file_name="2023年10月财产险情况表"),
            operation="SUBTRACT",
            expression="健康险 - 合计",
            operands=[
                TableOperand(name="合计", row="全国合计", column="合计"),
                TableOperand(name="健康险", row="全国合计", column="健康险"),
            ],
            need_clarification=False,
        )
        res1, _ = self.verifier.verify_table_calculation(plan_complete, mock_evidence_complete)
        self.assertTrue(res1.task_complete)
        self.assertTrue(res1.can_execute)
        self.assertEqual(res1.verified_targets, ["合计", "健康险"])
        self.assertEqual(res1.missing_targets, [])

        # Case 2: One operand missing
        mock_evidence_incomplete = [
            {"text": "【2023年10月财产险情况表】\n行=全国合计\n本年累计 / 合计 = 31739.18 亿元", "chunk_id": "C1"},
        ]
        res2, _ = self.verifier.verify_table_calculation(plan_complete, mock_evidence_incomplete)
        self.assertFalse(res2.task_complete)
        self.assertFalse(res2.can_execute)
        self.assertIn("健康险", res2.missing_targets)
        self.assertEqual(res2.error_code, "MISSING_OPERAND")

    def test_fact_choice_intermediate_verification(self):
        """Test FACT_SINGLE_CHOICE intermediate verification structure."""
        q = "根据《消费金融公司管理办法》，下列哪项表述正确？ A: 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。 B: 核心数据遭到泄露属于特别重大事件"
        plan = self.planner.plan(q)
        from app.retrieval.multi_target_retriever import multi_target_retriever
        mt_res = multi_target_retriever.retrieve(q, plan)

        res = self.verifier.verify_choice_options(plan, mt_res)
        d = res.to_dict()
        self.assertTrue(d["task_complete"])
        self.assertTrue(d["can_execute"])
        self.assertIn("A", d["verified_targets"])
        self.assertIn("B", d["missing_targets"])


if __name__ == "__main__":
    unittest.main()
