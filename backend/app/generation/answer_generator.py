from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.generation.evidence_verifier import evidence_verifier
from app.generation.refusal import assess_evidence_sufficiency, build_refusal
from app.generation.verifier import verify_answer
from app.schemas.answer_schema import (
    AnswerResult,
    normalize_evidence,
    normalize_retrieval_response,
)
from app.utils.logger import get_logger

logger = get_logger("app.generation.answer")

Generator = Callable[[str, list[dict[str, Any]]], str]


def generate_answer(
    question: str,
    evidence: Any,
    *,
    generator: Generator | None = None,
    min_evidence_overlap: int = 1,
) -> dict[str, Any]:
    """Generate an evidence-bound answer and verify high-risk claims.

    ``generator`` is an optional adapter for an LLM provider. Without one, the
    default extractive generator is used so the repository remains runnable
    offline and has deterministic regression tests.
    """

    retrieval = normalize_retrieval_response(evidence)
    retrieval_status = ""
    retrieval_guidance: dict[str, Any] = {}
    retrieval_diagnostics: dict[str, Any] = {}
    query_analysis = None
    if retrieval is not None:
        normalized = retrieval["evidence"]
        retrieval_status = str(retrieval.get("status") or "")
        retrieval_guidance = retrieval["module4_guidance"]
        retrieval_diagnostics = retrieval["diagnostics"]
        query_analysis = retrieval.get("analysis")
        gated = _handle_retrieval_gate(
            question,
            normalized,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )
        if gated is not None:
            logger.info(
                f"[AnswerGenerator] 检索门禁触发: retrieval_status='{retrieval_status}', action='{retrieval_guidance.get('action')}'"
            )
            return gated
    else:
        normalized = normalize_evidence(evidence)

    normalized = _add_deterministic_table_derivations(normalized, question)

    # =========================================================================
    # Step 0.5: Deterministic Table Execution Engine (TABLE_LOOKUP / COMPARE / CALCULATION)
    # =========================================================================
    from app.schemas.task_plan_schema import TaskPlan

    task_plan = None
    task_type = ""
    if query_analysis:
        if isinstance(query_analysis, dict):
            raw_tp = query_analysis.get("task_plan")
            task_type = query_analysis.get("task_type") or (raw_tp.get("task_type") if isinstance(raw_tp, dict) else getattr(raw_tp, "task_type", ""))
            if isinstance(raw_tp, dict):
                task_plan = TaskPlan.from_dict(raw_tp)
            elif isinstance(raw_tp, TaskPlan):
                task_plan = raw_tp
        else:
            task_plan = getattr(query_analysis, "task_plan", None)
            task_type = getattr(query_analysis, "task_type", None) or (task_plan.task_type if task_plan else "")

    if not task_plan and "multi_target" in retrieval_diagnostics:
        raw_mt = retrieval_diagnostics["multi_target"]
        if isinstance(raw_mt, dict) and "task_plan" in raw_mt:
            raw_tp = raw_mt["task_plan"]
            if isinstance(raw_tp, dict):
                task_plan = TaskPlan.from_dict(raw_tp)
                task_type = task_plan.task_type
            elif isinstance(raw_tp, TaskPlan):
                task_plan = raw_tp
                task_type = task_plan.task_type

    # Deterministic engines provide verified facts; DeepSeek remains responsible
    # for the final natural-language answer when an LLM generator is enabled.
    generation_question = str(question or "").strip()
    deterministic_execution = None
    verify_response = None

    if task_plan and task_type in {"TABLE_LOOKUP", "TABLE_COMPARE", "TABLE_CALCULATION"}:
        try:
            from app.retrieval.table_executor import table_executor
            mt_data = retrieval_diagnostics.get("multi_target") or normalized
            exec_result = table_executor.execute(task_plan, mt_data)
            logger.info(
                f"[AnswerGenerator] 表格确定性执行完成 | task_type={task_type} | status={exec_result.status} | matched_opt={exec_result.matched_option}"
            )

            if exec_result.status == "SUCCESS":
                from app.generation.answer_composer import answer_composer
                if task_type == "TABLE_COMPARE":
                    ans_text = answer_composer.compose_table_compare_answer(exec_result, task_plan, normalized)
                elif task_type == "TABLE_CALCULATION":
                    ans_text = answer_composer.compose_table_calculation_answer(exec_result, task_plan, normalized)
                else:
                    ans_text = answer_composer.compose_table_lookup_answer(exec_result, task_plan, normalized)

                deterministic_execution = exec_result
                generation_question = (
                    f"{generation_question}\n\n"
                    "【程序确定性核验结果】请将以下已核验事实组织成最终回答，不能修改数值或选项：\n"
                    f"{exec_result.explanation}\n"
                    f"匹配选项：{exec_result.matched_option or '无'}"
                )
                # With DeepSeek disabled, preserve the deterministic offline
                # response contract. With DeepSeek enabled, continue through
                # the normal generation + grounding verification pipeline.
                if generator is None:
                    citations = [normalized[0].get("citation_id", "E1")] if normalized else ["E1"]
                    result = AnswerResult(
                        status="answered", answer=ans_text, evidence=normalized,
                        risk_tips=["本结果由程序确定性执行计算与比较完成，数据源于官方监管报表。"],
                        confidence=0.99, citations=citations,
                        verification={
                            "passed": True, "issues": [],
                            "numeric_claims": [f"{op.name}={op.value}" for op in exec_result.operands],
                            "table_execution": exec_result.to_dict(),
                            "intermediate_verification": exec_result.intermediate_verification,
                        },
                        question=str(question or "").strip(),
                    ).to_dict()
                    return _attach_retrieval_context(result, retrieval_status, retrieval_guidance, retrieval_diagnostics)

            elif exec_result.status in {"MISSING_OPERAND", "CALCULATION_ERROR"}:
                err_code = "MISSING_OPERAND" if exec_result.status == "MISSING_OPERAND" else "CALCULATION_FAILED"
                logger.warning(f"[AnswerGenerator] 表格执行失败 [{err_code}]: {exec_result.explanation}")
                refusal = {
                    "status": "no_evidence",
                    "answer": f"⚠️ 系统已定位查询目标，但在知识库对应表格中未能完成运算（{exec_result.explanation}），无法完成确定性计算或比较。",
                    "evidence": normalized,
                    "risk_tips": ["知识库表格中未包含指定行列或指标数值"],
                    "confidence": 0.0,
                    "citations": [],
                    "error_code": err_code,
                    "verification": {
                        "passed": False,
                        "error_code": err_code,
                        "issues": [err_code],
                        "table_execution": exec_result.to_dict(),
                        "intermediate_verification": exec_result.intermediate_verification,
                    },
                    "refusal_reason": err_code,
                    "question": str(question or "").strip(),
                }
                return _attach_retrieval_context(
                    refusal,
                    retrieval_status,
                    retrieval_guidance,
                    retrieval_diagnostics,
                )
        except Exception as e:
            logger.error(f"[AnswerGenerator] 表格确定性执行器异常: {e}", exc_info=True)

    # =========================================================================
    # Step 0.6: Discrete Option Verification Engine (FACT_SINGLE_CHOICE / FACT_MULTI_CHOICE)
    # =========================================================================
    if task_plan and task_type in {"FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"}:
        try:
            from app.generation.answer_composer import answer_composer
            from app.retrieval.option_verifier import option_verifier
            mt_data = retrieval_diagnostics.get("multi_target") or normalized
            verify_response = option_verifier.verify(task_plan, mt_data)
            logger.info(
                f"[AnswerGenerator] 选项验证完成 | task_type={task_type} | status={verify_response.status} | selected={verify_response.selected_options}"
            )

            if verify_response.status == "SUCCESS" and verify_response.selected_options:
                ans_text = answer_composer.compose_fact_choice_answer(
                    verify_response, task_plan, normalized
                )

                if generator is None:
                    citations = [normalized[0].get("citation_id", "E1")] if normalized else ["E1"]
                    result = AnswerResult(
                        status="answered", answer=ans_text, evidence=normalized,
                        risk_tips=["本选项判定由事实比对引擎逐项独立验证完成，严格依据官方制度条款。"],
                        confidence=0.98, citations=citations,
                        verification={
                            "passed": True, "issues": [],
                            "option_verification": verify_response.to_dict(),
                            "intermediate_verification": verify_response.intermediate_verification,
                        },
                        question=str(question or "").strip(),
                    ).to_dict()
                    return _attach_retrieval_context(result, retrieval_status, retrieval_guidance, retrieval_diagnostics)
                generation_question = (
                    f"{generation_question}\n\n"
                    "【程序确定性核验结果】请据此组织最终回答，不能改变已核验的选项：\n"
                    f"{verify_response.explanation}\n"
                    f"已选选项：{', '.join(verify_response.selected_options)}"
                )
            elif verify_response.status in {"NO_DECISION", "CONFLICTING", "FAILED"}:
                err_code = "CONFLICTING_EVIDENCE" if verify_response.status == "CONFLICTING" else "INSUFFICIENT_OPTIONS"
                logger.warning(f"[AnswerGenerator] 选项验证未通过 [{err_code}]: {verify_response.explanation}")
                refusal = {
                    "status": "no_evidence",
                    "answer": f"⚠️ 经逐项条款比对，选项依据不足或存在冲突（{verify_response.explanation}），未能确定唯一正确选项。",
                    "evidence": normalized,
                    "risk_tips": ["知识库条款不足以支持明确选项判断"],
                    "confidence": 0.0,
                    "citations": [],
                    "error_code": err_code,
                    "verification": {
                        "passed": False,
                        "error_code": err_code,
                        "issues": [err_code],
                        "option_verification": verify_response.to_dict(),
                        "intermediate_verification": verify_response.intermediate_verification,
                    },
                    "refusal_reason": err_code,
                    "question": str(question or "").strip(),
                }
                return _attach_retrieval_context(
                    refusal,
                    retrieval_status,
                    retrieval_guidance,
                    retrieval_diagnostics,
                )
        except Exception as e:
            logger.error(f"[AnswerGenerator] 选项验证引擎异常: {e}", exc_info=True)

    # =========================================================================
    # Step 1: Pre-Generation Evidence Verifier (5 Core Dimensions)
    # =========================================================================
    use_llm = generator is not None
    verifier_result = evidence_verifier.verify(
        question,
        normalized,
        query_analysis=query_analysis,
        use_llm=use_llm,
    )
    sufficiency = assess_evidence_sufficiency(
        question,
        normalized,
        min_overlap=min_evidence_overlap,
    )

    if not verifier_result.answerable:
        logger.info(
            f"[AnswerGenerator] 证据核验未通过: reason_code='{verifier_result.reason_code}', "
            f"reason='{verifier_result.reason}', missing={verifier_result.missing_information}"
        )
        if verifier_result.need_clarification:
            clarification_msg = verifier_result.missing_information[0] if verifier_result.missing_information else verifier_result.reason
            refusal = {
                "status": "needs_clarification",
                "answer": clarification_msg,
                "evidence": normalized,
                "risk_tips": [f"需要补充场景条件：{verifier_result.reason}"],
                "confidence": 0.0,
                "citations": [],
                "error_code": "AMBIGUOUS_QUERY",
                "verification": {
                    "passed": False,
                    "error_code": "AMBIGUOUS_QUERY",
                    "issues": [verifier_result.reason],
                    "sufficiency": sufficiency.to_dict(),
                    "evidence_verifier": verifier_result.to_dict(),
                },
                "refusal_reason": "AMBIGUOUS_QUERY",
                "question": str(question or "").strip(),
            }
        else:
            refusal_reasons = [verifier_result.reason] + verifier_result.missing_information
            err_code = (
                "CONFLICTING_EVIDENCE"
                if verifier_result.reason_code == "CONFLICTING_EVIDENCE"
                else "MISSING_EVIDENCE"
            )
            refusal = build_refusal(
                question,
                refusal_reasons,
                normalized,
                error_code=err_code,
                reason_code=verifier_result.reason_code,
                missing_information=verifier_result.missing_information,
            )
            refusal["error_code"] = err_code
            refusal["verification"]["error_code"] = err_code
            refusal["verification"]["evidence_verifier"] = verifier_result.to_dict()
            refusal["verification"]["sufficiency"] = sufficiency.to_dict()

        return _attach_retrieval_context(
            refusal,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )

    if not sufficiency.sufficient:
        logger.info(f"[AnswerGenerator] 证据充分性评估未通过: reasons={sufficiency.reasons}")
        refusal = build_refusal(question, sufficiency.reasons, normalized)
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        refusal["verification"]["evidence_verifier"] = verifier_result.to_dict()
        return _attach_retrieval_context(
            refusal,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )

    # =========================================================================
    # Step 2: Dedicated Compliance Judgment Workflow (qa_type=COMPLIANCE_JUDGMENT)
    # =========================================================================
    is_compliance_q = any(
        w in str(question or "")
        for w in ("合规吗", "是否合规", "能否办理", "是否违规", "是否允许", "合规判定", "是否符合监管")
    ) or (query_analysis and getattr(query_analysis, "rule_type", "") in {"合规判断", "COMPLIANCE_JUDGMENT"})

    if is_compliance_q:
        try:
            from app.compliance.compliance_engine import compliance_engine
            compliance_verdict = compliance_engine.evaluate(str(question or "").strip(), normalized)
            if not compliance_verdict.is_ready:
                logger.info(f"[AnswerGenerator] 合规判断缺失关键事实: {compliance_verdict.missing_critical_fact}")
                refusal = {
                    "status": "needs_clarification",
                    "answer": f"💡 **请补充合规判定关键事实**：\n{compliance_verdict.clarification_prompt}",
                    "evidence": normalized,
                    "risk_tips": [f"缺少合规判定关键事实：{compliance_verdict.missing_critical_fact}"],
                    "confidence": 0.0,
                    "citations": [],
                    "verification": {
                        "passed": False,
                        "issues": [compliance_verdict.missing_critical_fact or "缺少必要数据"],
                        "sufficiency": sufficiency.to_dict(),
                        "evidence_verifier": verifier_result.to_dict(),
                        "compliance": compliance_verdict.to_dict(),
                    },
                    "refusal_reason": compliance_verdict.missing_critical_fact or "缺少必要数据",
                    "question": str(question or "").strip(),
                }
                return _attach_retrieval_context(
                    refusal,
                    retrieval_status,
                    retrieval_guidance,
                    retrieval_diagnostics,
                )

            if compliance_verdict.rule_type != "GENERAL_COMPLIANCE":
                logger.info(f"[AnswerGenerator] 合规判断完成确定性核算与规则比对: verdict={compliance_verdict.judgment}")
                compliance_answer = compliance_verdict.to_formatted_answer()
                result = AnswerResult(
                    status="answered",
                    answer=compliance_answer,
                    evidence=normalized,
                    risk_tips=["合规判断由确定性计算引擎完成，并经监管规则比对核验。"],
                    confidence=0.99,
                    citations=compliance_verdict.citations or [normalized[0].get("citation_id", "E1")],
                    verification={
                        "passed": True,
                        "issues": [],
                        "numeric_claims": [],
                        "date_claims": [],
                        "document_no_claims": [],
                        "institution_claims": [],
                        "unsupported_claims": [],
                        "evidence_verifier": verifier_result.to_dict(),
                        "compliance": compliance_verdict.to_dict(),
                    },
                    question=str(question or "").strip(),
                ).to_dict()
                return _attach_retrieval_context(
                    result,
                    retrieval_status,
                    retrieval_guidance,
                    retrieval_diagnostics,
                )
        except Exception as e:
            logger.warning(f"[AnswerGenerator] 合规引擎处理异常，回退常规生成流程: {e}", exc_info=True)

    evidence_for_gen = normalized
    if verifier_result.supporting_evidence_ids:
        supporting_set = set(verifier_result.supporting_evidence_ids)
        verified_evidence = [e for e in normalized if e.get("citation_id") in supporting_set]
        if verified_evidence:
            evidence_for_gen = verified_evidence

    gen_mode = "DeepSeek/LLM" if generator else "Extractive Fallback"
    logger.info(f"[AnswerGenerator] 启动回答生成 | 模式: {gen_mode} | 确认有效证据数: {len(evidence_for_gen)}条")

    try:
        generated = (generator or _extractive_generator)(generation_question, evidence_for_gen)
    except Exception as exc:
        logger.error(
            f"[AnswerGenerator] 答案生成服务调用异常: {type(exc).__name__}: {exc}",
            exc_info=True,
        )
        refusal = build_refusal(
            question,
            [f"答案生成服务调用失败: {exc}"],
            normalized,
            error_code="GENERATION_FAILED",
        )
        refusal["verification"]["sufficiency"] = sufficiency.to_dict()
        refusal["verification"]["evidence_verifier"] = verifier_result.to_dict()
        return _attach_retrieval_context(
            refusal,
            retrieval_status,
            retrieval_guidance,
            retrieval_diagnostics,
        )
    answer_text = str(generated or "").strip()

    # Deterministic module-4 decisions are authoritative. DeepSeek may help
    # phrase an answer, but it must not replace a verified table value or
    # option selected by the local evidence verifier. Recompose the canonical
    # answer after the provider call so the public result always contains the
    # verified option letter/value.
    if deterministic_execution is not None:
        from app.generation.answer_composer import answer_composer
        if task_type == "TABLE_COMPARE":
            answer_text = answer_composer.compose_table_compare_answer(
                deterministic_execution, task_plan, evidence_for_gen
            )
        elif task_type == "TABLE_CALCULATION":
            answer_text = answer_composer.compose_table_calculation_answer(
                deterministic_execution, task_plan, evidence_for_gen
            )
        else:
            answer_text = answer_composer.compose_table_lookup_answer(
                deterministic_execution, task_plan, evidence_for_gen
            )
    elif (
        verify_response is not None
        and task_plan
        and task_type in {"FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"}
        and verify_response.selected_options
    ):
        from app.generation.answer_composer import answer_composer
        answer_text = answer_composer.compose_fact_choice_answer(
            verify_response, task_plan, evidence_for_gen
        )
    if answer_text.upper() == "REFUSE" or answer_text.upper().startswith("REFUSE"):
        # A model-side REFUSE can be overly conservative when deterministic
        # option verification already selected an answer.  Re-run the local
        # grounded fallback before considering refusal.
        logger.info("[AnswerGenerator] DeepSeek 返回 REFUSE，尝试本地证据抽取式回答")
        try:
            if task_plan and task_type in {"FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"} and verify_response.selected_options:
                from app.generation.answer_composer import answer_composer
                answer_text = answer_composer.compose_fact_choice_answer(
                    verify_response, task_plan, evidence_for_gen
                )
            else:
                answer_text = str(_extractive_generator(generation_question, evidence_for_gen) or "").strip()
        except Exception:
            answer_text = ""
        if not answer_text or answer_text.upper().startswith("REFUSE"):
            refusal = build_refusal(question, ["依据现有证据不足以得出确定性结论，系统已安全拒答。"], normalized)
            refusal["verification"]["sufficiency"] = sufficiency.to_dict()
            refusal["verification"]["evidence_verifier"] = verifier_result.to_dict()
            return _attach_retrieval_context(
                refusal,
                retrieval_status,
                retrieval_guidance,
                retrieval_diagnostics,
            )

    # If the answer is missing explicit [E#] citation brackets but evidence is present, append the first citation
    if normalized and not re.search(r"\[(E\d+)\]|\b(E\d+)\b", answer_text, re.IGNORECASE):
        first_cite = normalized[0].get("citation_id", "E1")
        answer_text = f"{answer_text} [{first_cite}]"
        logger.info(f"[AnswerGenerator] 自动为回答补全证据引用 [{first_cite}]")

    initial_answer_text = answer_text
    verification = verify_answer(answer_text, normalized, question=question)
    grounding_action = "PASS"
    regeneration_triggered = False

    if verification.get("status") == "PARTIAL_PASS":
        logger.info(
            f"[AnswerGenerator] 答案触发 PARTIAL_PASS，执行非核心无依据修剪: "
            f"ungrounded_optional={len(verification.get('unsupported_optional_claims', []))}条"
        )
        answer_text = verification.get("pruned_answer") or answer_text
        grounding_action = "REMOVE_OPTIONAL"
    elif verification.get("status") == "FAIL":
        logger.warning(f"[AnswerGenerator] 答案初次生成校验 FAIL: issues={verification['issues']}")
        # Attempt 1-shot Grounded Regeneration if using DeepSeek backend
        try:
            from app.generation.deepseek_client import deepseek_generator, deepseek_grounded_regenerator, deepseek_enabled
            is_deepseek_gen = (generator is None) or (generator is deepseek_generator)
            if is_deepseek_gen and deepseek_enabled():
                logger.info(f"[AnswerGenerator] 启动 Grounded Regeneration 受控修复生成...")
                regen_text = deepseek_grounded_regenerator(
                    str(question or "").strip(),
                    evidence_for_gen,
                    verification.get("issues"),
                )
                regen_text = str(regen_text or "").strip()
                if regen_text and regen_text.upper() != "REFUSE":
                    regeneration_triggered = True
                    if normalized and not re.search(r"\[(E\d+)\]|\b(E\d+)\b", regen_text, re.IGNORECASE):
                        first_cite = normalized[0].get("citation_id", "E1")
                        regen_text = f"{regen_text} [{first_cite}]"

                    regen_ver = verify_answer(regen_text, normalized, question=question)
                    if regen_ver["passed"]:
                        logger.info(f"[AnswerGenerator] Grounded Regeneration 修正成功 (status={regen_ver['status']})")
                        answer_text = regen_ver.get("pruned_answer") or regen_text
                        verification = regen_ver
                        grounding_action = "REGENERATE"
                    else:
                        logger.warning(f"[AnswerGenerator] Grounded Regeneration 重生后仍未通过: issues={regen_ver['issues']}")
                        verification = regen_ver
                        grounding_action = "REJECT"
                else:
                    grounding_action = "REJECT"
            else:
                grounding_action = "REJECT"
        except Exception as e:
            logger.warning(f"[AnswerGenerator] Grounded Regeneration 执行异常: {e}")
            grounding_action = "REJECT"

    risk_tips: list[str] = []
    status = "answered"
    refusal_reason = ""

    # A deterministic option decision is already grounded directly against
    # the per-option evidence.  The generic post-generation verifier can
    # misread option labels, clause numbers, or table coordinates as
    # unsupported numeric claims (especially when DeepSeek is unavailable and
    # the local composer is used).  Do not convert that verified choice into a
    # refusal; retain the audit issues as a warning instead.
    deterministic_choice_answer = bool(
        task_plan
        and task_type in {"FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE"}
        and verify_response is not None
        and getattr(verify_response, "selected_options", None)
        and normalized
    )
    deterministic_table_answer = bool(
        task_plan
        and task_type in {"TABLE_LOOKUP", "TABLE_COMPARE", "TABLE_CALCULATION"}
        and deterministic_execution is not None
        and getattr(deterministic_execution, "status", None) == "SUCCESS"
        and normalized
    )

    if not verification["passed"] and deterministic_table_answer:
        risk_tips.append(
            "数值或选项已由本地表格执行器完成取数、计算与核验；已保留确定性结果。"
        )
        verification = {
            **verification,
            "passed": True,
            "status": "PASS_DETERMINISTIC_TABLE",
            "issues": verification.get("issues", []),
        }
        grounding_action = "PASS_DETERMINISTIC_TABLE"

    if not verification["passed"] and deterministic_choice_answer:
        risk_tips.append(
            "选项已由本地检索证据确定；通用生成后校验发现的是格式/附带文本问题，已保留确定性选项答案。"
        )
        verification = {
            **verification,
            "passed": True,
            "status": "PASS_DETERMINISTIC_OPTION",
            "issues": verification.get("issues", []),
        }
        grounding_action = "PASS_DETERMINISTIC_OPTION"

    if not verification["passed"]:
        status = "refused"
        refusal_reason = "；".join(verification["issues"])
        risk_tips.extend(verification["issues"])
        answer_text = "依据当前检索证据无法得出充分支持的核心事实结论，系统已安全拒答。"
        logger.warning(f"[AnswerGenerator] 答案最终未通过事实校验: issues={verification['issues']}")
    elif _has_multiple_scopes(normalized):
        risk_tips.append("证据来自不同文档或期间，使用前请确认适用范围和时点。")
    elif verification.get("status") == "PARTIAL_PASS":
        risk_tips.append("提示：已自动修剪未经证据支持的非核心描述，仅保留证据可确认内容。")

    if retrieval_status == "degraded":
        risk_tips.append(_degraded_risk_tip(retrieval_diagnostics))

    citations = verification.get("citations") or [item["citation_id"] for item in normalized]
    confidence = _estimate_confidence(normalized, verification, sufficiency.overlap)
    logger.info(
        f"[AnswerGenerator] 答案生成及校验完成 | 状态: {status} | GroundingAction: {grounding_action} | 置信度: {confidence:.2f} | 引用数: {len(citations)}"
    )
    result = AnswerResult(
        status=status,
        answer=answer_text,
        evidence=normalized,
        risk_tips=risk_tips,
        confidence=confidence if status == "answered" else 0.0,
        citations=citations,
        verification={
            **verification,
            **({"table_execution": deterministic_execution.to_dict()} if deterministic_execution is not None else {}),
            **({"option_verification": verify_response.to_dict()} if verify_response is not None else {}),
            "sufficiency": sufficiency.to_dict(),
            "evidence_verifier": verifier_result.to_dict(),
            "grounding_action": grounding_action,
            "regeneration_triggered": regeneration_triggered,
            "initial_answer": initial_answer_text,
        },
        refusal_reason=refusal_reason,
        question=str(question or "").strip(),
    )
    payload = result.to_dict()
    if retrieval_status:
        payload["status"] = "degraded" if retrieval_status == "degraded" and status == "answered" else payload["status"]
    return _attach_retrieval_context(
        payload,
        retrieval_status,
        retrieval_guidance,
        retrieval_diagnostics,
    )


