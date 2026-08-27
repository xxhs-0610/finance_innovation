"""System Card and dedicated SYSTEM_META handler for RegTrust-RAG."""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from app.generation.deepseek_client import (
    deepseek_api_key,
    deepseek_base_url,
    deepseek_enabled,
    deepseek_model,
    deepseek_timeout_seconds,
)
from app.utils.logger import get_logger

logger = get_logger("app.router.system_card")


class SystemCard:
    """Authoritative System Profile & Dynamic Responder for SYSTEM_META queries."""

    # 1. System Positioning
    SYSTEM_NAME = "面向银行业监管制度与统计报表的可信 RAG 问答系统"

    # 2. System Capabilities
    CAPABILITIES = [
        "银行业监管制度与政策规章查询",
        "监管条款与法条依据查询",
        "监管阈值（金额、比例、期限底线及限额）查询",
        "监管业务办理及报送流程查询",
        "监管指标定义、计算方法与统计口径查询",
        "监管统计报表（Excel/统计表季度与月度指标）取数查询",
        "跨监管文件比对与联合查询",
        "正文与附件（如《资本管理办法》附件1至24）联合查询",
        "基于监管依据的业务场景合规辅助判断",
    ]

    # 3. Data Sources (Strictly based on reality, no hallucinated sources)
    DATA_SOURCES = [
        "国家金融监管部门发布的银行业监管制度与政策规章",
        "官方监管统计报表与指标披露附件（含《商业银行资本管理办法》附件1至附件24技术细则）",
        "主要商业银行监管指标季度/月度统计数据集",
        "官方比赛提供与授权的银行业监管语料资料",
    ]

    # 4. Response Principles
    PRINCIPLES = [
        "有依据才回答：所有结论均须有明确的制度条款或报表证据支持",
        "证据不足不猜测：检索证据不足以支持确定性结论时坚决安全拒答",
        "信息不足主动澄清：用户提问缺失指标或指代不明时主动追问",
        "领域外问题拒绝回答：对股票走势、投资理财、求职招聘及通用百科严格拦截",
        "监管事实尽量提供来源依据：回答明确标注引用的制度依据与 [E#] 编号",
    ]

    def generate_response(self, question: str) -> str:
        """Generate a concise, targeted system explanation without full dump."""
        q = (question or "").strip()
        return self._generate_deterministic(q)

    def _generate_deterministic(self, question: str) -> str:
        """Deterministic targeted responder matched to user focus."""
        text = question.strip().lower()

        # A. Identity / Name
        if any(w in text for w in ("你是谁", "你叫什么", "系统介绍", "你是什么系统", "自我介绍")):
            return (
                f"我是**{self.SYSTEM_NAME}**。\n\n"
                f"我专为银行业监管政策溯源、条款阈值核验、指标口径查阅以及统计报表数据分析而构建，"
                f"为金融机构、合规人员及研究人员提供高可靠、可溯源的监管问答支持。"
            )

        # B. Problems solved / Capabilities
        if any(w in text for w in ("解决什么问题", "你能做什么", "能干嘛", "功能", "支持哪些问题", "支持什么功能", "哪些能力")):
            caps = "\n".join(f"- {c}" for c in self.CAPABILITIES)
            return (
                f"作为**{self.SYSTEM_NAME}**，我主要帮助用户解决以下银行业监管与报表分析问题：\n\n"
                f"{caps}"
            )

        # C. Data sources
        if any(w in text for w in ("数据来源", "从哪来", "语料", "知识库来源", "数据是什么", "哪些数据")):
            sources = "\n".join(f"- {s}" for s in self.DATA_SOURCES)
            return (
                f"本系统的知识库严格基于权威真实的官方监管资料构建，主要数据来源包括：\n\n"
                f"{sources}\n\n"
                f"系统不收录未经授权的非官方言论或网络传闻，确保数据源的严肃性与合规性。"
            )

        # D. Why not answering out-of-scope (e.g. Weather, Stocks)
        if any(w in text for w in ("为什么天气", "为什么不回答", "拒答", "限制", "不理我", "天气问题")):
            return (
                f"本系统严格遵循**“领域外问题拒绝回答、有依据才回答”**的可信安全原则。\n\n"
                f"天气、生活娱乐、股票预测、银行招聘等属于通用百科或非监管业务范围，"
                f"系统设定了合规安全护栏主动拦截，以避免产生与监管制度无关的模型幻觉，"
                f"保证系统在银行业监管专业领域的严谨性。"
            )

        # E. Specific capability inquiries (e.g. Regulatory Reports)
        if any(w in text for w in ("查询监管报表", "查报表", "支持报表", "可以查询报表", "报表查询")):
            return (
                f"**可以**。系统完全支持监管统计报表查询与取数分析。\n\n"
                f"包括：各年度商业银行主要监管指标统计表（Excel/Word）、"
                f"特定季度/月度（如资本充足率、不良贷款率、拨备覆盖率）的数值定位，"
                f"以及制度正文与配套附表说明的联合比对。"
            )

        # F. Trustworthiness / Reliability
        if any(w in text for w in ("可信", "保证可信", "靠谱吗", "有依据吗", "准确吗")):
            principles = "\n".join(f"- {p}" for p in self.PRINCIPLES)
            return (
                f"本系统通过以下**五大原则**保证回答的高度可信与合规：\n\n"
                f"{principles}"
            )

        # Default: Concise overall intro
        return (
            f"您好！我是**{self.SYSTEM_NAME}**。\n\n"
            f"我专注于银行业监管制度（如《商业银行资本管理办法》）、监管阈值、指标定义、统计报表及合规判定。"
            f"所有业务回答均基于权威监管文件严格溯源，坚持“有依据才回答、证据不足不猜测”的可信原则。"
        )

    def _generate_with_llm(self, question: str) -> str | None:
        """Use DeepSeek to synthesize a concise, natural response based on SystemCard."""
        api_key = deepseek_api_key()
        if not api_key:
            return None

        prompt_system = (
            "你是一个面向银行业监管制度与统计报表的可信问答系统助手。\n"
            "请严格基于以下给定的【System Card 真实信息】，针对用户的具体提问，生成一段专业、自然且简洁的系统说明。\n\n"
            "【System Card 真实信息】:\n"
            f"1. 系统定位: {self.SYSTEM_NAME}\n"
            f"2. 主要能力: {'; '.join(self.CAPABILITIES)}\n"
            f"3. 真实数据来源: {'; '.join(self.DATA_SOURCES)}\n"
            f"4. 核心回答原则: {'; '.join(self.PRINCIPLES)}\n\n"
            "【严格要求】:\n"
            "- 必须简洁聚焦：针对用户询问的点直接回答（例如问'你是谁'就简洁介绍定位；问'为什么不回答天气'就解释领域外拦截与可信原则；问'能否查监管报表'就明确确认并说明报表能力），千万不要把全部卡片一次性堆砌出来。\n"
            "- 严禁虚构任何 System Card 中没有的数据来源或通用聊天能力。\n"
            "- 语气严谨、专业、礼貌。"
        )

        url = f"{deepseek_base_url().rstrip('/')}/chat/completions"
        payload = {
            "model": deepseek_model(),
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": question},
            ],
            "temperature": 0.2,
            "max_tokens": 400,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            timeout = min(deepseek_timeout_seconds(), 8.0)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                choice = (data.get("choices") or [{}])[0]
                text = choice.get("message", {}).get("content", "").strip()
                return text if text else None
        except Exception as exc:
            logger.warning(f"[SystemCard] LLM生成系统说明异常，采用内置规则回复: {type(exc).__name__}: {exc}")
            return None


system_card = SystemCard()

__all__ = ["SystemCard", "system_card"]
