"""Unit tests for Option Verification Engine (Prompt 6)."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure backend in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.retrieval.option_verifier import (
    OptionVerificationEngine,
    clean_for_match,
    compute_sliding_similarity,
    detect_contradictions,
    detect_question_intent_target,
    option_verifier,
)
from app.retrieval.task_planner import task_planner
from app.retrieval.multi_target_retriever import multi_target_retriever
from app.services.rag_service import RAGService
from app.schemas.task_plan_schema import ChoiceOption, SourceConstraints, TaskPlan


class OptionVerifierTest(unittest.TestCase):
    """Test suite verifying discrete option verification for single and multi choice QA."""

    def setUp(self):
        self.verifier = option_verifier
        self.planner = task_planner
        self.retriever = multi_target_retriever
        self.rag_service = RAGService()

    def test_detect_question_intent_target(self):
        """Test detection of question polarity (CORRECT vs INCORRECT)."""
        self.assertEqual(detect_question_intent_target("下列哪项表述正确？"), "CORRECT")
        self.assertEqual(detect_question_intent_target("下列关于商业银行资本充足率的说法，符合规定的是？"), "CORRECT")
        self.assertEqual(detect_question_intent_target("下列哪项表述不正确？"), "INCORRECT")
        self.assertEqual(detect_question_intent_target("下列哪一项属于违规行为？"), "INCORRECT")
        self.assertEqual(detect_question_intent_target("以下哪项不符合监管要求？"), "INCORRECT")

    def test_compute_sliding_similarity(self):
        """Test high similarity on real regulatory clause text."""
        claim = "消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。"
        evidence = "第二条 本办法所称消费金融公司，是指经国家金融监督管理总局批准设立的，不吸收公众存款，以小额、分散为原则，为中国境内居民个人提供消费贷款的非银行金融机构。"
        sim, _ = compute_sliding_similarity(claim, evidence)
        self.assertGreater(sim, 0.90)

    def test_detect_contradictions(self):
        """Test explicit numerical and modality contradiction detection."""
        # 1. Number contradiction
        claim_num = "商业银行注册资本最低限额为人民币 10亿元。"
        ev_num = "商业银行注册资本最低限额为人民币 1亿元。"
        is_contra, msg = detect_contradictions(claim_num, ev_num)
        self.assertTrue(is_contra)
        self.assertIn("1亿元", msg)
        self.assertIn("10亿元", msg)

        # 2. Modality contradiction (prohibition vs permission)
        claim_modal = "消费金融公司可以投资股票和二级市场证券。"
        ev_modal = "消费金融公司不得从事投资股票、二级市场证券以及其他高风险金融资产。"
        is_contra2, msg2 = detect_contradictions(claim_modal, ev_modal)
        self.assertTrue(is_contra2)
        self.assertIn("不得", msg2)

    def test_single_choice_verification_engine(self):
        """Test FACT_SINGLE_CHOICE discrete verification returns Option A."""
        q = "根据《消费金融公司管理办法》，下列哪项表述正确？ A: 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。 B: 核心数据遭到泄露、破坏或者非法获取、非法利用，属于特别重大数据安全事件。 C: 重要数据遭到泄露、破坏或者非法获取、非法利用，并对2个及以上省级区域经济运行秩序造成特别严重影响，属于特别重大数据安全事件。 D: 重要数据遭到泄露、破坏或者非法获取、非法利用，并对省级区域经济带来重大影响或者对银行保险行业安全造成影响，属于重大数据安全事件。"
        plan = self.planner.plan(q)
        mt_res = self.retriever.retrieve(q, plan)

        res = self.verifier.verify(plan, mt_res)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.selected_options, ["A"])
        self.assertEqual(res.options_verification[0].verdict, "SUPPORTED")
        self.assertIn("nfra_att_", res.options_verification[0].evidence_ids[0])
        self.assertEqual(res.options_verification[1].verdict, "NOT_ENOUGH_EVIDENCE")

    def test_multi_choice_verification_engine(self):
        """Test FACT_MULTI_CHOICE discrete sub-claim verification returns Option C."""
        q = "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？ A: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；消费贷款是消费金融公司向借款人发放的以消费为目的的贷款，但不包括购买住房和汽车的贷款。 C: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；会计师事务所在实施银行函证过程中，应当安排专门部门或岗位集中发送、收回银行询证函。"
        plan = self.planner.plan(q)
        mt_res = self.retriever.retrieve(q, plan)

        res = self.verifier.verify(plan, mt_res)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.selected_options, ["C"])

        opt_a = next(o for o in res.options_verification if o.option == "A")
        opt_c = next(o for o in res.options_verification if o.option == "C")

        self.assertEqual(opt_a.verdict, "NOT_ENOUGH_EVIDENCE")
        self.assertEqual(opt_c.verdict, "SUPPORTED")
        self.assertEqual(len(opt_c.sub_claims), 2)
        self.assertTrue(all(sc.verdict == "SUPPORTED" for sc in opt_c.sub_claims))

    def test_rag_service_end_to_end_single_choice(self):
        """Test full RAGService.ask flow for fact single choice question."""
        q = "根据《消费金融公司管理办法》，下列哪项表述正确？ A: 消费金融公司是经国家金融监督管理总局批准设立、不吸收公众存款、以小额分散为原则、为中国境内居民个人提供消费贷款的非银行金融机构。 B: 核心数据遭到泄露、破坏或者非法获取、非法利用，属于特别重大数据安全事件。 C: 重要数据遭到泄露、破坏或者非法获取、非法利用，并对2个及以上省级区域经济运行秩序造成特别严重影响，属于特别重大数据安全事件。 D: 重要数据遭到泄露、破坏或者非法获取、非法利用，并对省级区域经济带来重大影响或者对银行保险行业安全造成影响，属于重大数据安全事件。"
        ans = self.rag_service.ask(q)
        self.assertEqual(ans["status"], "answered")
        self.assertIn("A", ans["answer"])
        self.assertTrue(ans["verification"]["passed"])
        self.assertIn("option_verification", ans["verification"])
        self.assertEqual(ans["verification"]["option_verification"]["selected_options"], ["A"])

    def test_rag_service_end_to_end_multi_choice(self):
        """Test full RAGService.ask flow for fact multi choice question."""
        q = "关于《银行函证工作操作指引》，下列哪一组选项中的两项表述均属于该材料内容？ A: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；消费贷款是消费金融公司向借款人发放的以消费为目的的贷款，但不包括购买住房和汽车的贷款。 C: 银行函证工作操作指引用于进一步明确和细化银行函证工作中的具体事项，推进会计师事务所和银行业金融机构提高银行函证工作质量和效率。；会计师事务所在实施银行函证过程中，应当安排专门部门或岗位集中发送、收回银行询证函。"
        ans = self.rag_service.ask(q)
        self.assertEqual(ans["status"], "answered")
        self.assertIn("C", ans["answer"])
        self.assertTrue(ans["verification"]["passed"])
        self.assertIn("option_verification", ans["verification"])
        self.assertEqual(ans["verification"]["option_verification"]["selected_options"], ["C"])


if __name__ == "__main__":
    unittest.main()
