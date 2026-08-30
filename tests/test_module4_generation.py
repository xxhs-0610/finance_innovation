from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.api.main import ask
from app.generation.answer_generator import generate_answer
from app.generation.deepseek_client import _extract_answer, deepseek_enabled
from app.generation.prompt_builder import build_generation_prompt
from app.generation.verifier import extract_numeric_claims, verify_answer
from app.schemas.task_plan_schema import ChoiceOption, SourceConstraints, TaskPlan


def clause_evidence(text: str, *, chunk_id: str = "doc1_clause_0001") -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_type": "clause",
        "score": 1.2,
        "text": text,
        "source": {
            "doc_id": "doc1",
            "title": "商业银行资本管理办法",
            "issuer": "国家金融监督管理总局",
            "publish_date": "2023-11-01",
            "clause_no": "第十条",
            "source_url": "https://example.com/doc1",
        },
        "metadata": {},
    }


class Module4GenerationTest(unittest.TestCase):
    def test_shared_generation_config_is_present(self) -> None:
        root_cand = Path(__file__).resolve().parents[1] / "configs" / "generation.json"
        backend_cand = Path(__file__).resolve().parents[1] / "backend" / "configs" / "generation.json"
        config_path = backend_cand if backend_cand.exists() else root_cand
        self.assertTrue(config_path.exists())
        self.assertNotIn("api_key", config_path.read_text(encoding="utf-8").lower())

    def test_environment_overrides_shared_generation_config(self) -> None:
        with patch.dict("os.environ", {"DEEPSEEK_ENABLED": "true"}, clear=False):
            self.assertTrue(deepseek_enabled())

    def test_deepseek_json_response_is_unwrapped(self) -> None:
        self.assertEqual(
            _extract_answer(
                {"choices": [{"message": {"content": '{"status":"answered","answer":"答案。[E1]"}'}}]}
            ),
            "答案。[E1]",
        )

    def test_deepseek_markdown_json_response_is_unwrapped(self) -> None:
        self.assertEqual(
            _extract_answer(
                {"choices": [{"message": {"content": '```json\n{"answer":"答案。[E1]"}\n```'}}]}
            ),
            "答案。[E1]",
        )

    def test_deepseek_json_citations_are_added_when_answer_omits_them(self) -> None:
        self.assertEqual(
            _extract_answer(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"answer":"答案。","citations":["E1"]}'
                            }
                        }
                    ]
                }
            ),
            "答案。 [E1]",
        )

    def test_default_generator_returns_cited_verified_answer(self) -> None:
        evidence = [
            clause_evidence(
                "商业银行核心一级资本充足率不得低于5%，一级资本充足率不得低于6%，"
                "资本充足率不得低于8%。"
            )
        ]
        result = generate_answer("资本充足率最低要求是多少？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertIn("[E1]", result["answer"])
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(result["citations"], ["E1"])
        self.assertGreater(result["confidence"], 0)

    def test_empty_or_unrelated_evidence_triggers_refusal(self) -> None:
        empty_result = generate_answer("资本充足率是多少？", [])
        unrelated_result = generate_answer(
            "资本充足率是多少？",
            [clause_evidence("银行业金融机构应当建立数据质量检查机制。")],
        )

        self.assertEqual(empty_result["status"], "refused")
        self.assertEqual(unrelated_result["status"], "refused")
        self.assertEqual(empty_result["confidence"], 0.0)

    def test_duration_question_without_numeric_term_is_refused(self) -> None:
        evidence = [clause_evidence("商业银行应当妥善保存监管统计资料。")]

        result = generate_answer(
            "监管统计资料按规定必须保存几年？",
            evidence,
            generator=lambda _question, _evidence: "按规定保存五年。[E1]",
        )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["verification"]["evidence_verifier"]["reason_code"], "MISSING_NUMERIC_EVIDENCE")
        self.assertEqual(result["confidence"], 0.0)

    def test_hallucinated_number_is_blocked(self) -> None:
        evidence = [clause_evidence("商业银行资本充足率不得低于8%。")]

        result = generate_answer(
            "资本充足率最低要求是多少？",
            evidence,
            generator=lambda _question, _evidence: "资本充足率不得低于10%。[E1]",
        )

        self.assertEqual(result["status"], "refused")
        self.assertFalse(result["verification"]["passed"])
        self.assertEqual(result["verification"]["unsupported_claims"][0]["raw"], "10%")

    def test_generator_failure_is_converted_to_safe_refusal(self) -> None:
        evidence = [clause_evidence("商业银行资本充足率不得低于8%。")]

        def broken_generator(_question, _evidence):
            raise RuntimeError("provider unavailable")

        result = generate_answer(
            "资本充足率最低要求是多少？",
            evidence,
            generator=broken_generator,
        )

        self.assertEqual(result["status"], "refused")
        self.assertIn("答案生成服务调用失败", result["refusal_reason"])

    def test_fact_choice_generator_cannot_override_verified_option(self) -> None:
        claim_a = "消费金融公司不得吸收公众存款。"
        plan = TaskPlan(
            task_type="FACT_SINGLE_CHOICE",
            question="根据《消费金融公司管理办法》，下列哪项表述正确？",
            source_constraints=SourceConstraints(document_name="消费金融公司管理办法"),
            options=[
                ChoiceOption(label="A", claim=claim_a),
                ChoiceOption(label="B", claim="消费金融公司可以吸收公众存款。"),
            ],
        )
        evidence_a = clause_evidence(claim_a, chunk_id="consumer_a")
        evidence_a["source"]["title"] = "消费金融公司管理办法"
        response = {
            "status": "answerable",
            "evidence": [evidence_a],
            "module4_guidance": {"action": "answer", "may_generate_answer": True},
            "analysis": {"task_type": plan.task_type, "task_plan": plan.to_dict()},
            "diagnostics": {
                "multi_target": {
                    "task_plan": plan.to_dict(),
                    "retrieval_results": [
                        {"task_id": "OPT_A", "evidence": [evidence_a]},
                        {"task_id": "OPT_B", "evidence": []},
                    ],
                    "merged_evidence": [evidence_a],
                }
            },
        }

        result = generate_answer(
            plan.question,
            response,
            generator=lambda _question, _evidence: "答案：B。该选项符合规定。[E1]",
        )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(
            result["verification"]["option_verification"]["selected_options"],
            ["A"],
        )
        self.assertRegex(result["answer"], r"^答案：\*\*A\*\*")

    def test_metadata_question_uses_traceable_source_fields(self) -> None:
        evidence = [clause_evidence("商业银行应当建立资本管理制度。")]

        result = generate_answer("这份文件由谁发布，发布日期是什么？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertIn("国家金融监督管理总局", result["answer"])
        self.assertIn("2023-11-01", result["answer"])
        self.assertTrue(result["verification"]["passed"])

    def test_multiple_evidence_list_markers_are_not_numeric_claims(self) -> None:
        evidence = [
            clause_evidence("商业银行应当建立资本管理制度。", chunk_id="c1"),
            clause_evidence("商业银行应当持续监测资本充足率。", chunk_id="c2"),
        ]

        result = generate_answer("商业银行如何管理资本充足率？", evidence)

        self.assertEqual(result["status"], "answered")
        self.assertNotIn("1", extract_numeric_claims(result["answer"]))
        self.assertNotIn("2", extract_numeric_claims(result["answer"]))

    def test_document_number_and_institution_are_verified(self) -> None:
        evidence = [
            clause_evidence(
                "根据银保监规〔2023〕1号，中国人民银行与有关监管部门按职责开展工作。"
            )
        ]
        passed = verify_answer(
            "中国人民银行依据银保监规〔2023〕1号开展相关工作。[E1]",
            evidence,
        )
        failed = verify_answer("工商银行负责批准该事项。[E1]", evidence)

        self.assertTrue(passed["passed"])
        self.assertEqual(passed["document_no_claims"][0]["raw"], "银保监规〔2023〕1号")
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["unsupported_claims"][0]["kind"], "institution")

    def test_chinese_quarter_matches_q_period_in_evidence(self) -> None:
        evidence = [clause_evidence("资本充足率统计期间为2025Q3，数值为15.359%。")]

        result = verify_answer(
            "2025年第三季度商业银行资本充足率为15.359%。[E1]",
            evidence,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["unsupported_claims"], [])
        self.assertEqual(result["institution_claims"][0]["raw"], "商业银行")

    def test_numeric_claim_accepts_display_rounding(self) -> None:
        evidence = [clause_evidence("资本充足率统计期间为2025Q3，数值为15.359%。")]

        result = verify_answer(
            "2025年第三季度商业银行资本充足率为15.36%。[E1]",
            evidence,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["unsupported_claims"], [])

    def test_numeric_claim_rejects_wrong_display_rounding(self) -> None:
        evidence = [clause_evidence("资本充足率统计期间为2025Q3，数值为15.359%。")]

        result = verify_answer(
            "2025年第三季度商业银行资本充足率为15.37%。[E1]",
            evidence,
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["unsupported_claims"][0]["raw"], "15.37%")

    def test_prompt_contains_numbered_sources_and_output_contract(self) -> None:
        prompt = build_generation_prompt(
            "资本充足率最低要求是多少？",
            [clause_evidence("商业银行资本充足率不得低于8%。")],
        )

        self.assertIn("[E1]", prompt)
        self.assertIn("只能使用给定证据回答", prompt)
        self.assertIn('"status":"answered|refused"', prompt)
        self.assertIn("direct_answer MUST start with", prompt)
        self.assertIn("Answer: A,C", prompt)

    def test_verified_table_result_cannot_be_overridden_by_model(self) -> None:
        question = (
            "根据《测试表》，甲项减乙项是多少？"
            "A: 5 B: -5 C: 10 D: -10"
        )
        task_plan = {
            "task_type": "TABLE_CALCULATION",
            "source": {"file_name": "测试表", "sheet_name": "Sheet1"},
            "operation": "SUBTRACT",
            "operands": [
                {"name": "甲项", "row": "合计", "column": "甲项"},
                {"name": "乙项", "row": "合计", "column": "乙项"},
            ],
            "options": {"A": "5", "B": "-5", "C": "10", "D": "-10"},
            "need_clarification": False,
        }
        evidence = clause_evidence("测试表中甲项为10，乙项为5。")
        response = {
            "status": "answerable",
            "evidence": [evidence],
            "analysis": {"task_type": "TABLE_CALCULATION", "task_plan": task_plan},
            "module4_guidance": {"action": "answer", "may_generate_answer": True},
            "diagnostics": {},
        }

        from app.schemas.table_execution_schema import (
            TableExecutionResult,
            TableOperandResult,
        )

        verified = TableExecutionResult(
            status="SUCCESS",
            task_type="TABLE_CALCULATION",
            operation="SUBTRACT",
            operands=[
                TableOperandResult(name="甲项", value=10, verified=True),
                TableOperandResult(name="乙项", value=5, verified=True),
            ],
            result=-5,
            matched_option="B",
            explanation="乙项(5) - 甲项(10) = -5，对应选项 B。",
        )

        with patch("app.retrieval.table_executor.table_executor.execute", return_value=verified):
            result = generate_answer(
                question,
                response,
                generator=lambda _question, _evidence: "答案：C，结果为10。[E1]",
            )

        self.assertEqual(result["status"], "answered")
        self.assertIn("答案：**B. -5", result["answer"])
        self.assertNotIn("答案：C", result["answer"])
        self.assertEqual(result["verification"]["table_execution"]["matched_option"], "B")

    def test_verified_fact_choice_cannot_be_overridden_by_model(self) -> None:
        question = "根据《测试办法》，正确的是？A.应当备案 B.无需备案"
        task_plan = {
            "task_type": "FACT_SINGLE_CHOICE",
            "source_constraints": {"document_name": "测试办法"},
            "choice_mode": "SINGLE",
            "options": [
                {"label": "A", "claim": "应当备案"},
                {"label": "B", "claim": "无需备案"},
            ],
            "need_clarification": False,
        }
        response = {
            "status": "answerable",
            "evidence": [clause_evidence("《测试办法》规定，相关事项应当备案。")],
            "analysis": {"task_type": "FACT_SINGLE_CHOICE", "task_plan": task_plan},
            "module4_guidance": {"action": "answer", "may_generate_answer": True},
            "diagnostics": {},
        }

        from app.schemas.option_verification_schema import OptionVerificationResponse

        verified = OptionVerificationResponse(
            status="SUCCESS",
            choice_mode="SINGLE",
            question_intent_target="CORRECT",
            selected_options=["A"],
            explanation="选项 A 与证据中的‘应当备案’一致。",
        )

        with patch("app.retrieval.option_verifier.option_verifier.verify", return_value=verified):
            result = generate_answer(
                question,
                response,
                generator=lambda _question, _evidence: "答案：B，无需备案。[E1]",
            )

        self.assertEqual(result["status"], "answered")
        self.assertIn("答案：**A**", result["answer"])
        self.assertNotIn("答案：B", result["answer"])
        self.assertEqual(result["verification"]["option_verification"]["selected_options"], ["A"])

    def test_prompt_includes_deterministic_ratio_conversion(self) -> None:
        evidence = clause_evidence("资本充足率 | 2025Q3 | D44=0.15359")
        evidence["metadata"] = {
            "derived_values": [
                {
                    "kind": "ratio_to_percent",
                    "source_value": "0.15359",
                    "display_value": "15.359%",
                    "explanation": "保留原值 0.15359，按百分比展示为 15.359%。",
                }
            ]
        }

        prompt = build_generation_prompt("资本充足率百分比是多少？", [evidence])

        self.assertIn("确定性换算", prompt)
        self.assertIn("15.359%", prompt)
        self.assertIn("不得给原始存储值直接添加百分号", prompt)

    def test_full_retrieval_response_answerable_is_consumed(self) -> None:
        response = {
            "status": "answerable",
            "evidence": [clause_evidence("商业银行资本充足率不得低于8%。")],
            "module4_guidance": {
                "action": "answer",
                "may_generate_answer": True,
                "require_citations": True,
            },
            "diagnostics": {"failures": []},
        }

        result = generate_answer("资本充足率最低要求是多少？", response)

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["retrieval_status"], "answerable")
        self.assertEqual(result["module4_guidance"]["action"], "answer")

    def test_clarification_status_is_preserved_without_generation(self) -> None:
        response = {
            "status": "needs_clarification",
            "evidence": [],
            "module4_guidance": {
                "action": "clarify",
                "may_generate_answer": False,
                "clarification_question": "请选择财产险或人身险。",
                "clarification_options": ["财产险", "人身险"],
            },
            "diagnostics": {},
        }

        result = generate_answer("2025年保费收入是多少？", response)

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["clarification_options"], ["财产险", "人身险"])
        self.assertEqual(result["answer"], "请选择财产险或人身险。")

    def test_no_evidence_status_is_not_converted_to_clarification(self) -> None:
        response = {
            "status": "no_evidence",
            "evidence": [],
            "module4_guidance": {
                "action": "refuse",
                "may_generate_answer": False,
                "reason": "no_reliable_evidence",
            },
            "diagnostics": {},
        }

        result = generate_answer("不存在年份的指标是多少？", response)

        self.assertEqual(result["status"], "no_evidence")
        self.assertIn("no_reliable_evidence", result["refusal_reason"])
        self.assertNotIn("clarification_question", result)

    def test_degraded_status_adds_failure_warning(self) -> None:
        response = {
            "status": "degraded",
            "evidence": [clause_evidence("商业银行资本充足率不得低于8%。")],
            "module4_guidance": {
                "action": "answer_with_warning",
                "may_generate_answer": True,
            },
            "diagnostics": {
                "failures": [
                    {"stage": "retrieval", "component": "vector", "error_type": "RuntimeError"}
                ]
            },
        }

        result = generate_answer("资本充足率最低要求是多少？", response)

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(any("vector" in tip for tip in result["risk_tips"]))

    def test_incomplete_evidence_quality_is_refused(self) -> None:
        evidence = clause_evidence("商业银行资本充足率不得低于8%。")
        evidence["metadata"] = {
            "evidence_quality": {"complete": False, "missing_fields": ["source_url"]}
        }

        result = generate_answer("资本充足率最低要求是多少？", [evidence])

        self.assertEqual(result["status"], "refused")
        self.assertIn("来源字段不完整", result["refusal_reason"])

    def test_ratio_conversion_preserves_source_value(self) -> None:
        evidence = {
            "chunk_id": "table1",
            "chunk_type": "table",
            "score": 1.0,
            "text": "资本充足率 2025Q3 原值 0.15359",
            "source": {
                "doc_id": "doc101",
                "title": "监管统计指标",
                "sheet_name": "资本指标",
                "table_name": "主要监管指标",
                "cell_ref": "D44",
            },
            "metadata": {
                "metric_name": "资本充足率",
                "period": "2025Q3",
                "unit": "%",
                "value": "0.15359",
                "value_numeric": "0.153590000000000000",
                "evidence_quality": {"complete": True, "missing_fields": []},
            },
        }

        result = generate_answer("2025年三季度资本充足率百分比是多少？", [evidence])

        self.assertEqual(result["status"], "answered")
        self.assertIn("15.359%", result["answer"])
        self.assertIn("0.153590000000000000", result["answer"])
        derived = result["evidence"][0]["metadata"]["derived_values"][0]
        self.assertEqual(derived["source_value"], "0.153590000000000000")
        self.assertEqual(derived["display_value"], "15.359%")

    def test_api_uses_full_retrieval_response(self) -> None:
        response = {
            "status": "needs_clarification",
            "evidence": [],
            "module4_guidance": {
                "action": "clarify",
                "may_generate_answer": False,
                "clarification_question": "请补充具体指标。",
            },
            "diagnostics": {},
        }

        with patch(
            "app.api.main.retrieve", return_value=response
        ) as mocked_retrieve, patch(
            "app.api.main.deepseek_enabled", return_value=False
        ) as mocked_enabled:
            result = ask("2025年三季度是多少？")

        self.assertEqual(mocked_retrieve.call_args[0][0], "2025年三季度是多少？")
        mocked_enabled.assert_called_once_with()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["answer"], "请补充具体指标。")


if __name__ == "__main__":
    unittest.main()
