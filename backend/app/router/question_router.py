"""Question Router for pre-retrieval intent classification and policy enforcement."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Optional

import certifi

from app.generation.deepseek_client import (
    deepseek_api_key,
    deepseek_base_url,
    deepseek_enabled,
    deepseek_model,
    deepseek_timeout_seconds,
)
from app.router.router_prompts import (
    CLARIFICATION_HINTS,
    OUT_OF_SCOPE_RESPONSES,
    ROUTER_SYSTEM_PROMPT,
    SYSTEM_META_CARD_CONTENT,
)
from app.schemas.router_schema import DomainTaskType, RouteDecision, RouterIntent
from app.utils.logger import get_logger

logger = get_logger("app.router")


class QuestionRouter:
    """Intelligent Question Router placed immediately before RAG retrieval.
    
    Responsibilities:
      - Classify user input into Level 1 Intents: DOMAIN_QA, SYSTEM_META, OUT_OF_SCOPE, or NEED_CLARIFICATION.
      - When intent is DOMAIN_QA, classify into 6 Level 2 Task Types:
          * TABLE_LOOKUP: Single/multi-period point data retrieval from tables/Excel.
          * TABLE_COMPARE: Extremum / ranking / magnitude comparison across table items.
          * TABLE_CALCULATION: Arithmetic calculation / difference / growth between table cells.
          * FACT_SINGLE_CHOICE: Single-choice question with 1 correct assertion.
          * FACT_MULTI_CHOICE: Multi-choice or multi-fact paired combination question.
          * DIRECT_FACT_QA: Non-choice regulatory clauses, thresholds, rules, processes, definitions, compliance.
      - Never directly answer user questions; only categorize intent and task type.
      - Ensure ONLY DOMAIN_QA questions proceed to RAG search and execution.
    """

    def __init__(self) -> None:
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        # 1. System Meta Patterns (queries asking about the system itself)
        self.system_meta_re = re.compile(
            r"(?:你能做什么|你(?:能|可以)解决什么问题|这个系统解决什么问题|你支持哪些(?:功能|问题|查询)|你的数据来源是什么|"
            r"数据来源|系统介绍|你是什么系统|自我介绍|系统功能|为什么(?:刚才|.*?)(?:不回答|拒答|拒绝回答)|"
            r"你的回答可信吗|如何保证(?:回答)?(?:的)?可信|可信保障|有哪些(?:使用)?限制|系统限制|谁开发的|你是谁|"
            r"定位和核心功能|防止大模型.*?产生幻觉|如何防止.*?幻觉|合规辅助判断|"
            r"(?:知识库|系统)?数据(?:来源|来自|来自于)|来自于哪些|"
            r"系统(?:是否)?支持.*(?:查询|检索|比对)|支持跨.*(?:联合查询|查询)|"
            r"你(?:可以|能否|支持|能|会)(?:查询|检索|查看|处理|分析)?(?:监管)?(?:报表|统计表|制度|条款|指标)(?:吗|？|\?))",
            re.IGNORECASE,
        )

        # 2. Out-of-Scope: Stocks, Investments, Recruitment, Retail Services, Daily Life
        self.stock_re = re.compile(
            r"(?:股票|股价|大盘|行情|走势|会涨吗|会上涨吗|会跌吗|牛市|熊市|买入|卖出|建仓|炒股|开户|代码多少|市值多少|ETF基金|黄金概念股票|加密货币|比特币)",
            re.IGNORECASE,
        )
        self.investment_re = re.compile(
            r"(?:理财产品推荐|买什么基金|投资建议|能赚钱吗|赚钱|理财收益|高收益|哪款产品好|存款利率最高|大额存单.*利息|收益稳定.*理财产品)",
            re.IGNORECASE,
        )
        self.recruitment_re = re.compile(
            r"(?:招聘|校招|社招|招人|招前端|招后端|投递简历|薪资|待遇|面试|求职|工资|柜员.*学历|学历背景|笔试考)",
            re.IGNORECASE,
        )
        self.retail_services_re = re.compile(
            r"(?:办理借记卡|开户需要带什么|办卡需要|下班关门|营业时间|网点几点|吞卡|转账限额怎么|提高.*转账限额|"
            r"个人申请.*(?:车贷|汽车.*贷款|汽车按揭|房贷)|按揭贷款.*抵押机动车|汽车按揭贷款|"
            r"房贷断供.*法拍|征信黑名单|个人征信|汇率.*(?:升值|贬值)|降息25个基点|议息会议|"
            r"兑换.*现钞|换外币现钞|存款保险能赔多少|倒闭了存款保险|提现到银行卡|微信.*提现|支付宝.*提现)",
            re.IGNORECASE,
        )
        self.general_daily_re = re.compile(
            r"(?:天气|气温|下雨|菜谱|做饭|红烧肉|推荐一部电影|电影|游戏攻略|写一首诗|诗歌|写个故事|写代码|写一段|快速排序|排序算法|Python|Java|C\+\+|Javascript|编写代码|翻译成英文|笑话|八卦|旅游攻略|景点|星座|地球到月球|世界杯|感冒发烧|Vue3|皇帝|哲学|Docker|相对论|西湖|减脂减肥|猫咪|太阳系|普洱茶|发动机机油)",
            re.IGNORECASE,
        )

        # 3. Need Clarification Patterns (ambiguous pronouns, missing targets)
        self.clarification_re = re.compile(
            r"^(?:申请|办理)?(?:这个|那个|该|此|某)?(?:比例|数值|指标|要求|规定|数字|条款|许可证)?(?:是多少|是多少呢|是多少呀|怎么算|怎么规定|是什么|发布|满足什么条件|要满足什么条件)?[?？]?$"
            r"|^(?:比例|数值|指标|要求|规定|数字)(?:是多少|是多少呢|是多少呀|怎么算|怎么规定)[?？]?$"
            r"|^(?:按照规定|按规定)?(?:需要)?保存几年[?？]?$"
            r"|^(?:办理这个业务|办理该业务|申请该业务|申请这个许可证|申请该许可证)?(?:需要)?(?:几天(?:时间)?|要满足什么条件|满足什么条件)[?？]?$"
            r"|^(?:满足这个要求|满足该要求)?(?:需要)?多少资本[?？]?$"
            r"|^(?:这家机构|某机构|该银行)?(?:的)?拨备覆盖率达标了吗[?？]?$"
            r"|^(?:资本充足率|监管要求)?最低底线是多少[?？]?$"
            r"|^(?:企业贷款逾期|贷款逾期)(?:了)?(?:是否|算不算)?(?:算)?违约[?？]?$"
            r"|^(?:这项|此项|该项|这个|那个)(?:监管)?(?:惩罚|处罚|问责)?措施是什么[?？]?$"
            r"|^(?:某机构|该机构|这家机构|某银行)(?:这项|此项|该|此)?(?:指标)?(?:超标了吗|达标了吗)[?？]?$"
            r"|^(?:那个|这个|该|此)(?:报表|统计表|文件|通知)(?:什么时候|何时)发布[?？]?$"
            r"|^(?:这个|那个|该|此|某)(?:指标|比例)?的计算公式是什么[?？]?$"
            r"|^(?:这个|那个|该|此|某|各项|这项)?(?:.*)?达到(?:监管)?标准了吗[?？]?$"
        )
        self.ambiguous_action_re = re.compile(
            r"^(?:这样做|这样办|如此办理|该行为|某银行这样做)?(?:合规吗|是否合规|违规吗|可行吗|可以吗|行不行|达到监管标准了吗)[?？]?$"
        )
        self.short_ambiguous_re = re.compile(
            r"^(?:怎么办|什么意思|为什么|有什么规定|如何理解)[?？]?$"
        )

        # 4. Level 2 Task Type Patterns
        self.table_calc_re = re.compile(
            r"(?:两处取数|取数并计算|从.*?到.*?的数值变化|从.*?到.*?数值变化|数值变化|相差多少|相差约为多少|相差|差距|差额是多少|差额约为多少|差额|总和|之和|两者之和|合计与.*?相差|合计是多少|合计为多少|增加了多少|减少了多少|增长率|变化率|增幅|降幅|比值|占.*?比重|占.*?比值|占.*?比例|比重是多少|算得数值变化|绝对值)",
            re.IGNORECASE,
        )
        self.table_compare_re = re.compile(
            r"(?:哪一项数值最高|哪一项数值最低|哪项数值最高|哪项数值最低|哪一项最高|哪一项最低|哪项最高|哪项最低|数值最高|数值最低|哪一项最大|哪一项最小|哪项最大|哪项最小|谁最高|谁最低|谁最大|谁最小|谁最多|谁最少|最高的是|最低的是|谁更[多少高低大小]|谁的.*?更[多少高低大小]|哪项.*?更[多少高低大小]|哪个.*?更[多少高低大小]|按大小比较|比较(?:.*?)(?:谁|最大|最高|最低|最小)|(?:从高到低|从低到高|数值排序|指标排序))",
            re.IGNORECASE,
        )
        self.multi_choice_re = re.compile(
            r"(?:下列哪两项|下列哪几项|哪些表述正确|哪两项表述正确|哪两项表述|哪几项表述|两项表述均属于|均属于该材料内容|均属于|均正确|多项选择|下列哪些项|下列哪些|以下哪些|哪几项|哪些属于|包括哪些|有哪些|多选|哪些项|哪两项|哪三项|原则包括|范围包括|指标包括|业务包括|条件包括|职责包括|包括哪些|包含哪些|哪些项|具有哪些|哪些条件|哪几级|哪些活动|哪些属于|三大.*?要求|哪些方面|下列属于|属于.*?的有|统计口径的有|哪些类别)",
            re.IGNORECASE,
        )
        self.single_choice_re = re.compile(
            r"(?:下列哪项表述正确|下列哪项表述不正确|下列哪项正确|下列哪项错误|下列哪一项表述正确|下列哪一项|以下哪一项与材料内容一致|与材料内容一致|下列选项中正确|下列说法正确|下列说法错误|下列关于.*?的表述.*?正确|下列哪项符合|下列哪一项符合|哪项正确|哪项最高|哪项最低|哪项更高|哪项更低)",
            re.IGNORECASE,
        )
        self.table_context_re = re.compile(
            r"(?:Excel|报表|统计表|工作表|情况表|附件《|口径|截至当期|本年累计|各地区|全国合计|余额|(?:19|20)\d{2}\s*(?:年|[Qq][1-4]|季度|月末|月度|月份))",
            re.IGNORECASE,
        )
        self.choice_format_re = re.compile(
            r"(?:^|\n|\s)[A-D]\s*[:：\.、]|\bA\s*[:：]|\bB\s*[:：]|\bC\s*[:：]|\bD\s*[:：]"
        )

        # 5. Domain Keywords
        self.domain_keywords = (
            "资本充足率", "核心一级资本充足率", "一级资本充足率", "杠杆率", "流动性覆盖率",
            "净稳定资金比例", "拨备覆盖率", "不良贷款率", "贷款拨备率", "流动性比例", "存贷比",
            "净息差", "商业银行", "农村商业银行", "政策性银行", "消费金融公司", "金融租赁公司",
            "资本管理办法", "指标", "第一档", "第二档", "第三档", "附件", "报表", "统计表",
            "合规", "底线", "阈值", "条款", "操作指引", "管理办法", "监管指引"
        )

    def route(self, question: str) -> RouteDecision:
        """Route the user question and return a structured RouteDecision."""
        q = (question or "").strip()
        if not q:
            decision = RouteDecision(
                intent="NEED_CLARIFICATION",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=True,
                reason="问题内容为空，请提供具体问题",
            )
            self._log_decision(q, decision)
            return decision

        # 1. Fast deterministic rule evaluation. Safety/system boundary results
        # remain deterministic; domain questions are subsequently reviewed by
        # DeepSeek so nuanced table-vs-choice semantics are understood first.
        fast_decision = self._fast_rule_route(q)
        if fast_decision is not None and fast_decision.intent in {"SYSTEM_META", "OUT_OF_SCOPE"}:
            self._log_decision(q, fast_decision)
            return fast_decision

        # 2. DeepSeek semantic review before retrieval for domain questions.
        if deepseek_enabled():
            llm_decision = self._llm_classify(q)
            if llm_decision is not None:
                # A structured KB question that passed deterministic
                # boundary checks must not be rejected solely because the LLM
                # narrows "banking regulation" too aggressively (for example,
                # insurance tables and solvency attachments that are in this KB).
                if (
                    llm_decision.intent == "OUT_OF_SCOPE"
                    and fast_decision is not None
                    and fast_decision.intent == "DOMAIN_QA"
                    and fast_decision.task_type
                    in {
                        "TABLE_LOOKUP",
                        "TABLE_COMPARE",
                        "TABLE_CALCULATION",
                        "FACT_SINGLE_CHOICE",
                        "FACT_MULTI_CHOICE",
                        "DIRECT_FACT_QA",
                    }
                ):
                    self._log_decision(q, fast_decision)
                    return fast_decision
                self._log_decision(q, llm_decision)
                return llm_decision

        # 3. Safe fallback when DeepSeek is disabled or temporarily unavailable.
        fallback_decision = fast_decision or self._safe_fallback_route(q)
        self._log_decision(q, fallback_decision)
        return fallback_decision

    def _is_multi_target_or_choice(self, text: str) -> bool:
        """Check if query clearly specifies multiple targets, choices, comparisons, or calculations.
        
        Rule: Multiple targets NEVER equal ambiguity.
        """
        if self.choice_format_re.search(text):
            return True
        if self.table_calc_re.search(text):
            return True
        if self.table_compare_re.search(text):
            return True
        if self.multi_choice_re.search(text) or self.single_choice_re.search(text):
            return True
        if re.search(r"比较|相差|差额|从.*?到.*?", text):
            return True
        if len(re.findall(r"“[^”]+”|‘[^’]+’|《[^》]+》", text)) >= 2:
            return True
        return False

    def _is_dangling_demonstrative(self, text: str) -> bool:
        """Check if question has an unresolved demonstrative pronoun missing its concrete referent."""
        if re.match(r"^(?:申请|办理)?(?:这个|那个|这项|该项|此项|某机构|这家机构|这家银行)", text):
            # If text has explicit numbers, quotes, or well-defined metric keywords, it's not dangling
            if re.search(r"《[^》]+》|附件\d+|\d+(?:%|万|亿|年|月|条)", text):
                return False
            specific_entities = (
                "核心一级资本充足率", "一级资本充足率", "杠杆率", "流动性覆盖率",
                "净稳定资金比例", "不良贷款率", "贷款拨备率", "净息差",
                "大额风险暴露", "非同业单一客户", "单一集团客户"
            )
            if not any(se in text for se in specific_entities):
                return True
        return False

    def _fast_rule_route(self, question: str) -> Optional[RouteDecision]:
        """Perform zero-latency rule matching for high-precision cases."""
        text = question.strip()

        # A. System Meta
        if self.system_meta_re.search(text):
            return RouteDecision(
                intent="SYSTEM_META",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问系统自身定位、功能、数据来源或可信机制",
            )

        # Check if the query clearly targets a regulatory document, statistical table, or regulatory rule
        has_doc_or_stat = bool(re.search(r"《[^》]+》|资金运用|监管指标|情况表|管理办法|办法|指引|规定|细则|口径|报表|发布日程|主要指标|资产负债", text))

        # B. Out of Scope (Explicitly check stocks, recruitment, retail services, daily life)
        if not has_doc_or_stat and self.stock_re.search(text):
            return RouteDecision(
                intent="OUT_OF_SCOPE",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问股票行情、股价走势预测或证券交易，超出监管制度与统计范围",
            )
        if not has_doc_or_stat and self.investment_re.search(text):
            return RouteDecision(
                intent="OUT_OF_SCOPE",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问个人投资理财建议或金融产品推荐，超出监管政策范围",
            )
        if self.recruitment_re.search(text):
            return RouteDecision(
                intent="OUT_OF_SCOPE",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问银行求职招聘、薪资待遇，超出监管制度范围",
            )
        if self.retail_services_re.search(text):
            return RouteDecision(
                intent="OUT_OF_SCOPE",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问个人日常银行网点零售业务或个人金融操作，超出监管制度与统计报表范围",
            )
        if self.general_daily_re.search(text):
            return RouteDecision(
                intent="OUT_OF_SCOPE",
                task_type=None,
                qa_type=None,
                need_retrieval=False,
                need_clarification=False,
                reason="用户询问天气、娱乐、通用编程或日常生活问题，属于领域外通用百科",
            )

        # C. Need Clarification (Protected: only trigger if NOT multi-target / choice)
        if not self._is_multi_target_or_choice(text):
            if self.clarification_re.match(text) or self._is_dangling_demonstrative(text) or text in {"这个比例是多少？", "这个比例是多少", "指标是多少"}:
                return RouteDecision(
                    intent="NEED_CLARIFICATION",
                    task_type=None,
                    qa_type=None,
                    need_retrieval=False,
                    need_clarification=True,
                    reason="问题包含未指明的代词且缺少具体指标或监管制度名称，需澄清",
                )
            if self.ambiguous_action_re.match(text) or text in {"这样做合规吗？", "这样做合规吗"}:
                return RouteDecision(
                    intent="NEED_CLARIFICATION",
                    task_type=None,
                    qa_type=None,
                    need_retrieval=False,
                    need_clarification=True,
                    reason="问题缺少具体的业务操作或场景描述，无法进行合规判定",
                )
            if self.short_ambiguous_re.match(text) or len(text) <= 3:
                return RouteDecision(
                    intent="NEED_CLARIFICATION",
                    task_type=None,
                    qa_type=None,
                    need_retrieval=False,
                    need_clarification=True,
                    reason="输入过短或语义模糊，缺少监管业务上下文",
                )

        # D. Domain QA Task Types
        # D1. TABLE_CALCULATION: Explicit multi-value arithmetic or variation calculation
        if self.table_calc_re.search(text):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="TABLE_CALCULATION",
                qa_type="TABLE_CALCULATION",
                need_retrieval=True,
                need_clarification=False,
                reason="用户要求从表格数据中获取多个数值并进行数学运算/数值变化比对",
            )

        # D2. TABLE_COMPARE: Extremum comparison or ranking across candidate indicators
        if self.table_compare_re.search(text):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="TABLE_COMPARE",
                qa_type="TABLE_COMPARE",
                need_retrieval=True,
                need_clarification=False,
                reason="用户要求对表格中的多个指标或候选项进行数值大小比较/极值排序",
            )

        # D3. FACT_MULTI_CHOICE: Multi-choice or multi-fact paired assertions
        if self.multi_choice_re.search(text) or (self.choice_format_re.search(text) and text.count("；") >= 2):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="FACT_MULTI_CHOICE",
                qa_type="FACT_MULTI_CHOICE",
                need_retrieval=True,
                need_clarification=False,
                reason="用户提供多项选择题或要求核验双事实/多事实组合",
            )

        # D4. FACT_SINGLE_CHOICE: Single-choice verification
        if self.single_choice_re.search(text) or self.choice_format_re.search(text):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="FACT_SINGLE_CHOICE",
                qa_type="FACT_SINGLE_CHOICE",
                need_retrieval=True,
                need_clarification=False,
                reason="用户提供单项选择题，要求核验唯一正确表述",
            )

        # D5. TABLE_LOOKUP: Table value lookup (checked after choices so choice questions stay FACT_CHOICE)
        if self.table_context_re.search(text) and any(
            w in text for w in ("是多少", "多少", "数值", "情况", "余额", "口径", "本年累计", "截至当期")
        ):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="TABLE_LOOKUP",
                qa_type="TABLE_LOOKUP",
                need_retrieval=True,
                need_clarification=False,
                reason="用户询问特定统计报表或时间区间的单点或多期间表格取数",
            )

        # D6. DIRECT_FACT_QA: Direct regulatory facts, thresholds, compliance, processes, definitions
        if any(w in text for w in ("不得低于", "不低于", "不得高于", "不超过", "最低要求", "最高限额", "监管底线", "比例要求", "阈值")):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="THRESHOLD_RULE",
                need_retrieval=True,
                need_clarification=False,
                reason="用户询问银行业监管阈值或法定比例底线",
            )
        if any(w in text for w in ("是否合规", "合规吗", "能否认定", "是否允许", "合规判定")):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="COMPLIANCE_JUDGMENT",
                need_retrieval=True,
                need_clarification=False,
                reason="用户依据监管规定进行业务场景合规性判定",
            )
        if any(w in text for w in ("跨文件", "分别规定", "综合判断", "正文与附件")):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="CROSS_DOCUMENT",
                need_retrieval=True,
                need_clarification=False,
                reason="用户涉及跨监管文件或正文附件联合查询",
            )
        if any(w in text for w in ("操作流程", "业务流程", "如何办理", "如何管理", "报送程序", "包括哪些机制")):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="BUSINESS_PROCESS",
                need_retrieval=True,
                need_clarification=False,
                reason="用户询问银行业务流程或监管报送程序",
            )
        if any(w in text for w in ("定义", "统计口径", "计算方法", "计算公式", "填报说明", "含义是什么")):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="INDICATOR_DEFINITION",
                need_retrieval=True,
                need_clarification=False,
                reason="用户询问监管指标定义、统计口径或计算方法",
            )
        if any(kw in text for kw in self.domain_keywords) or re.search(r"《[^》]+》|第[零〇一二三四五六七八九十百千万\d]+条", text):
            return RouteDecision(
                intent="DOMAIN_QA",
                task_type="DIRECT_FACT_QA",
                qa_type="REGULATION_FACT",
                need_retrieval=True,
                need_clarification=False,
                reason="用户询问银行业监管制度与政策条款事实",
            )

        return None

    def _llm_classify(self, question: str) -> Optional[RouteDecision]:
        """Invoke DeepSeek in strict JSON mode to perform nuanced classification."""
        api_key = deepseek_api_key()
        if not api_key:
            return None

        url = f"{deepseek_base_url().rstrip('/')}/chat/completions"
        payload = {
            "model": deepseek_model(),
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": f"请对以下用户输入的问题进行意图与任务类型判定：\n\n【用户问题】: {question}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            # Semantic hints plus four long options can exceed 500 tokens;
            # allow enough room so JSON is not truncated mid-string.
            "max_tokens": 1000,
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
            timeout = min(deepseek_timeout_seconds(), 10.0)  # fast router timeout
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                choice = (data.get("choices") or [{}])[0]
                content = choice.get("message", {}).get("content", "")
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    # Be tolerant of markdown fences or a short preamble from
                    # providers that ignore response_format. If the payload is
                    # genuinely truncated, fall back to deterministic routing.
                    cleaned = str(content or "").strip()
                    if cleaned.startswith("```"):
                        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
                    start, end = cleaned.find("{"), cleaned.rfind("}")
                    if start < 0 or end <= start:
                        raise
                    parsed = json.loads(cleaned[start : end + 1])

                intent = parsed.get("intent", "DOMAIN_QA")
                if intent not in {"DOMAIN_QA", "SYSTEM_META", "OUT_OF_SCOPE", "NEED_CLARIFICATION"}:
                    intent = "DOMAIN_QA"

                task_type = parsed.get("task_type") or parsed.get("qa_type")
                valid_task_types = {
                    "TABLE_LOOKUP", "TABLE_COMPARE", "TABLE_CALCULATION",
                    "FACT_SINGLE_CHOICE", "FACT_MULTI_CHOICE", "DIRECT_FACT_QA"
                }
                legacy_mapping = {
                    "REGULATION_FACT": "DIRECT_FACT_QA",
                    "THRESHOLD_RULE": "DIRECT_FACT_QA",
                    "BUSINESS_PROCESS": "DIRECT_FACT_QA",
                    "INDICATOR_DEFINITION": "DIRECT_FACT_QA",
                    "CROSS_DOCUMENT": "DIRECT_FACT_QA",
                    "COMPLIANCE_JUDGMENT": "DIRECT_FACT_QA",
                }

                if intent == "DOMAIN_QA":
                    if task_type in legacy_mapping:
                        task_type = legacy_mapping[task_type]
                    elif task_type not in valid_task_types:
                        task_type = "DIRECT_FACT_QA"
                else:
                    task_type = None

                need_retrieval = (intent == "DOMAIN_QA")
                need_clarification = (intent == "NEED_CLARIFICATION")
                reason = str(parsed.get("reason") or "大模型意图与任务类型判定")
                semantic = parsed.get("semantic")
                if not isinstance(semantic, dict):
                    semantic = {}
                raw_keywords = semantic.get("keywords") or []
                if isinstance(raw_keywords, str):
                    raw_keywords = [raw_keywords]
                semantic["keywords"] = [str(k).strip() for k in raw_keywords if str(k).strip()]

                return RouteDecision(
                    intent=intent,
                    task_type=task_type,
                    qa_type=task_type,
                    need_retrieval=need_retrieval,
                    need_clarification=need_clarification,
                    reason=reason,
                    semantic=semantic,
                )
        except Exception as exc:
            logger.warning(f"[ROUTER] DeepSeek 路由请求异常 (降级至规则引擎): {type(exc).__name__}: {exc}")
            return None

    def _safe_fallback_route(self, question: str) -> RouteDecision:
        """Deterministic fallback rule-based classifier when LLM is unavailable."""
        text = question.strip()

        # Check in task type priority
        if self.table_calc_re.search(text):
            task_type: DomainTaskType = "TABLE_CALCULATION"
        elif self.table_compare_re.search(text):
            task_type = "TABLE_COMPARE"
        elif self.multi_choice_re.search(text) or (self.choice_format_re.search(text) and text.count("；") >= 2):
            task_type = "FACT_MULTI_CHOICE"
        elif self.single_choice_re.search(text) or self.choice_format_re.search(text):
            task_type = "FACT_SINGLE_CHOICE"
        elif self.table_context_re.search(text) and any(w in text for w in ("是多少", "多少", "数值", "情况", "余额", "口径", "本年累计", "截至当期")):
            task_type = "TABLE_LOOKUP"
        else:
            task_type = "DIRECT_FACT_QA"

        return RouteDecision(
            intent="DOMAIN_QA",
            task_type=task_type,
            qa_type=task_type,
            need_retrieval=True,
            need_clarification=False,
            reason="规则引擎识别为银行业监管业务问题",
        )

    def _log_decision(self, question: str, decision: RouteDecision) -> None:
        """Log structured router decision."""
        logger.info(
            f"[ROUTER]\n"
            f"query={question}\n"
            f"intent={decision.intent}\n"
            f"task_type={decision.task_type or decision.qa_type or 'None'}\n"
            f"need_retrieval={decision.need_retrieval}\n"
            f"need_clarification={decision.need_clarification}\n"
            f"reason={decision.reason}"
        )


question_router = QuestionRouter()

__all__ = ["QuestionRouter", "question_router"]

