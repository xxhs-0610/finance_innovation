"""Unit tests for QueryAnalyzer entity extraction and zero-hallucination constraints."""

from __future__ import annotations

import unittest
from app.retrieval.query_analyzer import QueryAnalyzer, query_analyzer


class QueryAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = query_analyzer

    def test_user_canonical_example(self) -> None:
        """Test the exact canonical example provided by the user."""
        q = "商业银行资本充足率最低监管要求是多少？"
        analysis = self.analyzer.analyze(q)
        res = analysis.to_analyzer_dict()

        self.assertEqual(res["query"], "商业银行资本充足率最低监管要求是多少")
        self.assertEqual(res["topic"], "资本监管")
        self.assertEqual(res["institution_type"], "商业银行")
        self.assertIsNone(res["regulator"], "Regulator must be null if not explicitly mentioned")
        self.assertIsNone(res["document_name"], "Document name must be null if not explicitly mentioned")
        self.assertIsNone(res["article_number"], "Article number must be null if not explicitly mentioned")
        self.assertEqual(res["indicator"], "资本充足率")
        self.assertIsNone(res["time_period"], "Time period must be null if not explicitly mentioned")
        self.assertEqual(res["rule_type"], "最低监管要求")
        self.assertEqual(res["keywords"], ["商业银行", "资本充足率", "最低要求"])

    def test_never_guesses_unmentioned_period(self) -> None:
        """Verify strict constraint: never guess or extrapolate time periods."""
        queries = [
            "商业银行资本充足率最低监管要求是多少？",
            "流动性覆盖率监管指标是如何计算的？",
            "第二档商业银行信息披露有哪些要求？",
        ]
        for q in queries:
            analysis = self.analyzer.analyze(q)
            self.assertIsNone(analysis.time_period, f"Guessed time_period for query: {q}")
            self.assertNotIn("publish_date", analysis.filters)

    def test_never_guesses_unmentioned_document_name(self) -> None:
        """Verify strict constraint: never guess document name from background knowledge."""
        queries = [
            "商业银行资本充足率最低监管要求是多少？",
            "不良贷款率的监管预警线是多少？",
            "金融机构恢复与处置计划由谁制定？",
        ]
        for q in queries:
            analysis = self.analyzer.analyze(q)
            self.assertIsNone(analysis.document_name, f"Guessed document_name for query: {q}")
            self.assertNotIn("title", analysis.filters)

    def test_never_guesses_unmentioned_regulator(self) -> None:
        """Verify strict constraint: never supply regulator using LLM knowledge."""
        queries = [
            "商业银行资本充足率最低监管要求是多少？",
            "第三档商业银行核心一级资本充足率最低要求是多少？",
            "贷款拨备率应如何计算？",
        ]
        for q in queries:
            analysis = self.analyzer.analyze(q)
            self.assertIsNone(analysis.regulator, f"Guessed regulator for query: {q}")
            self.assertNotIn("issuer", analysis.filters)

    def test_explicit_regulator_extraction(self) -> None:
        """Verify explicit regulator extraction when mentioned in query."""
        q = "国家金融监督管理总局发布的第三档商业银行核心一级资本充足率最低要求是多少？"
        analysis = self.analyzer.analyze(q)
        self.assertEqual(analysis.regulator, "国家金融监督管理总局")
        self.assertEqual(analysis.institution_type, "第三档商业银行")
        self.assertEqual(analysis.indicator, "核心一级资本充足率")
        self.assertEqual(analysis.rule_type, "最低监管要求")
        self.assertIn("国家金融监督管理总局", analysis.keywords)

    def test_explicit_document_and_article_extraction(self) -> None:
        """Verify explicit document title and article number extraction."""
        q = "2024年《商业银行资本管理办法》第十条规定是什么？"
        analysis = self.analyzer.analyze(q)
        self.assertEqual(analysis.document_name, "商业银行资本管理办法")
        self.assertEqual(analysis.article_number, "第十条")
        self.assertEqual(analysis.time_period, "2024年")
        self.assertEqual(analysis.institution_type, "商业银行")
        self.assertIsNone(analysis.regulator)

    def test_table_lookup_period_and_metric(self) -> None:
        """Verify table query with explicit quarter and metric."""
        q = "2025年三季度商业银行资本充足率是多少？"
        analysis = self.analyzer.analyze(q)
        self.assertEqual(analysis.time_period, "2025年三季度")
        self.assertEqual(analysis.indicator, "资本充足率")
        self.assertEqual(analysis.institution_type, "商业银行")
        self.assertEqual(analysis.rule_type, "统计报表取数")
        self.assertEqual(analysis.preferred_chunk_type, "table")

    def test_compliance_judgment_rule_type(self) -> None:
        """Verify compliance judgment rule type and topic."""
        q = "商业银行核心一级资本充足率降至5%以下是否合规？"
        analysis = self.analyzer.analyze(q)
        self.assertEqual(analysis.topic, "资本监管")
        self.assertEqual(analysis.rule_type, "合规判定")
        self.assertEqual(analysis.indicator, "核心一级资本充足率")
        self.assertEqual(analysis.institution_type, "商业银行")

    def test_business_procedure_rule_type(self) -> None:
        """Verify business procedure rule type."""
        q = "商业银行内部资本充足评估程序（ICAAP）的操作流程是什么？"
        analysis = self.analyzer.analyze(q)
        self.assertEqual(analysis.topic, "资本监管")
        self.assertEqual(analysis.rule_type, "业务流程")
        self.assertEqual(analysis.institution_type, "商业银行")


if __name__ == "__main__":
    unittest.main()
