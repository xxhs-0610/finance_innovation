"""Deterministic compliance calculation engine using exact Decimal arithmetic."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.schemas.compliance_schema import DeterministicCalculation


class ComplianceCalculator:
    """Performs deterministic financial and regulatory ratio calculations."""

    @staticmethod
    def single_customer_concentration(
        loan_amount: Decimal,
        net_capital: Decimal,
        *,
        loan_str: str = "",
        net_capital_str: str = "",
    ) -> DeterministicCalculation:
        """Calculate single customer loan concentration (Statutory threshold <= 10%)."""
        if net_capital <= 0:
            raise ValueError("资本净额必须大于0")

        ratio = (loan_amount / net_capital).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        pct_value = ratio * Decimal("100")
        display_pct = f"{pct_value:.2f}%"
        threshold = Decimal("0.10")
        display_threshold = "≤ 10.00%"
        is_compliant = ratio <= threshold

        l_desc = loan_str or f"{loan_amount:,} 元"
        c_desc = net_capital_str or f"{net_capital:,} 元"
        formula = f"贷款金额（{l_desc}）÷ 资本净额（{c_desc}）"

        if is_compliant:
            explanation = f"计算得出单一客户贷款集中度为 {display_pct}，未超过法定监管上限 {display_threshold}，符合监管比例要求。"
        else:
            diff_pct = f"{(pct_value - Decimal('10.00')):.2f}%"
            explanation = f"计算得出单一客户贷款集中度为 {display_pct}，已超过法定监管上限 {display_threshold}（超标 {diff_pct}），违反大额风险暴露监管规定。"

        return DeterministicCalculation(
            formula=formula,
            computed_value=ratio,
            display_computed=display_pct,
            threshold_value=threshold,
            display_threshold=display_threshold,
            comparison_operator="<=",
            is_compliant=is_compliant,
            explanation=explanation,
        )

    @staticmethod
    def group_customer_concentration(
        credit_amount: Decimal,
        net_capital: Decimal,
        *,
        credit_str: str = "",
        net_capital_str: str = "",
    ) -> DeterministicCalculation:
        """Calculate group customer credit concentration (Statutory threshold <= 15%)."""
        if net_capital <= 0:
            raise ValueError("资本净额必须大于0")

        ratio = (credit_amount / net_capital).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        pct_value = ratio * Decimal("100")
        display_pct = f"{pct_value:.2f}%"
        threshold = Decimal("0.15")
        display_threshold = "≤ 15.00%"
        is_compliant = ratio <= threshold

        c_desc = credit_str or f"{credit_amount:,} 元"
        cap_desc = net_capital_str or f"{net_capital:,} 元"
        formula = f"授信总额（{c_desc}）÷ 资本净额（{cap_desc}）"

        if is_compliant:
            explanation = f"计算得出集团客户授信集中度为 {display_pct}，未超过法定监管上限 {display_threshold}，符合规定。"
        else:
            diff_pct = f"{(pct_value - Decimal('15.00')):.2f}%"
            explanation = f"计算得出集团客户授信集中度为 {display_pct}，超过法定监管上限 {display_threshold}（超标 {diff_pct}），不合规。"

        return DeterministicCalculation(
            formula=formula,
            computed_value=ratio,
            display_computed=display_pct,
            threshold_value=threshold,
            display_threshold=display_threshold,
            comparison_operator="<=",
            is_compliant=is_compliant,
            explanation=explanation,
        )

    @staticmethod
    def capital_adequacy_ratio(
        stated_ratio: Decimal,
        metric: str = "核心一级资本充足率",
        tier: str = "第一档商业银行",
    ) -> DeterministicCalculation:
        """Evaluate capital adequacy ratio against threshold."""
        pct_value = stated_ratio * Decimal("100")
        display_pct = f"{pct_value:.2f}%"

        if "第三档" in tier:
            threshold = Decimal("0.075")
            display_threshold = "≥ 7.50%"
            metric_name = "核心一级资本充足率（第三档）"
        elif "核心一级" in metric:
            threshold = Decimal("0.050")
            display_threshold = "≥ 5.00%"
            metric_name = "核心一级资本充足率最低要求"
        elif "一级资本" in metric:
            threshold = Decimal("0.060")
            display_threshold = "≥ 6.00%"
            metric_name = "一级资本充足率最低要求"
        else:
            threshold = Decimal("0.080")
            display_threshold = "≥ 8.00%"
            metric_name = "资本充足率最低要求"

        is_compliant = stated_ratio >= threshold
        formula = f"{metric_name}比对：实际 {display_pct} vs 法定底线 {display_threshold}"

        if is_compliant:
            explanation = f"实际指标为 {display_pct}，达到或高于法定最低监管要求 {display_threshold}，满足最低监管指标标准。"
        else:
            diff_pct = f"{(threshold * 100 - pct_value):.2f}%"
            explanation = f"实际指标为 {display_pct}，低于法定最低监管要求 {display_threshold}（资本缺口 {diff_pct}），不合规。"

        return DeterministicCalculation(
            formula=formula,
            computed_value=stated_ratio,
            display_computed=display_pct,
            threshold_value=threshold,
            display_threshold=display_threshold,
            comparison_operator=">=",
            is_compliant=is_compliant,
            explanation=explanation,
        )


compliance_calculator = ComplianceCalculator()
