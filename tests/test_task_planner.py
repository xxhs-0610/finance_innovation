"""Unit tests for Task Planner (Prompt 3)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.task_planner import (
    TaskPlanner,
    extract_choice_options,
    extract_sheet_name,
    task_planner,
)
from app.retrieval.query_analyzer import QueryAnalyzer, query_analyzer


class TaskPlannerTest(unittest.TestCase):
    """Test suite verifying Task Planner output structure against competition requirements."""

    def setUp(self):
        self.planner = task_planner
        self.analyzer = query_analyzer

    def test_extract_choice_options(self):
        """Test extraction of options in various delimiter formats."""
        # 1. Colon format inline
        q1 = "下列哪项正确？A: 选项一 B: 选项二 C: 选项三 D: 选项四"
        stem1, opts1 = extract_choice_options(q1)
        self.assertEqual(stem1, "下列哪项正确")
        self.assertEqual(opts1, {"A": "选项一", "B": "选项二", "C": "选项三", "D": "选项四"})

        # 2. Dot format multiline
        q2 = "以下哪项最高？\nA.年化收益\nB.财务收益\nC.资金运用\nD.银行存款"
        stem2, opts2 = extract_choice_options(q2)
        self.assertEqual(stem2, "以下哪项最高")
        self.assertEqual(opts2, {"A": "年化收益", "B": "财务收益", "C": "资金运用", "D": "银行存款"})

        # 3. No options
        q3 = "2024年《商业银行资本管理办法》第十条规定是什么？"
        stem3, opts3 = extract_choice_options(q3)
        self.assertEqual(stem3, q3)
        self.assertEqual(opts3, {})

    def test_extract_sheet_name(self):
        """Test sheet name extraction with and without nested parentheses."""
        s1 = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），以下哪项最高？"
        self.assertEqual(extract_sheet_name(s1), "2023年4季度保险资金运用情况表")

        s2 = "根据 Excel 附件《2023年10月人身险公司经营情况表》（工作表：人身保险公司（月度） ），数值是多少？"
        self.assertEqual(extract_sheet_name(s2), "人身保险公司（月度）")

        s3 = "根据 Excel 附件《2023年商业银行主要指标分机构类情况表（季度）》（工作表：商业银行分机构类情况表），数值是多少？"
        self.assertEqual(extract_sheet_name(s3), "商业银行分机构类情况表")

    def test_prompt3_example1_table_lookup(self):
        """Test TABLE_LOOKUP exact structure."""
        q = "根据 Excel 附件《2023年10月人身险公司经营情况表》（工作表：人身保险公司（月度） ），“原保险保费收入”在“本年累计/截至当期”口径下的数值是多少？A: 31739.18 B: 6428.56 C: 24912.73 D: 397.89"
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "TABLE_LOOKUP")
        self.assertEqual(d["source"]["file_name"], "2023年10月人身险公司经营情况表")
        self.assertEqual(d["source"]["sheet_name"], "人身保险公司（月度）")
        self.assertEqual(d["scope"], "本年累计/截至当期")
        self.assertEqual(len(d["targets"]), 1)
        self.assertEqual(d["targets"][0]["row"], "原保险保费收入")
        self.assertEqual(d["targets"][0]["column"], "本年累计")
        self.assertEqual(d["options"]["A"], "31739.18")
        self.assertFalse(d["need_clarification"])

    def test_prompt3_example2_table_compare(self):
        """Test TABLE_COMPARE exact structure and all candidate preservation."""
        q = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？A: 年化综合收益率 B: 年化财务收益率 C: 资金运用余额 D: 银行存款"
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "TABLE_COMPARE")
        self.assertEqual(d["source"]["file_name"], "2023年4季度保险业资金运用情况表")
        self.assertEqual(d["source"]["sheet_name"], "2023年4季度保险资金运用情况表")
        self.assertEqual(d["operation"], "MAX")
        self.assertEqual(d["scope"], "截至当期-账面余额")
        self.assertEqual(len(d["candidates"]), 4)
        self.assertEqual(d["candidates"][0], {"label": "A", "target": "年化综合收益率"})
        self.assertEqual(d["candidates"][1], {"label": "B", "target": "年化财务收益率"})
        self.assertEqual(d["candidates"][2], {"label": "C", "target": "资金运用余额"})
        self.assertEqual(d["candidates"][3], {"label": "D", "target": "银行存款"})
        self.assertFalse(d["need_clarification"])

    def test_prompt3_example3_table_calculation(self):
        """Test TABLE_CALCULATION operands and subtraction expression."""
        q = "需要对同一 Excel 附件做两处取数并计算。根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？A: 42212.17 B: -42212.17 C: -46433.39 D: -37990.95"
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "TABLE_CALCULATION")
        self.assertEqual(d["source"]["file_name"], "2023年12月全国各地区原保险保费收入情况表")
        self.assertIsNone(d["source"]["sheet_name"])
        self.assertEqual(d["operation"], "SUBTRACT")
        self.assertEqual(d["expression"], "健康险 - 合计")
        self.assertEqual(len(d["operands"]), 2)
        self.assertEqual(d["operands"][0], {"name": "合计", "row": "全国合计", "column": "合计"})
        self.assertEqual(d["operands"][1], {"name": "健康险", "row": "全国合计", "column": "健康险"})
        self.assertEqual(d["options"]["A"], "42212.17")
        self.assertEqual(d["options"]["B"], "-42212.17")
        self.assertFalse(d["need_clarification"])

    def test_prompt3_example4_fact_single_choice(self):
        """Test FACT_SINGLE_CHOICE structure."""
        q = "根据《消费金融公司管理办法》，下列哪项表述正确？ A: 消费金融公司是经国家金融监督管理总局批准设立... B: 核心数据遭到泄露... C: 重要数据遭到泄露... D: 重要数据遭到泄露2..."
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "FACT_SINGLE_CHOICE")
        self.assertEqual(d["source_constraints"]["document_name"], "消费金融公司管理办法")
        self.assertEqual(d["choice_mode"], "SINGLE")
        self.assertEqual(len(d["options"]), 4)
        self.assertEqual(d["options"][0]["label"], "A")
        self.assertEqual(d["options"][0]["claim"], "消费金融公司是经国家金融监督管理总局批准设立...")
        self.assertFalse(d["need_clarification"])

    def test_prompt3_example5_fact_multi_choice(self):
        """Test FACT_MULTI_CHOICE structure with required_correct_count and sub_claims."""
        q = "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？ A: 函证指引内容1。；消费贷款内容2。 B: 函证指引内容3。；消费金融内容4。 C: 函证指引内容5。；会计师事务所内容6。 D: 函证指引内容7。；消费金融公司内容8。"
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "FACT_MULTI_CHOICE")
        self.assertEqual(d["source_constraints"]["document_name"], "银行函证工作操作指引")
        self.assertEqual(d["choice_mode"], "MULTI")
        self.assertEqual(d["required_correct_count"], 2)
        self.assertEqual(len(d["options"]), 4)
        self.assertEqual(d["options"][0]["label"], "A")
        self.assertEqual(d["options"][0]["sub_claims"], ["函证指引内容1。", "消费贷款内容2。"])
        self.assertFalse(d["need_clarification"])

    def test_direct_fact_qa(self):
        """Test DIRECT_FACT_QA plan generation."""
        q = "2024年《商业银行资本管理办法》第十条规定是什么？"
        plan = self.planner.plan(q)
        d = plan.to_dict()

        self.assertEqual(d["task_type"], "DIRECT_FACT_QA")
        self.assertEqual(d["source_constraints"]["document_name"], "商业银行资本管理办法")
        self.assertEqual(d["source_constraints"]["article_number"], "第十条")
        self.assertIn("商业银行资本管理办法", d["query_keywords"])
        self.assertFalse(d["need_clarification"])

    def test_query_analyzer_integration(self):
        """Test QueryAnalyzer integration with TaskPlanner."""
        q = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？A: 年化综合收益率 B: 年化财务收益率 C: 资金运用余额 D: 银行存款"
        analysis = self.analyzer.analyze(q, task_type="TABLE_COMPARE")

        self.assertIsNotNone(analysis.task_plan)
        self.assertEqual(analysis.task_plan.task_type, "TABLE_COMPARE")
        self.assertEqual(len(analysis.task_plan.candidates), 4)
        self.assertEqual(analysis.document_name, "2023年4季度保险业资金运用情况表")

        d = analysis.to_analyzer_dict()
        self.assertIn("task_plan", d)
        self.assertEqual(d["task_plan"]["task_type"], "TABLE_COMPARE")
        self.assertEqual(d["task_plan"]["operation"], "MAX")


if __name__ == "__main__":
    unittest.main()
