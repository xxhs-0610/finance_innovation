"""Unit tests for Evidence Adapter and Unified Evidence Layer (Prompt 10)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.evidence_adapter import evidence_adapter
from app.retrieval.table_executor import extract_operand_value, table_executor
from app.retrieval.option_verifier import option_verifier
from app.schemas.chunk_schema import KnowledgeChunk, SearchResult, SourceInfo
from app.schemas.unified_evidence_schema import UnifiedEvidence
from app.schemas.task_plan_schema import TableOperand, TaskPlan, TableSource


class EvidenceAdapterTest(unittest.TestCase):
    """Test suite for Unified Evidence Adapter across Excel, Word, and PDF."""

    def setUp(self):
        self.adapter = evidence_adapter
        self.executor = table_executor
        self.option_verifier = option_verifier

    def test_unified_evidence_schema(self):
        """Verify UnifiedEvidence structure adheres to Prompt 10 specification."""
        ev = UnifiedEvidence(
            evidence_id="chunk_123",
            source_type="excel",
            source_title="2023年4季度保险业资金运用情况表",
            location={"sheet": "资金运用表", "row": "银行存款", "column": "账面余额", "cell": "B12"},
            content="行=银行存款 | 账面余额 = 27154.34 | 单位：亿元",
            structured_value={"kv": {"账面余额": 27154.34}, "unit": "亿元"},
        )
        d = ev.to_dict()
        self.assertEqual(d["evidence_id"], "chunk_123")
        self.assertEqual(d["source_type"], "excel")
        self.assertEqual(d["source_title"], "2023年4季度保险业资金运用情况表")
        self.assertEqual(d["location"]["sheet"], "资金运用表")
        self.assertEqual(d["location"]["cell"], "B12")
        self.assertEqual(d["content"], "行=银行存款 | 账面余额 = 27154.34 | 单位：亿元")
        self.assertEqual(d["structured_value"]["unit"], "亿元")

    def test_adapt_excel_chunk(self):
        """Test adapting Excel chunk into UnifiedEvidence with sheet, row, column, cell location."""
        raw = {
            "chunk_id": "excel_001",
            "chunk_type": "table",
            "title": "2023年4季度保险业资金运用情况表",
            "sheet_name": "资金运用情况表",
            "cell_ref": "C10",
            "text": "【2023年4季度保险业资金运用情况表】| 行=资金运用余额 | 账面余额 = 281594.88 | 单位：亿元",
            "local_path": "data/raw/nfra_page_attachments_500/017_2023_funds.xlsx",
        }
        ev = self.adapter.adapt(raw)
        self.assertEqual(ev.source_type, "excel")
        self.assertEqual(ev.location["sheet"], "资金运用情况表")
        self.assertEqual(ev.location["row"], "资金运用余额")
        self.assertEqual(ev.location["cell"], "C10")
        self.assertIsNotNone(ev.structured_value)
        self.assertEqual(ev.structured_value["kv"].get("账面余额"), 281594.88)
        self.assertEqual(ev.structured_value.get("unit"), "亿元")

    def test_adapt_word_chunk(self):
        """Test adapting Word chunk into UnifiedEvidence with section and article location."""
        raw = {
            "chunk_id": "word_001",
            "chunk_type": "clause",
            "title": "消费金融公司管理办法",
            "clause_no": "第三条",
            "section_path": ["第一章 总则", "第三条 设立原则"],
            "text": "第三条 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款的非银行金融机构。",
            "local_path": "data/raw/rules/消费金融公司管理办法.docx",
        }
        ev = self.adapter.adapt(raw)
        self.assertEqual(ev.source_type, "word")
        self.assertEqual(ev.location["article"], "第三条")
        self.assertEqual(ev.location["section"], "第一章 总则 > 第三条 设立原则")
        self.assertIn("消费金融公司是经国家金融监督管理总局批准设立", ev.content)

    def test_adapt_pdf_chunk(self):
        """Test adapting PDF chunk into UnifiedEvidence with page location."""
        raw = {
            "chunk_id": "pdf_001",
            "chunk_type": "clause",
            "title": "商业银行资本管理办法",
            "clause_no": "第二十五条",
            "metadata": {"page": 10, "format": "pdf"},
            "text": "第 10 页 | 第二十五条 商业银行核心一级资本充足率不得低于5%，一级资本充足率不得低于6%。",
            "local_path": "data/raw/docs/商业银行资本管理办法.pdf",
        }
        ev = self.adapter.adapt(raw)
        self.assertEqual(ev.source_type, "pdf")
        self.assertEqual(ev.location["page"], 10)
        self.assertIn("核心一级资本充足率不得低于5%", ev.content)

    def test_unified_numeric_extraction_across_word_and_excel(self):
        """Verify that extract_operand_value works seamlessly across both Word policy text and Excel table."""
        # 1. Excel Evidence
        excel_ev = self.adapter.adapt({
            "chunk_id": "EX_1",
            "title": "保险统计表",
            "text": "行=银行存款 | 账面余额 = 27154.34 | 单位：亿元",
            "local_path": "test.xlsx",
        })
        op_excel = extract_operand_value([excel_ev], "银行存款", scope="账面余额")
        self.assertTrue(op_excel.verified)
        self.assertEqual(op_excel.value, 27154.34)
        self.assertEqual(op_excel.unit, "亿元")

        # 2. Word Policy Evidence
        word_ev = self.adapter.adapt({
            "chunk_id": "WD_1",
            "title": "消费金融公司管理办法",
            "text": "第八条 消费金融公司注册资本为一次性实缴货币资本，最低限额为3亿元人民币或等值的可自由兑换货币。",
            "local_path": "test.docx",
        })
        op_word = extract_operand_value([word_ev], "注册资本")
        self.assertTrue(op_word.verified)
        self.assertEqual(op_word.value, 3.0)
        self.assertEqual(op_word.unit, "亿元")

    def test_unified_option_verification_across_formats(self):
        """Verify that OptionVerificationEngine evaluates claims on adapted UnifiedEvidence regardless of format."""
        plan = TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            options={
                "A": "消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款的非银行金融机构",
                "B": "消费金融公司可以吸收公众存款",
            },
            need_clarification=False,
        )
        # Mix of Word and PDF adapted evidence
        ev1 = self.adapter.adapt({
            "chunk_id": "W1",
            "title": "消费金融公司管理办法",
            "text": "第三条 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、为中国境内居民个人提供消费贷款的非银行金融机构。",
            "local_path": "消费金融公司管理办法.docx",
        })
        res = self.option_verifier.verify(plan, [ev1])
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.selected_options, ["A"])


if __name__ == "__main__":
    unittest.main()
