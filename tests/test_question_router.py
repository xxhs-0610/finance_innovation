from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.router.question_router import QuestionRouter, question_router
from app.schemas.router_schema import RouteDecision
from app.services.rag_service import rag_service


class QuestionRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QuestionRouter()

    # -------------------------------------------------------------------------
    # 1. Level 1 Classification: SYSTEM_META
    # -------------------------------------------------------------------------
    def test_system_meta_classification(self) -> None:
        queries = [
            "你能做什么？",
            "这个系统解决什么问题？",
            "你支持哪些问题？",
            "你的数据来源是什么？",
            "为什么刚才不回答？",
            "你的回答可信吗？",
            "这个系统如何保证可信？",
            "你有哪些限制？",
            "你是什么系统",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "SYSTEM_META", f"Failed for query: {q}")
            self.assertFalse(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)
            self.assertIsNone(decision.qa_type)

    # -------------------------------------------------------------------------
    # 2. Level 1 Classification: OUT_OF_SCOPE
    # -------------------------------------------------------------------------
    def test_out_of_scope_stocks_and_investments(self) -> None:
        # Note: Must NOT be confused by the presence of '银行' in the query!
        queries = [
            "工商银行股票明天会不会涨？",
            "招商银行股价走势如何？",
            "现在适合买入平安银行股票吗？",
            "推荐几个高收益的银行理财产品？",
            "买什么基金比较赚钱？",
            "招商银行招聘前端开发工程师吗？",
            "明天北京天气怎么样？",
            "推荐一部好看的科幻电影",
            "帮我写一段 Python 快速排序代码",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "OUT_OF_SCOPE", f"Failed for query: {q}")
            self.assertFalse(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)
            self.assertIsNone(decision.qa_type)

    # -------------------------------------------------------------------------
    # 3. Level 1 Classification: NEED_CLARIFICATION
    # -------------------------------------------------------------------------
    def test_need_clarification_classification(self) -> None:
        queries = [
            "这个比例是多少？",
            "这样做合规吗？",
            "怎么办？",
            "什么意思？",
            "指标是多少",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "NEED_CLARIFICATION", f"Failed for query: {q}")
            self.assertFalse(decision.need_retrieval)
            self.assertTrue(decision.need_clarification)
            self.assertIsNone(decision.qa_type)

    # -------------------------------------------------------------------------
    # 4. Level 1 Classification: DOMAIN_QA and Level 2 Task Types
    # -------------------------------------------------------------------------
    def test_domain_qa_table_lookup(self) -> None:
        queries = [
            "2025年三季度商业银行资本充足率是多少？",
            "原保险保费收入在本年累计口径下是多少？",
            "根据 Excel 附件《2023年10月人身险公司经营情况表》（工作表：人身保险公司（月度） ），“原保险保费收入”在“本年累计/截至当期”口径下的数值是多少？",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "TABLE_LOOKUP", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_domain_qa_table_compare(self) -> None:
        queries = [
            "A、B、C、D中哪项数值最高？",
            "比较A、B、C、D谁最大",
            "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "TABLE_COMPARE", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_domain_qa_table_calculation(self) -> None:
        queries = [
            "从合计到健康险的数值变化约为多少？",
            "合计与健康险相差多少",
            "需要对同一 Excel 附件做两处取数并计算。根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "TABLE_CALCULATION", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_domain_qa_fact_single_choice(self) -> None:
        queries = [
            "根据《消费金融公司管理办法》，下列哪项表述正确？",
            "下列哪项表述正确？",
            "检索《数据安全事件分级》后，以下哪一项与材料内容一致？",
            "根据《账簿划分和名词解释》，下列哪项表述正确？\nA: 第一条\nB: 第二条\nC: 第三条\nD: 第四条",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "FACT_SINGLE_CHOICE", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_domain_qa_fact_multi_choice(self) -> None:
        queries = [
            "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？",
            "下列哪两项表述正确？",
            "下列哪些项符合《商业银行监管指引》？",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "FACT_MULTI_CHOICE", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_domain_qa_direct_fact_qa(self) -> None:
        queries = [
            "第三档商业银行核心一级资本充足率最低要求是多少？",
            "2024年《商业银行资本管理办法》第十条规定是什么？",
            "商业银行核心一级资本充足率降至5%以下是否合规？",
            "商业银行内部资本充足评估程序（ICAAP）的操作流程是什么？",
            "净稳定资金比例的计算方法是什么？",
        ]
        for q in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Failed for {q}")
            self.assertEqual(decision.task_type, "DIRECT_FACT_QA", f"Failed task_type for {q}")
            self.assertTrue(decision.need_retrieval)
            self.assertFalse(decision.need_clarification)

    def test_multi_target_not_ambiguous_rule(self) -> None:
        """Explicitly test critical rule: multiple targets NEVER equal ambiguity."""
        queries = [
            ("比较A、B、C、D谁最大", "TABLE_COMPARE"),
            ("合计与健康险相差多少", "TABLE_CALCULATION"),
            ("“全国合计”从“合计”到“健康险”的数值变化约为多少？", "TABLE_CALCULATION"),
            ("在“截至当期-账面余额”口径下，A、B、C、D哪一项数值最高？", "TABLE_COMPARE"),
        ]
        for q, expected_task in queries:
            decision = self.router.route(q)
            self.assertEqual(decision.intent, "DOMAIN_QA", f"Query {q} was incorrectly flagged as ambiguous")
            self.assertEqual(decision.task_type, expected_task)
            self.assertFalse(decision.need_clarification)
            self.assertTrue(decision.need_retrieval)

    # -------------------------------------------------------------------------
    # 5. Output Schema Contract
    # -------------------------------------------------------------------------
    def test_router_output_schema(self) -> None:
        decision = self.router.route("商业银行资本充足率监管底线是多少？")
        data = decision.to_dict()
        self.assertIn("intent", data)
        self.assertIn("task_type", data)
        self.assertIn("qa_type", data)
        self.assertIn("need_retrieval", data)
        self.assertIn("need_clarification", data)
        self.assertIn("reason", data)
        self.assertEqual(data["intent"], "DOMAIN_QA")
        self.assertEqual(data["task_type"], "DIRECT_FACT_QA")
        self.assertEqual(data["qa_type"], "DIRECT_FACT_QA")
        self.assertTrue(data["need_retrieval"])
        self.assertFalse(data["need_clarification"])

    # -------------------------------------------------------------------------
    # 6. RAG Service End-to-End Routing Tests
    # -------------------------------------------------------------------------
    def test_rag_service_handles_system_meta_without_retrieval(self) -> None:
        with patch.object(rag_service, "retrieve") as mock_retrieve:
            res = rag_service.ask("你能做什么？")
            mock_retrieve.assert_not_called()
            self.assertEqual(res["status"], "answered")
            self.assertTrue(any(kw in res["answer"] for kw in ("监管", "问答系统", "RAG", "报表")))
            self.assertIn("router", res["diagnostics"])
            self.assertEqual(res["diagnostics"]["router"]["intent"], "SYSTEM_META")

    def test_rag_service_handles_out_of_scope_without_retrieval(self) -> None:
        with patch.object(rag_service, "retrieve") as mock_retrieve:
            res = rag_service.ask("工商银行股票明天会不会涨？")
            mock_retrieve.assert_not_called()
            self.assertEqual(res["status"], "refused")
            self.assertIn("服务范围", res["answer"])
            self.assertIn("银行业监管制度", res["answer"])
            self.assertEqual(res["diagnostics"]["router"]["intent"], "OUT_OF_SCOPE")

    def test_system_card_targeted_questions(self) -> None:
        """Test the 5 specific SYSTEM_META questions requested by the user."""
        test_cases = [
            ("你是谁？", ["银行业监管", "问答系统"]),
            ("你能解决什么问题？", ["监管", "报表"]),
            ("你的数据来源是什么？", ["监管", "数据"]),
            ("为什么天气问题你不回答？", ["领域外", "不回答", "无关", "服务范围"]),
            ("你可以查询监管报表吗？", ["可以", "支持", "报表"]),
        ]
        for query, expected_keywords in test_cases:
            decision = self.router.route(query)
            self.assertEqual(decision.intent, "SYSTEM_META", f"Query failed router: {query}")
            with patch.object(rag_service, "retrieve") as mock_retrieve:
                res = rag_service.ask(query)
                mock_retrieve.assert_not_called()
                self.assertEqual(res["status"], "answered")
                self.assertTrue(
                    any(kw in res["answer"] for kw in expected_keywords),
                    f"None of {expected_keywords} found in answer: '{res['answer']}' for query: '{query}'"
                )


if __name__ == "__main__":
    unittest.main()
