"""Unit tests for Multi-target Retrieval (Prompt 4)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.multi_target_retriever import (
    MultiTargetRetriever,
    find_matching_table_titles,
    multi_target_retriever,
)
from app.retrieval.task_planner import task_planner
from app.retrieval.hybrid_retriever import HybridRetriever, retrieve


class MultiTargetRetrieverTest(unittest.TestCase):
    """Test suite verifying Multi-target Retrieval decomposition and execution."""

    def setUp(self):
        self.retriever = multi_target_retriever
        self.planner = task_planner

    def test_table_title_matcher(self):
        """Test fuzzy table title matching with quarter variants and synonyms."""
        # 1. Quarter Arabic vs Chinese numerals
        titles1 = find_matching_table_titles(
            self.retriever.db_path, "2023年4季度保险业资金运用情况表"
        )
        self.assertIn("2023年四季度保险业资金运用情况表", titles1)

        # 2. Synonym 财产险 vs 财产保险
        titles2 = find_matching_table_titles(
            self.retriever.db_path, "2024年9月财产保险公司经营情况表"
        )
        self.assertIn("2024年9月财产险公司经营情况表", titles2)

    def test_table_compare_multi_target_retrieval(self):
        """Test TABLE_COMPARE generates 4 discrete tasks and retrieves 4 candidate results."""
        q = "根据 Excel 附件《2023年4季度保险业资金运用情况表》（工作表：2023年4季度保险资金运用情况表），在“截至当期-账面余额”口径下，以下哪一项数值最高？A: 年化综合收益率 B: 年化财务收益率 C: 资金运用余额 D: 银行存款"
        plan = self.planner.plan(q)
        resp = self.retriever.retrieve(q, plan, top_k=3)

        # 1. Verify tasks
        tasks = resp.retrieval_tasks
        self.assertEqual(len(tasks), 4)
        self.assertEqual(tasks[0].task_id, "CAND_A")
        self.assertEqual(tasks[1].task_id, "CAND_B")
        self.assertEqual(tasks[2].task_id, "CAND_C")
        self.assertEqual(tasks[3].task_id, "CAND_D")

        # 2. Verify results
        results = resp.retrieval_results
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertEqual(r.status, "SUCCESS")
            self.assertGreater(len(r.evidence), 0)

        # 3. Verify specific values in evidence
        # Option C is 资金运用余额
        c_evidence = results[2].evidence[0].text
        self.assertIn("资金运用余额", c_evidence)
        self.assertIn("281573.609414449", c_evidence)

        # 4. Verify merged evidence
        self.assertGreater(len(resp.merged_evidence), 0)

        # 5. Verify JSON schema format
        d = resp.to_dict()
        self.assertIn("retrieval_tasks", d)
        self.assertIn("retrieval_results", d)
        self.assertEqual(d["retrieval_tasks"][0]["task_id"], "CAND_A")
        self.assertEqual(d["retrieval_results"][0]["status"], "SUCCESS")

    def test_table_calculation_multi_target_retrieval(self):
        """Test TABLE_CALCULATION retrieves both operands distinctly."""
        q = "需要对同一 Excel 附件做两处取数并计算。根据《2023年12月全国各地区原保险保费收入情况表》，“全国合计”从“合计”到“健康险”的数值变化约为多少？A: 42212.17 B: -42212.17 C: -46433.39 D: -37990.95"
        plan = self.planner.plan(q)
        resp = self.retriever.retrieve(q, plan, top_k=3)

        # 1. Verify tasks
        tasks = resp.retrieval_tasks
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].task_id, "OPERAND_1")
        self.assertEqual(tasks[1].task_id, "OPERAND_2")

        # 2. Verify results
        results = resp.retrieval_results
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, "SUCCESS")
        self.assertEqual(results[1].status, "SUCCESS")

        # 3. Verify operand 1 & 2 content
        text1 = results[0].evidence[0].text
        text2 = results[1].evidence[0].text
        self.assertIn("合计=51246.71", text1)
        self.assertIn("健康险=9034.54", text2)

    def test_fact_single_choice_multi_target_retrieval(self):
        """Test FACT_SINGLE_CHOICE discrete claim retrieval under document constraint."""
        q = "根据《消费金融公司管理办法》，下列哪项表述正确？ A: 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。 B: 核心数据遭到泄露、破坏或者非法获取、非法利用，属于特别重大数据安全事件。 C: 重要数据遭到泄露... D: 重要数据遭到泄露2..."
        plan = self.planner.plan(q)
        resp = self.retriever.retrieve(q, plan, top_k=2)

        self.assertEqual(len(resp.retrieval_tasks), 4)
        self.assertEqual(resp.retrieval_tasks[0].task_id, "OPT_A")
        self.assertEqual(resp.retrieval_tasks[0].source_constraints["document_name"], "消费金融公司管理办法")

        # Option A must be SUCCESS with high match
        res_a = resp.retrieval_results[0]
        self.assertEqual(res_a.status, "SUCCESS")
        self.assertIn("第二条", res_a.evidence[0].text)

    def test_fact_multi_choice_multi_target_retrieval(self):
        """Test FACT_MULTI_CHOICE discrete sub-claim retrieval."""
        q = "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？ A: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；消费贷款是消费金融公司向借款人发放的以消费为目的的贷款，但不包括购买住房和汽车的贷款。 B: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；消费金融公司名称中应当标明“消费金融”字样，未经批准不得在名称中使用该字样。 C: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；会计师事务所在实施银行函证过程中，应当安排专门部门或岗位集中发送、收回银行询证函。 D: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。"
        plan = self.planner.plan(q)
        resp = self.retriever.retrieve(q, plan, top_k=2)

        self.assertEqual(len(resp.retrieval_tasks), 4)
        self.assertEqual(len(resp.retrieval_tasks[2].sub_targets), 2)

        # Option C should retrieve evidence for both sub-claims
        res_c = resp.retrieval_results[2]
        self.assertEqual(res_c.status, "SUCCESS")
        self.assertGreaterEqual(len(res_c.evidence), 2)

    def test_hybrid_retriever_multi_target_integration(self):
        """Test HybridRetriever.search automatically delegates to multi-target retrieval."""
        q = "根据 Excel 附件《2023年10月人身险公司经营情况表》（工作表：人身保险公司（月度） ），“原保险保费收入”在“本年累计/截至当期”口径下的数值是多少？A: 31739.18 B: 6428.56 C: 24912.73 D: 397.89"
        ret_response = retrieve(q, top_k=3, task_type="TABLE_LOOKUP")

        self.assertEqual(ret_response.status, "answerable")
        self.assertGreater(len(ret_response.evidence), 0)
        self.assertIn("31739.18", ret_response.evidence[0].text)
        self.assertIn("retrieval_tasks", ret_response.diagnostics)
        self.assertIn("retrieval_results", ret_response.diagnostics)


if __name__ == "__main__":
    unittest.main()
