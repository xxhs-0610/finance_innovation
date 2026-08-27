"""Schemas for Compliance Judgment Pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass
class ScenarioFacts:
    """Structured facts extracted from a user's compliance scenario."""
    institution_type: str | None = None          # 适用机构主体，如"商业银行"、"第一档商业银行"、"农商行"
    counterparty: str | None = None                # 交易对手/对象，如"单一客户A"、"某集团企业"、"本行董事"
    action_type: str | None = None                 # 业务行为，如"发放贷款"、"信用贷款"、"关联交易"、"股权投资"
    loan_amount: Decimal | None = None             # 贷款/授信/交易金额（标准单位：元）
    loan_amount_str: str | None = None             # 原始金额文本，如"5000万元"
    net_capital: Decimal | None = None             # 资本净额/一级资本净额（标准单位：元）
    net_capital_str: str | None = None             # 原始资本净额文本，如"10亿元"
    rwa: Decimal | None = None                     # 风险加权资产（标准单位：元）
    stated_ratio: Decimal | None = None            # 场景中给定的比例，如 Decimal("0.068") (6.8%)
    stated_ratio_str: str | None = None            # 原始比例文本，如"6.8%"
    is_credit_loan: bool = False                   # 是否为无担保的信用贷款
    is_related_party: bool = False                 # 是否涉及关联方/关系人
    time_period: str | None = None                 # 业务发生时间
    raw_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "institution_type": self.institution_type,
            "counterparty": self.counterparty,
            "action_type": self.action_type,
            "loan_amount_str": self.loan_amount_str,
            "net_capital_str": self.net_capital_str,
            "stated_ratio_str": self.stated_ratio_str,
            "is_credit_loan": self.is_credit_loan,
            "is_related_party": self.is_related_party,
            "time_period": self.time_period,
        }


@dataclass
class DeterministicCalculation:
    """Precise mathematical calculation completed deterministically by code."""
    formula: str                                   # 计算公式说明，如"5,000 万元 ÷ 10 亿元"
    computed_value: Decimal                        # 精确计算结果数值，如 Decimal("0.05")
    display_computed: str                          # 展示百分比，如"5.00%"
    threshold_value: Decimal                       # 监管法定阈值，如 Decimal("0.10")
    display_threshold: str                         # 展示法定阈值，如"≤ 10.00%"
    comparison_operator: str                       # 比较符，如"<=", ">="
    is_compliant: bool                             # 是否在法定阈值合规范围内
    explanation: str                               # 计算比对说明

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "computed_value": float(self.computed_value),
            "display_computed": self.display_computed,
            "display_threshold": self.display_threshold,
            "is_compliant": self.is_compliant,
            "explanation": self.explanation,
        }


@dataclass
class ComplianceJudgmentResult:
    """Final structured compliance verdict matching the 5 required sections."""
    is_ready: bool = True                          # False 表示缺少关键事实，需补充
    missing_critical_fact: str | None = None       # 缺失的关键事实名称，如"资本净额"
    clarification_prompt: str | None = None        # 反问用户的最小必要问题
    judgment: Literal["COMPLIANT", "NON_COMPLIANT", "CONDITIONAL", "UNABLE_TO_JUDGE"] = "UNABLE_TO_JUDGE"
    regulatory_rule: str = ""                      # 1. 监管规则
    scenario_facts_desc: str = ""                  # 2. 场景事实
    comparison_process: str = ""                   # 3. 对比过程（含确定性计算）
    judgment_conclusion: str = ""                  # 4. 判断结论
    regulatory_basis: str = ""                     # 5. 依据
    citations: list[str] = field(default_factory=list)
    calculation: DeterministicCalculation | None = None
    rule_type: str = "GENERAL_COMPLIANCE"

    def to_formatted_answer(self) -> str:
        """Render the exact 5-section response format."""
        return (
            f"【判断结论】\n{self.judgment_conclusion}\n\n"
            f"【监管规则】\n{self.regulatory_rule}\n\n"
            f"【场景事实】\n{self.scenario_facts_desc}\n\n"
            f"【对比过程】\n{self.comparison_process}\n\n"
            f"【依据】\n{self.regulatory_basis}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "missing_critical_fact": self.missing_critical_fact,
            "clarification_prompt": self.clarification_prompt,
            "judgment": self.judgment,
            "regulatory_rule": self.regulatory_rule,
            "scenario_facts_desc": self.scenario_facts_desc,
            "comparison_process": self.comparison_process,
            "judgment_conclusion": self.judgment_conclusion,
            "regulatory_basis": self.regulatory_basis,
            "citations": self.citations,
            "calculation": self.calculation.to_dict() if self.calculation else None,
            "rule_type": self.rule_type,
        }
