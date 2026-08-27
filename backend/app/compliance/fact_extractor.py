"""Extract structured scenario facts from compliance queries."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.compliance_schema import ScenarioFacts


# Regular expressions for parsing Chinese currency and percentage amounts
NET_CAPITAL_RE = re.compile(
    r"(?:资本净额|一级资本净额|核心一级资本净额|资本余额)(?:为|达到|是|有)?\s*([0-9]+(?:\.[0-9]+)?)\s*(万|亿|万元|亿元|元)?",
    re.IGNORECASE,
)

LOAN_AMOUNT_RE = re.compile(
    r"(?:发放|提供|申请|办理)?(?:贷款|授信|融资金额|借款|授信额度|贷款金额|敞口)(?:为|达|是|有)?\s*([0-9]+(?:\.[0-9]+)?)\s*(万|亿|万元|亿元|元)?",
    re.IGNORECASE,
)

GENERIC_AMOUNT_RE = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)\s*(万|亿|万元|亿元)",
    re.IGNORECASE,
)

RATIO_RE = re.compile(
    r"(?:资本充足率|核心一级资本充足率|一级资本充足率|不良贷款率|拨备覆盖率|集中度|比例)(?:为|达到|是|有)?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE,
)

INSTITUTION_KEYWORDS = [
    "第一档商业银行",
    "第二档商业银行",
    "第三档商业银行",
    "大型商业银行",
    "国有商业银行",
    "全国性股份制商业银行",
    "城市商业银行",
    "农村商业银行",
    "村镇银行",
    "外资银行",
    "金融租赁公司",
    "信托公司",
    "商业银行",
]

RELATED_PARTY_KEYWORDS = [
    "关系人",
    "关联方",
    "关联企业",
    "关联自然人",
    "本行董事",
    "本行监事",
    "管理人员",
    "信贷业务人员",
    "主要股东",
    "控股股东",
]

CREDIT_LOAN_KEYWORDS = [
    "信用贷款",
    "无担保贷款",
    "信用方式",
    "无抵押",
]


def parse_chinese_money(num_str: str, unit_str: str | None) -> Decimal | None:
    """Parse a number string and unit ('万', '亿', etc.) into standard Yuan (元)."""
    try:
        val = Decimal(num_str)
    except (InvalidOperation, TypeError):
        return None

    unit = (unit_str or "").strip()
    if "亿" in unit:
        return val * Decimal("100000000")
    elif "万" in unit:
        return val * Decimal("10000")
    else:
        return val


class ScenarioFactExtractor:
    """Extracts business facts from compliance inquiry queries."""

    def extract(self, query: str) -> ScenarioFacts:
        text = query.strip()
        facts = ScenarioFacts(raw_query=text)

        # 1. Institution Type
        for inst in INSTITUTION_KEYWORDS:
            if inst in text:
                facts.institution_type = inst
                break
        if not facts.institution_type and "银行" in text:
            facts.institution_type = "商业银行"

        # 2. Related Party / Credit Loan markers
        for rp in RELATED_PARTY_KEYWORDS:
            if rp in text:
                facts.is_related_party = True
                facts.counterparty = rp
                break

        for cl in CREDIT_LOAN_KEYWORDS:
            if cl in text:
                facts.is_credit_loan = True
                facts.action_type = "信用贷款"
                break

        if not facts.action_type:
            if "贷款" in text:
                facts.action_type = "发放贷款"
            elif "授信" in text:
                facts.action_type = "提供授信"
            elif "投资" in text:
                facts.action_type = "投资业务"
            elif "资本充足率" in text:
                facts.action_type = "资本充足率核算"

        # 3. Counterparty
        if not facts.counterparty:
            m_cp = re.search(r"向\s*([^，,。]+?)(?:发放|提供|申请|办理)?(?:贷款|授信|融资)", text)
            if m_cp:
                facts.counterparty = m_cp.group(1).strip()
            elif "单一客户" in text or "单一企业" in text:
                facts.counterparty = "单一客户"
            elif "集团客户" in text or "单一集团" in text:
                facts.counterparty = "单一集团客户"

        # 4. Net Capital
        m_nc = NET_CAPITAL_RE.search(text)
        if m_nc:
            num, unit = m_nc.group(1), m_nc.group(2)
            facts.net_capital = parse_chinese_money(num, unit)
            facts.net_capital_str = f"{num}{unit or '元'}"

        # 5. Loan / Transaction Amount
        m_la = LOAN_AMOUNT_RE.search(text)
        if m_la:
            num, unit = m_la.group(1), m_la.group(2)
            facts.loan_amount = parse_chinese_money(num, unit)
            facts.loan_amount_str = f"{num}{unit or '元'}"
        else:
            # Fallback to search any generic money amounts not already captured by net capital
            amounts = list(GENERIC_AMOUNT_RE.finditer(text))
            for m in amounts:
                num, unit = m.group(1), m.group(2)
                raw_token = f"{num}{unit}"
                if facts.net_capital_str and raw_token in facts.net_capital_str:
                    continue
                facts.loan_amount = parse_chinese_money(num, unit)
                facts.loan_amount_str = raw_token
                break

        # 6. Stated Ratio (e.g. 资本充足率为 8.5% 或 4.8%)
        m_ratio = RATIO_RE.search(text)
        if m_ratio:
            ratio_val = Decimal(m_ratio.group(1)) / Decimal("100")
            facts.stated_ratio = ratio_val
            facts.stated_ratio_str = f"{m_ratio.group(1)}%"

        return facts


scenario_fact_extractor = ScenarioFactExtractor()
