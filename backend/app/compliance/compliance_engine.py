"""Compliance Judgment Engine.
Orchestrates: Scenario Extraction -> Rule Mapping -> Fact Gap Check -> Deterministic Math -> Structured Verdict.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.compliance.compliance_calculator import compliance_calculator
from app.compliance.fact_extractor import scenario_fact_extractor
from app.schemas.compliance_schema import (
    ComplianceJudgmentResult,
    DeterministicCalculation,
    ScenarioFacts,
)
from app.utils.logger import get_logger

logger = get_logger("app.compliance.engine")


class ComplianceEngine:
    """Rigorous compliance verification engine ensuring zero-hallucination factual deductions."""

    def evaluate(
        self,
        query: str,
        evidence: list[dict[str, Any]],
    ) -> ComplianceJudgmentResult:
        """Execute the complete compliance verification pipeline."""
        q = query.strip()
        logger.info(f"[ComplianceEngine] 启动合规判定链路: query='{q}'")

        # Step 1: 提取场景事实
        facts = scenario_fact_extractor.extract(q)
        logger.info(f"[ComplianceEngine] 提取场景事实完成: {facts.to_dict()}")

        # Step 2: 检查是否缺少决定合规性的关键事实
        is_ready, missing_fact, clarification_prompt = self._check_critical_fact_gap(facts, q)
        if not is_ready:
            logger.info(f"[ComplianceEngine] 缺失关键事实: {missing_fact} -> 触发 NEED_CLARIFICATION")
            return ComplianceJudgmentResult(
                is_ready=False,
                missing_critical_fact=missing_fact,
                clarification_prompt=clarification_prompt,
                judgment="UNABLE_TO_JUDGE",
                judgment_conclusion="【需补充关键事实】缺少判定合规性所需的必要前置数据。",
                scenario_facts_desc=self._build_facts_desc(facts),
                regulatory_rule="需结合具体监管指标规定（如资本净额比例上限）进行对照判定。",
                comparison_process=f"因缺少【{missing_fact}】，无法进行确定性数值核算与规则比对。",
                regulatory_basis="《中华人民共和国商业银行法》、《商业银行大额风险暴露管理办法》",
                citations=[],
            )

        # Step 3: 确定适用规则与执行确定性计算
        return self._execute_compliance_deduction(q, facts, evidence)

    def _check_critical_fact_gap(
        self,
        facts: ScenarioFacts,
        query: str,
    ) -> tuple[bool, str | None, str | None]:
        """Verify whether all critical factual parameters are present.
        Returns: (is_ready, missing_fact_name, targeted_clarification_prompt)
        """
        text = query.lower()

        # Case A: 贷款/授信集中度问题（有贷款金额，但缺少资本净额）
        is_concentration_query = any(
            w in query for w in ("单一客户", "大额风险暴露", "授信集中度", "贷款集中度", "单一企业", "某企业", "客户A", "企业A")
        ) or (facts.loan_amount is not None and not facts.is_related_party)

        if is_concentration_query:
            if facts.loan_amount is not None and facts.net_capital is None:
                missing = "商业银行资本净额（或一级资本净额）"
                prompt = (
                    "根据银行业监管规定（《商业银行法》第三十九条、《商业银行大额风险暴露管理办法》），"
                    "商业银行对单一客户的贷款余额不得超过资本净额的10%（对单一集团客户授信总额不得超过资本净额的15%）。\n"
                    "由于您未提供该商业银行的【资本净额】数值，系统无法计算集中度比例，请补充该银行的资本净额数值后再行判定。"
                )
                return False, missing, prompt

        # Case B: 资本充足率合规性判断（询问达标/合规，但未提供指标数值）
        if "资本充足率" in query and any(w in query for w in ("合规吗", "是否合规", "是否达标", "达标吗", "满足要求吗")):
            if facts.stated_ratio is None:
                missing = "实际资本充足率数值"
                prompt = (
                    "请补充该商业银行实际的核心一级资本充足率、一级资本充足率或资本充足率具体百分比数值，"
                    "以便对照现行监管底线标准进行确定性合规比对。"
                )
                return False, missing, prompt

        # Case C: 关系人贷款（若未指明是信用贷款还是担保贷款）
        if facts.is_related_party and facts.loan_amount is not None:
            if not facts.is_credit_loan and not any(w in query for w in ("信用", "担保", "抵押", "质押")):
                missing = "贷款担保方式（信用贷款还是担保/抵押贷款）"
                prompt = (
                    "《商业银行法》第四十条明确禁止向关系人发放【信用贷款】；若发放【担保贷款】，其条件不得优于其他借款人同类贷款。\n"
                    "请明确该笔向关系人发放的贷款属于信用贷款还是足额担保贷款，以便准确判定合规性。"
                )
                return False, missing, prompt

        return True, None, None

    def _execute_compliance_deduction(
        self,
        query: str,
        facts: ScenarioFacts,
        evidence: list[dict[str, Any]],
    ) -> ComplianceJudgmentResult:
        """Perform exact deterministic comparison and format the 5-section response."""
        citation_ids = [item.get("citation_id", "E1") for item in evidence] if evidence else ["E1"]
        primary_cite = citation_ids[0]

        # ---------------------------------------------------------------------
        # Type 1: 关系人信用贷款禁止性规定
        # ---------------------------------------------------------------------
        if facts.is_related_party and facts.is_credit_loan:
            rule = f"依据《中华人民共和国商业银行法》第四十条规定：“商业银行不得向关系人发放信用贷款。向关系人发放担保贷款的条件不得优于其他借款人同类贷款的条件。” [{primary_cite}]"
            facts_desc = (
                f"- 适用主体：{facts.institution_type or '商业银行'}\n"
                f"- 交易对象：{facts.counterparty or '本行关系人（董事/监事/管理人员/信贷人员及其近亲属）'}\n"
                f"- 业务类型：{facts.action_type or '信用贷款'}"
                + (f"（金额：{facts.loan_amount_str}）" if facts.loan_amount_str else "")
            )
            process = (
                "对比过程：\n"
                "1. 身份识别：借款人为商业银行关系人（董事/高管/股东等）；\n"
                "2. 业务性质：该笔贷款为无担保的【信用贷款】；\n"
                "3. 规则比对：法律设有明确禁止性条款，直接触发违规红线。"
            )
            conclusion = f"**违规（禁止办理）**。商业银行向关系人发放信用贷款直接违反《商业银行法》第四十条的强制禁止性规定。 [{primary_cite}]"
            basis = f"《中华人民共和国商业银行法》第四十条 [{primary_cite}]"

            return ComplianceJudgmentResult(
                is_ready=True,
                judgment="NON_COMPLIANT",
                regulatory_rule=rule,
                scenario_facts_desc=facts_desc,
                comparison_process=process,
                judgment_conclusion=conclusion,
                regulatory_basis=basis,
                citations=citation_ids[:1],
                rule_type="RELATED_PARTY_CREDIT_PROHIBITION",
            )

        # ---------------------------------------------------------------------
        # Type 2: 单一客户贷款集中度（确定性计算）
        # ---------------------------------------------------------------------
        if facts.loan_amount is not None and facts.net_capital is not None:
            calc = compliance_calculator.single_customer_concentration(
                facts.loan_amount,
                facts.net_capital,
                loan_str=facts.loan_amount_str or "",
                net_capital_str=facts.net_capital_str or "",
            )
            rule = (
                f"依据《中华人民共和国商业银行法》第三十九条第（四）项及《商业银行大额风险暴露管理办法》规定，"
                f"商业银行对单一客户的贷款余额与商业银行资本余额的比例不得超过 10%（{calc.display_threshold}）。 [{primary_cite}]"
            )
            facts_desc = (
                f"- 适用主体：{facts.institution_type or '商业银行'}\n"
                f"- 贷款对象：{facts.counterparty or '单一企业客户'}\n"
                f"- 拟发放贷款金额：{facts.loan_amount_str}\n"
                f"- 银行资本净额：{facts.net_capital_str}"
            )
            process = (
                f"确定性数学计算与比对：\n"
                f"1. 计算公式：单一客户贷款集中度 = 贷款金额 ÷ 资本净额\n"
                f"2. 确定性计算：{calc.formula} = **{calc.display_computed}**\n"
                f"3. 阈值比对：实际集中度 {calc.display_computed} vs 法定监管上限 {calc.display_threshold}\n"
                f"4. 判定分析：{calc.explanation}"
            )
            if calc.is_compliant:
                conclusion = f"**合规**。拟发放贷款金额占资本净额的比例为 {calc.display_computed}，未超过 10% 的法定监管上限要求。 [{primary_cite}]"
                verdict = "COMPLIANT"
            else:
                conclusion = f"**违规（超限额）**。拟发放贷款金额占资本净额的比例达到 {calc.display_computed}，已超过 10% 的法定监管上限要求。 [{primary_cite}]"
                verdict = "NON_COMPLIANT"

            basis = f"《中华人民共和国商业银行法》第三十九条、《商业银行大额风险暴露管理办法》 [{primary_cite}]"

            return ComplianceJudgmentResult(
                is_ready=True,
                judgment=verdict,
                regulatory_rule=rule,
                scenario_facts_desc=facts_desc,
                comparison_process=process,
                judgment_conclusion=conclusion,
                regulatory_basis=basis,
                citations=citation_ids[:1],
                calculation=calc,
                rule_type="SINGLE_CUSTOMER_LOAN_CONCENTRATION",
            )

        # ---------------------------------------------------------------------
        # Type 3: 资本充足率合规比对
        # ---------------------------------------------------------------------
        if facts.stated_ratio is not None:
            tier = facts.institution_type or "第一档商业银行"
            metric = "核心一级资本充足率" if "核心一级" in query else ("一级资本充足率" if "一级资本" in query else "资本充足率")
            calc = compliance_calculator.capital_adequacy_ratio(facts.stated_ratio, metric=metric, tier=tier)
            rule = (
                f"依据《商业银行资本管理办法》规定，{tier}{metric}不得低于 {calc.display_threshold}。 [{primary_cite}]"
            )
            facts_desc = (
                f"- 适用主体：{tier}\n"
                f"- 考核指标：{metric}\n"
                f"- 实际指标数值：{facts.stated_ratio_str}"
            )
            process = (
                f"确定性比对过程：\n"
                f"1. 监管底线：{metric}法定最低要求为 {calc.display_threshold}\n"
                f"2. 实际数值：{facts.stated_ratio_str}（{calc.display_computed}）\n"
                f"3. 比对结果：{calc.explanation}"
            )
            if calc.is_compliant:
                conclusion = f"**合规（达标）**。实际{metric}（{calc.display_computed}）满足或高于法定最低要求（{calc.display_threshold}）。 [{primary_cite}]"
                verdict = "COMPLIANT"
            else:
                conclusion = f"**不达标（不合规）**。实际{metric}（{calc.display_computed}）低于法定最低监管要求（{calc.display_threshold}）。 [{primary_cite}]"
                verdict = "NON_COMPLIANT"

            basis = f"《商业银行资本管理办法》（附件23/正文第二十三条） [{primary_cite}]"

            return ComplianceJudgmentResult(
                is_ready=True,
                judgment=verdict,
                regulatory_rule=rule,
                scenario_facts_desc=facts_desc,
                comparison_process=process,
                judgment_conclusion=conclusion,
                regulatory_basis=basis,
                citations=citation_ids[:1],
                calculation=calc,
                rule_type="CAPITAL_ADEQUACY_CHECK",
            )

        # ---------------------------------------------------------------------
        # Type 4: 通用合规场景规则提取与比对
        # ---------------------------------------------------------------------
        rule_text = evidence[0].get("text", "") if evidence else "相关银行业监管政策法规。"
        source = evidence[0].get("source", {}) if evidence else {}
        doc_title = source.get("title", "银行业监管制度")
        clause = source.get("clause_no", "相关条款")

        rule = f"依据《{doc_title}》{clause}规定：{rule_text[:120]}... [{primary_cite}]"
        facts_desc = f"- 涉及主体与业务行为：{query}"
        process = f"对照上述监管条款进行合规要件审查：核对业务主体资格、操作权限、授权审批及禁止性限制。"
        conclusion = f"依据检索到的监管制度条款 [{primary_cite}]，开展该业务需严格满足上述法定前置条件及合规要求。"
        basis = f"《{doc_title}》{clause} [{primary_cite}]"

        return ComplianceJudgmentResult(
            is_ready=True,
            judgment="CONDITIONAL",
            regulatory_rule=rule,
            scenario_facts_desc=facts_desc,
            comparison_process=process,
            judgment_conclusion=conclusion,
            regulatory_basis=basis,
            citations=citation_ids[:1],
            rule_type="GENERAL_COMPLIANCE",
        )

    def _build_facts_desc(self, facts: ScenarioFacts) -> str:
        items = []
        if facts.institution_type:
            items.append(f"适用主体：{facts.institution_type}")
        if facts.counterparty:
            items.append(f"交易对象：{facts.counterparty}")
        if facts.loan_amount_str:
            items.append(f"业务金额：{facts.loan_amount_str}")
        if facts.net_capital_str:
            items.append(f"资本净额：{facts.net_capital_str}")
        if facts.stated_ratio_str:
            items.append(f"指标比例：{facts.stated_ratio_str}")
        return "；".join(items) if items else "用户提问中所列场景事实"


compliance_engine = ComplianceEngine()
