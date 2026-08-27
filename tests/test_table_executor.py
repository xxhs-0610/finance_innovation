"""Unit tests for Table Executor (Prompt 5)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.table_executor import (
    TableExecutor,
    extract_operand_value,
    match_numeric_option,
    parse_table_chunk_kv,
    table_executor,
)
from app.retrieval.task_planner import task_planner
from app.retrieval.multi_target_retriever import multi_target_retriever
from app.services.rag_service import RAGService
from app.schemas.chunk_schema import SearchResult, SourceInfo
from app.schemas.task_plan_schema import TableOperand, TaskPlan


class TableExecutorTest(unittest.TestCase):
    """Test suite verifying deterministic table lookup, comparison, and arithmetic calculation."""

    def setUp(self):
        self.executor = table_executor
        self.planner = task_planner
        self.retriever = multi_target_retriever
        self.rag_service = RAGService()

    def test_parse_table_chunk_kv(self):
        """Test key-value pair and unit parsing from table text."""
        text = "2023年四季度保险业资金运用情况表 | 2023年4季度保险资金运用情况表 | 资金运用余额 | 项目=资金运用余额；截至当期 / 账面余额=281573.609414449；截至当期 / 规模占比=1 | 期间：2023Q4 | 单位：亿元"
        kv, unit = parse_table_chunk_kv(text)
        self.assertEqual(unit, "亿元")
        self.assertEqual(kv["截至当期 / 账面余额"], 281573.609414449)
        self.assertEqual(kv["截至当期 / 规模占比"], 1.0)

    def test_match_numeric_option(self):
        """Test matching calculated numeric value to A/B/C/D choices."""
        options = {
            "A": "42212.17",
            "B": "-42212.17",
            "C": "-46433.39",
            "D": "-37990.95",
        }
        best_opt, diff = match_numeric_option(-42212.17, options)
        self.assertEqual(best_opt, "B")
        self.assertAlmostEqual(diff, 0.0)

    def test_table_compare_execution(self):
        """Test TABLE_COMPARE execution produces programmatic MAX and matches option C."""
        q = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？A: 年化综合收益率 B: 年化财务收益率 C: 资金运用余额 D: 银行存款"
        plan = self.planner.plan(q)
        mt_res = self.retriever.retrieve(q, plan)

        exec_res = self.executor.execute(plan, mt_res)
        self.assertEqual(exec_res.status, "SUCCESS")
        self.assertEqual(exec_res.matched_option, "C")
        self.assertEqual(exec_res.operation, "MAX")
        self.assertAlmostEqual(exec_res.result, 281573.609414449, places=2)
        self.assertEqual(len(exec_res.operands), 4)
        for op in exec_res.operands:
            self.assertTrue(op.verified)

    def test_table_calculation_execution(self):
        """Test TABLE_CALCULATION execution computes subtraction and matches option B."""
        q = "需要对同一 Excel 附件做两处取数并计算。根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？A: 42212.17 B: -42212.17 C: -46433.39 D: -37990.95"
        plan = self.planner.plan(q)
        mt_res = self.retriever.retrieve(q, plan)

        exec_res = self.executor.execute(plan, mt_res)
        self.assertEqual(exec_res.status, "SUCCESS")
        self.assertEqual(exec_res.matched_option, "B")
        self.assertEqual(exec_res.operation, "SUBTRACT")
        self.assertAlmostEqual(exec_res.result, -42212.17, places=2)

    def test_table_lookup_execution(self):
        """Test TABLE_LOOKUP extracts exact coordinate value and matches option A."""
        q = "根据 Excel 附件《2023年10月人身险公司经营情况表》（工作表：人身保险公司（月度） ），“原保险保费收入”在“本年累计/截至当期”口径下的数值是多少？A: 31739.18 B: 6428.56 C: 24912.73 D: 397.89"
        plan = self.planner.plan(q)
        mt_res = self.retriever.retrieve(q, plan)

        exec_res = self.executor.execute(plan, mt_res)
        self.assertEqual(exec_res.status, "SUCCESS")
        self.assertEqual(exec_res.matched_option, "A")
        self.assertAlmostEqual(exec_res.result, 31739.18, places=2)

    def test_missing_operand_status_never_clarifies(self):
        """Test missing operand returns MISSING_OPERAND and does not trigger NEED_CLARIFICATION."""
        plan = TaskPlan(
            task_type="TABLE_CALCULATION",
            operation="SUBTRACT",
            operands=[
                TableOperand(name="不存在指标A", row="全国合计", column="不存在指标A"),
                TableOperand(name="不存在指标B", row="全国合计", column="不存在指标B"),
            ],
            need_clarification=False,
        )
        empty_res = []
        exec_res = self.executor.execute(plan, empty_res)
        self.assertEqual(exec_res.status, "MISSING_OPERAND")
        self.assertIn("缺少", exec_res.explanation)

    def test_rag_service_end_to_end_table_compare(self):
        """Test full RAGService.ask flow for table compare question."""
        q = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？A: 年化综合收益率 B: 年化财务收益率 C: 资金运用余额 D: 银行存款"
        ans = self.rag_service.ask(q)
        self.assertEqual(ans["status"], "answered")
        self.assertIn("C", ans["answer"])
        self.assertIn("资金运用余额", ans["answer"])
        self.assertTrue(ans["verification"]["passed"])
        self.assertIn("table_execution", ans["verification"])
        self.assertEqual(ans["verification"]["table_execution"]["matched_option"], "C")

    def test_rag_service_end_to_end_table_calculation(self):
        """Test full RAGService.ask flow for table calculation question."""
        q = "需要对同一 Excel 附件做两处取数并计算。根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？A: 42212.17 B: -42212.17 C: -46433.39 D: -37990.95"
        ans = self.rag_service.ask(q)
        self.assertEqual(ans["status"], "answered")
        self.assertIn("B", ans["answer"])
        self.assertIn("-42212.17", ans["answer"])
        self.assertTrue(ans["verification"]["passed"])
        self.assertIn("table_execution", ans["verification"])
        self.assertEqual(ans["verification"]["table_execution"]["matched_option"], "B")


if __name__ == "__main__":
    unittest.main()
