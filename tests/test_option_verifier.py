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
from app.schemas.chunk_schema import SearchResult, SourceInfo
from app.schemas.multi_target_retrieval_schema import (
    MultiTargetRetrievalResponse,
    TargetRetrievalResult,
)


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

    def test_all_nei_options_do_not_get_promoted_by_ranking(self):
        plan = TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            question="根据《目标规定》，下列哪项表述正确？",
            source_constraints=SourceConstraints(document_name="目标规定"),
            options=[
                ChoiceOption(label="A", claim="甲机构必须在十日内报告。"),
                ChoiceOption(label="B", claim="乙机构可以免于报告。"),
                ChoiceOption(label="C", claim="丙机构应当每月报告。"),
                ChoiceOption(label="D", claim="丁机构不得提交报告。"),
            ],
        )
        results = []
        merged = []
        for label in "ABCD":
            evidence = SearchResult(
                chunk_id=f"target_{label}",
                chunk_type="clause",
                score=99.0,
                text="本条规定适用于风险管理制度和内部控制流程。",
                source=SourceInfo(doc_id="target", title="目标规定"),
            )
            merged.append(evidence)
            results.append(
                TargetRetrievalResult(
                    task_id=f"OPT_{label}",
                    target=label,
                    evidence=[evidence],
                )
            )

        response = MultiTargetRetrievalResponse(
            query=plan.question,
            task_type=plan.task_type,
            task_plan=plan,
            retrieval_results=results,
            merged_evidence=merged,
        )

        verified = self.verifier.verify(plan, response)

        self.assertEqual(verified.status, "NO_DECISION")
        self.assertEqual(verified.selected_options, [])
        self.assertTrue(
            all(item.verdict == "NOT_ENOUGH_EVIDENCE" for item in verified.options_verification)
        )

    def test_empty_source_metadata_cannot_match_requested_document(self):
        claim = "寿险合同负债评估采用基础利率曲线加综合溢价形成折现率曲线。"
        evidence = SearchResult(
            chunk_id="wrong_doc_exact",
            chunk_type="clause",
            score=100.0,
            text=claim,
            source=SourceInfo(doc_id="other_doc", title=""),
            metadata={},
        )

        result = self.verifier.verify_single_claim(
            claim,
            [evidence],
            doc_name="寿险合同负债评估折现率曲线",
        )

        self.assertEqual(result.verdict, "NOT_ENOUGH_EVIDENCE")
        self.assertEqual(result.evidence_ids, [])

    def test_consecutive_chunks_can_jointly_support_one_claim(self):
        claim = "计算现金流现值所采用的折现率曲线由基础利率曲线加综合溢价形成。"
        source = SourceInfo(doc_id="life_rate", title="寿险合同负债评估折现率曲线")
        evidence = [
            SearchResult(
                chunk_id="life_rate_clause_0004",
                chunk_type="clause",
                score=0.8,
                text="计算现金流现值所采用的折现",
                source=source,
            ),
            SearchResult(
                chunk_id="life_rate_clause_0005",
                chunk_type="clause",
                score=0.7,
                text="率曲线由基础利率曲线加综合溢价形成。",
                source=source,
            ),
        ]

        result = self.verifier.verify_single_claim(
            claim,
            evidence,
            doc_name="寿险合同负债评估折现率曲线",
        )

        self.assertEqual(result.verdict, "SUPPORTED")
        self.assertEqual(
            result.evidence_ids,
            ["life_rate_clause_0004", "life_rate_clause_0005"],
        )

    def test_numbered_heading_and_section_path_are_valid_evidence(self):
        heading = SearchResult(
            chunk_id="license_clause_0090",
            chunk_type="clause",
            score=0.8,
            text="1.2 中资商业银行法人机构开业核准",
            source=SourceInfo(
                doc_id="license",
                title="中资商业银行行政许可事项申请材料目录及格式要求（2023年版）",
                section_path=["一、机构设立"],
            ),
        )
        split_section = SearchResult(
            chunk_id="life_rate_clause_0037",
            chunk_type="clause",
            score=0.8,
            text="值法得到：",
            source=SourceInfo(
                doc_id="life_rate",
                title="寿险合同负债评估折现率曲线",
                local_path="寿险合同负债评估折现率曲线.pdf",
                section_path=["（三）20 年到 40 年之间的综合溢价采用以下线性插"],
            ),
        )

        heading_result = self.verifier.verify_single_claim(
            "中资商业银行法人机构开业核准属于机构设立类行政许可事项。",
            [heading],
            doc_name="中资商业银行行政许可事项申请材料目录及格式要求（2023年版）",
        )
        section_result = self.verifier.verify_single_claim(
            "20年到40年之间的综合溢价采用线性插值法得到。",
            [split_section],
            doc_name="寿险合同负债评估折现率曲线",
        )

        self.assertEqual(heading_result.verdict, "SUPPORTED")
        self.assertEqual(section_result.verdict, "SUPPORTED", msg=str(section_result.to_dict()))

    def test_missing_option_task_does_not_borrow_merged_evidence(self):
        claim = "消费金融公司不得吸收公众存款。"
        plan = TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            question="根据《消费金融公司管理办法》，下列哪项表述正确？",
            source_constraints=SourceConstraints(document_name="消费金融公司管理办法"),
            options=[
                ChoiceOption(label="A", claim=claim),
                ChoiceOption(label="B", claim=claim),
            ],
        )
        evidence = SearchResult(
            chunk_id="consumer_clause",
            chunk_type="clause",
            score=100.0,
            text=claim,
            source=SourceInfo(doc_id="consumer", title="消费金融公司管理办法"),
        )
        response = MultiTargetRetrievalResponse(
            query=plan.question,
            task_type=plan.task_type,
            task_plan=plan,
            retrieval_results=[
                TargetRetrievalResult(task_id="OPT_A", target=claim, evidence=[evidence])
            ],
            merged_evidence=[evidence],
        )

        verified = self.verifier.verify(plan, response)

        self.assertEqual(verified.status, "SUCCESS")
        self.assertEqual(verified.selected_options, ["A"])
        option_b = next(item for item in verified.options_verification if item.option == "B")
        self.assertEqual(option_b.verdict, "NOT_ENOUGH_EVIDENCE")
        self.assertEqual(option_b.evidence_ids, [])

    def test_real_index_q201_isolated_to_requested_document(self):
        question = (
            "根据《寿险合同负债评估折现率曲线》，下列哪项表述正确？\n"
            "A. 寿险合同负债评估中计算现金流现值所采用的折现率曲线由基础利率曲线加综合溢价形成。\n"
            "B. 列入名单的保险集团应当按照《保险公司偿付能力监管规则第19号：保险集团》有关规定编报保险集团偿付能力报告。\n"
            "C. 其他符合保险集团定义的保险集团暂不编报偿付能力报告。\n"
            "D. 中国人民保险集团股份有限公司属于应当编制保险集团偿付能力报告的保险控股型集团。"
        )
        plan = self.planner.plan(question)
        retrieval = self.retriever.retrieve(question, plan)

        retrieved_doc_ids = {
            item.source.doc_id
            for result in retrieval.retrieval_results
            for item in result.evidence
        }
        verified = self.verifier.verify(plan, retrieval)

        self.assertTrue(retrieved_doc_ids)
        self.assertEqual(retrieved_doc_ids, {"nfra_att_460"})
        self.assertEqual(
            verified.status,
            "SUCCESS",
            msg=str(
                {
                    "retrieval": {
                        result.task_id: [item.chunk_id for item in result.evidence]
                        for result in retrieval.retrieval_results
                    },
                    "verification": [
                        item.to_dict() for item in verified.options_verification
                    ],
                }
            ),
        )
        self.assertEqual(verified.selected_options, ["A"])

    def test_plain_attachment_prefix_and_truncated_version_resolve(self):
        from app.retrieval.multi_target_retriever import _preferred_document_ids

        document_name = "中资商业银行行政许可事项申请材料目录及格式要求（2023年版）"

        self.assertEqual(
            _preferred_document_ids(self.retriever.db_path, document_name),
            ["nfra_att_430"],
        )

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