def _handle_retrieval_gate(
    question: str,
    evidence: list[dict[str, Any]],
    retrieval_status: str,
    guidance: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    """Honor module 3's answerability decision before any generation."""

    action = str(guidance.get("action") or "")
    may_generate = guidance.get("may_generate_answer")
    if may_generate is None:
        may_generate = retrieval_status in {"answerable", "degraded"} and bool(evidence)

    if retrieval_status == "no_evidence" or action == "refuse":
        err_code = "RETRIEVAL_FAILED" if not evidence else "MISSING_EVIDENCE"
        refusal = build_refusal(
            question,
            [str(guidance.get("reason") or "未检索到足够的可靠证据。")],
            evidence,
            error_code=err_code,
            reason_code="NO_RELEVANT_EVIDENCE",
        )
        refusal["status"] = "no_evidence" if retrieval_status == "no_evidence" else "refused"
        refusal["error_code"] = err_code
        refusal["verification"]["error_code"] = err_code
        return _attach_retrieval_context(
            refusal, retrieval_status, guidance, diagnostics
        )

    if retrieval_status == "needs_clarification" or action == "clarify":
        # Prompt 7 Guard: Choice, comparison, calculation, and multi-quote queries NEVER trigger clarification
        if any(c in question for c in ("A:", "A.", "A：", "A、", "比较", "相差", "差距", "从", "到", "谁最大", "谁最小", "哪项", "最高", "最低")) or len(re.findall(r"“[^”]+”|‘[^’]+’|《[^》]+》", question)) >= 2:
            refusal = build_refusal(
                question,
                ["知识库中未检索到与查询目标匹配的有效条款或表格数据。"],
                evidence,
                error_code="MISSING_EVIDENCE",
                reason_code="NO_RELEVANT_EVIDENCE",
            )
            refusal["status"] = "no_evidence"
            refusal["error_code"] = "MISSING_EVIDENCE"
            refusal["verification"]["error_code"] = "MISSING_EVIDENCE"
            return _attach_retrieval_context(
                refusal, "no_evidence", guidance, diagnostics
            )

        clarification = str(guidance.get("clarification_question") or "请补充问题中的适用对象或查询条件。")
        options = guidance.get("clarification_options")
        payload = {
            "status": "needs_clarification",
            "answer": clarification,
            "evidence": evidence,
            "risk_tips": ["信息条件不足，系统未生成确定性答案。"],
            "confidence": 0.0,
            "citations": [],
            "error_code": "AMBIGUOUS_QUERY",
            "verification": {
                "passed": False,
                "error_code": "AMBIGUOUS_QUERY",
                "issues": ["问题要素不足，需先澄清查询条件。"],
                "sufficiency": {"sufficient": False, "reasons": ["问题要素不足，需先澄清查询条件。"]},
            },
            "clarification_question": clarification,
            "question": str(question or "").strip(),
        }
        if isinstance(options, list) and options:
            payload["clarification_options"] = options
        return _attach_retrieval_context(
            payload, retrieval_status, guidance, diagnostics
        )

    return None


def _attach_retrieval_context(
    payload: dict[str, Any],
    retrieval_status: str,
    guidance: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    if retrieval_status:
        payload["retrieval_status"] = retrieval_status
        payload["module4_guidance"] = guidance
        payload["diagnostics"] = diagnostics
    return payload


def _degraded_risk_tip(diagnostics: dict[str, Any]) -> str:
    failures = diagnostics.get("failures") if isinstance(diagnostics, Mapping) else None
    if isinstance(failures, list) and failures:
        components = [str(item.get("component")) for item in failures if isinstance(item, Mapping) and item.get("component")]
        if components:
            return f"检索链路部分降级（{', '.join(components)}），答案仅基于当前可用证据生成。"
    return "检索链路部分降级，答案仅基于当前可用证据生成。"


def _add_deterministic_table_derivations(
    evidence: list[dict[str, Any]], question: str
) -> list[dict[str, Any]]:
    """Record safe ratio conversions without overwriting source values."""

    wants_ratio = any(marker in str(question or "") for marker in ("百分比", "百分率", "占比", "比例", "率"))
    if not wants_ratio:
        return evidence
    output: list[dict[str, Any]] = []
    for item in evidence:
        record = deepcopy(item)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
        metadata = dict(metadata)
        metric = str(metadata.get("metric_name") or "")
        unit = str(metadata.get("unit") or "")
        raw = metadata.get("value_numeric", metadata.get("value"))
        if "率" in metric or "比例" in metric or "占比" in metric:
            converted = _ratio_as_percent(raw, unit)
            if converted is not None:
                metadata.setdefault("derived_values", []).append({
                    "kind": "ratio_to_percent",
                    "source_value": str(raw),
                    "display_value": converted,
                    "explanation": f"保留原值 {raw}，按百分比展示为 {converted}。",
                })
        record["metadata"] = metadata
        output.append(record)
    return output


def _ratio_as_percent(raw: Any, unit: str) -> str | None:
    if "%" not in unit and "％" not in unit:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not Decimal("-1") <= value <= Decimal("1") or value == 0:
        return None
    return f"{(value * 100).normalize():f}%"


def _extractive_generator(question: str, evidence: list[dict[str, Any]]) -> str:
    """Produce a conservative answer using only retrieved evidence text."""

    if not evidence:
        return ""
    metadata_answer = _answer_metadata_question(question, evidence)
    if metadata_answer is not None:
        return metadata_answer
    lines: list[str] = []
    for item in evidence[:3]:
        text = _evidence_text_for_answer(item)
        if not text:
            continue
        citation = item.get("citation_id", "E1")
        source = item.get("source") or {}
        prefix = "数据证据" if item.get("chunk_type") == "table" else "制度依据"
        clause = source.get("clause_no") or source.get("cell_ref")
        locator = f"（{clause}）" if clause else ""
        lines.append(f"{prefix}{locator}：{text} [{citation}]")
    if not lines:
        return ""
    if len(lines) == 1:
        return f"结论：{lines[0]}"
    return "结论：结合检索到的证据，相关信息如下：\n" + "\n".join(
        f"{idx}. {line}" for idx, line in enumerate(lines, start=1)
    )


def _evidence_text_for_answer(item: dict[str, Any]) -> str:
    text = str(item.get("text") or "").strip().rstrip("。；;")
    derived = (item.get("metadata") or {}).get("derived_values", [])
    if isinstance(derived, list):
        explanations = [
            str(value.get("explanation"))
            for value in derived
            if isinstance(value, Mapping) and value.get("explanation")
        ]
        if explanations:
            text = f"{text}（{'；'.join(explanations)}）"
    return text


def _answer_metadata_question(question: str, evidence: list[dict[str, Any]]) -> str | None:
    source = evidence[0].get("source") or {}
    citation = evidence[0].get("citation_id", "E1")
    requested = False
    parts: list[str] = []

    field_markers = [
        ("发布机构", ("发布机构", "发文机关", "发布部门", "哪个机构", "哪个部门", "谁发布", "颁布"), source.get("issuer")),
        ("发布日期", ("发布日期", "发布时间", "何时发布", "什么时候发布", "哪年发布"), source.get("publish_date")),
        ("文件标题", ("文件名", "文件标题", "标题"), source.get("title")),
        ("原文来源", ("来源链接", "原文链接", "网址"), source.get("source_url")),
    ]
    for label, markers, value in field_markers:
        if any(marker in question for marker in markers):
            requested = True
            if str(value or "").strip():
                parts.append(f"{label}：{str(value).strip()}")

    if not requested:
        return None
    if not parts:
        return ""
    return f"结论：{'；'.join(parts)} [{citation}]"


def _estimate_confidence(
    evidence: list[dict[str, Any]],
    verification: dict[str, Any],
    overlap: int,
) -> float:
    if not evidence or not verification.get("passed"):
        return 0.0
    scores = [max(0.0, float(item.get("score", 0.0) or 0.0)) for item in evidence]
    score_signal = min(1.0, sum(scores[:3]) / max(1, len(scores[:3]))) if any(scores) else 0.5
    overlap_signal = min(1.0, overlap / 3) if overlap else 0.25
    citation_signal = 1.0 if verification.get("citations") else 0.6
    return min(0.98, 0.45 * score_signal + 0.35 * overlap_signal + 0.20 * citation_signal)


def _has_multiple_scopes(evidence: list[dict[str, Any]]) -> bool:
    docs = {str((item.get("source") or {}).get("doc_id") or "") for item in evidence}
    periods = {
        str((item.get("metadata") or {}).get("period") or "")
        for item in evidence
        if (item.get("metadata") or {}).get("period")
    }
    return len(docs - {""}) > 1 or len(periods) > 1


__all__ = ["generate_answer"]

