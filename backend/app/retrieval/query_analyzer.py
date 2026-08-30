"""Query Analyzer for RegTrust-RAG.

Performs structured semantic & entity analysis for DOMAIN_QA queries before retrieval.
Extracts:
  - topic
  - institution_type
  - regulator (strict: only if explicitly mentioned)
  - document_name (strict: only if explicitly mentioned)
  - article_number (strict: only if explicitly mentioned)
  - indicator (strict: only if explicitly mentioned)
  - time_period (strict: only if explicitly mentioned)
  - rule_type
  - keywords

Crucial Constraints:
  - Never guess or extrapolate unmentioned dates/periods.
  - Never guess or extrapolate unmentioned filenames.
  - Never hallucinate regulators from background knowledge.
  - null is strictly preferred over false completions.
"""

from __future__ import annotations

import re
from typing import Any

from app.retrieval.query_classifier import classify_query
from app.retrieval.task_planner import (
    TaskPlanner,
    extract_choice_options,
    extract_sheet_name,
    task_planner,
)
from app.schemas.chunk_schema import ChunkType
from app.schemas.retrieval_schema import QueryAnalysis, QueryType
from app.schemas.task_plan_schema import TaskPlan
from app.utils.logger import get_logger

logger = get_logger("app.retrieval.query_analyzer")

# Regex Patterns
DOCUMENT_RE = re.compile(r"《([^》]+)》")
DOCUMENT_NUMBER_RE = re.compile(
    r"(?:银保监办发|银保监发|银保监规|银监发|保监发|金规|金办发|银发|财金)"
    r"\s*[〔\[【(]?\s*\d{4}\s*[〕\]】)]?\s*\d{1,4}\s*号"
)
CLAUSE_RE = re.compile(r"第[零〇一二三四五六七八九十百千万\d]+条")
FULL_DATE_RE = re.compile(
    r"(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
)
PERIOD_RE = re.compile(
    r"(?:19|20)\d{2}(?:"
    r"年(?:0?[1-9]|1[0-2])月|"
    r"年(?:第?[一二三四1234]季度|上半年|下半年|年末|年度)?|"
    r"[Qq][1-4]|-(?:0[1-9]|1[0-2])"
    r")"
)
YEAR_RANGE_RE = re.compile(
    r"(?P<start>(?:19|20)\d{2})\s*年?\s*(?:至|到|[-—~～])\s*"
    r"(?P<end>(?:19|20)\d{2})\s*年?"
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}年?")
VALUE_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?\s*(?:[%％]|亿元|万元|元|个|家)")
PUNCTUATION_RE = re.compile(r"[，。！？?；;：:、“”‘’（）()【】\[\]<>《》_-]+")

# Strict Regulator / Issuer candidate list (ordered by specificity)
ISSUERS = (
    "国家金融监督管理总局",
    "金融监管总局",
    "中国银行保险监督管理委员会",
    "中国银保监会",
    "银保监会",
    "中国银行业监督管理委员会",
    "中国银监会",
    "银监会",
    "中国人民银行",
    "人民银行",
    "原中国银保监会",
    "原中国保监会",
    "财政部",
)

# Institution Types (ordered by specificity)
INSTITUTION_TYPES = (
    "第一档商业银行",
    "第二档商业银行",
    "第三档商业银行",
    "第一档银行",
    "第二档银行",
    "第三档银行",
    "农村商业银行",
    "城市商业银行",
    "政策性银行",
    "农村信用社",
    "人身险公司",
    "财产险公司",
    "保险公司",
    "信托公司",
    "金融租赁公司",
    "财务公司",
    "商业银行",
    "银行业金融机构",
    "金融机构",
)

# Regulatory Indicators / Metrics (ordered by specificity)
METRICS = (
    "核心一级资本充足率",
    "一级资本充足率",
    "资本充足率",
    "优质流动性资产充足率",
    "流动性覆盖率",
    "净稳定资金比例",
    "流动性匹配率",
    "流动性比例",
    "拨备覆盖率",
    "贷款拨备率",
    "不良贷款率",
    "不良贷款余额",
    "关注类贷款迁徙率",
    "次级类贷款迁徙率",
    "可疑类贷款迁徙率",
    "原保险保费收入",
    "保险保费收入",
    "赔付支出",
    "资产总额",
    "总资产",
    "负债总额",
    "总负债",
    "杠杆率",
    "存贷比",
    "净息差",
    "净利差",
    "成本收入比",
    "大额风险暴露",
)

# Rule Type Markers
RULE_TYPE_PATTERNS = (
    ("最低监管要求", ("最低监管要求", "最低要求", "底线要求", "最低标准", "监管底线")),
    ("监管阈值", ("不得低于", "不低于", "不得高于", "不得超过", "不高于", "不超过", "比例要求", "限额要求", "阈值")),
    ("禁止性规定", ("禁止", "不得从事", "严禁", "禁止性")),
    ("业务流程", ("流程", "程序", "如何办理", "办理流程", "报送流程", "工作机制", "步骤", "处置程序")),
    ("指标定义与统计口径", ("定义", "含义", "统计口径", "计算方法", "计算公式", "如何计算", "指标说明", "口径")),
    ("合规判定", ("是否合规", "合规吗", "能否认定", "是否允许", "合规性")),
)

# Topic Category Patterns
TOPIC_PATTERNS = (
    ("资本监管", ("资本", "核心一级", "一级资本", "资本充足率", "资本净额", "杠杆率", "风险加权资产", "资本底线", "资本管理")),
    ("流动性监管", ("流动性", "流动性覆盖率", "净稳定资金", "流动性比例", "流动性匹配率", "优质流动性资产")),
    ("信用风险与资产质量", ("不良贷款", "不良率", "拨备", "贷款拨备率", "拨备覆盖率", "逾期", "重组贷款", "授信", "大额风险暴露")),
    ("保险监管", ("保险", "人身险", "财产险", "保费", "赔付", "偿付能力", "原保险保费收入")),
    ("科技与数据治理", ("数据安全", "信息科技", "网络安全", "数据治理", "恢复计划", "处置计划")),
    ("公司治理", ("公司治理", "股东", "股权", "关联交易", "董事会", "监事会", "内部控制")),
    ("监管统计与报表", ("统计表", "报表", "情况表", "季度", "月度", "主要监管指标")),
)

QUESTION_PHRASES = (
    "请问",
    "请说明",
    "请介绍",
    "请列出",
    "是多少",
    "是多少？",
    "是多少?",
    "是什么",
    "是什么？",
    "是什么?",
    "有哪些",
    "如何",
    "吗",
    "？",
    "?",
)


class QueryAnalyzer:
    """Intelligent semantic & entity query analyzer for banking regulation RAG."""

    def analyze(
        self,
        question: str,
        task_type: str | None = None,
        options: dict[str, str] | None = None,
        semantic_hint: dict[str, Any] | None = None,
    ) -> QueryAnalysis:
        """Parse user query into structured QueryAnalysis and TaskPlan without false assumptions."""
        raw = (question or "").strip()
        normalized = " ".join(raw.split())
        semantic = semantic_hint if isinstance(semantic_hint, dict) else {}
        query_type = classify_query(normalized)

        # 0. Generate Execution Plan via TaskPlanner
        # The API/evaluator commonly embeds A-D options directly in the
        # question and does not pass a separate ``options`` mapping. Extract
        # them here so TABLE_COMPARE and choice verification retain all
        # candidates instead of producing an empty plan.
        extracted_stem, extracted_options = extract_choice_options(normalized)
        effective_options = options or extracted_options
        task_plan = task_planner.plan(
            question=normalized,
            task_type=task_type,
            options=effective_options,
            semantic_hint=semantic,
        )

        entities: dict[str, str] = {}
        filters: dict[str, str] = {}

        # 1. Document Name (Strict: only if enclosed in 《》 or explicit title from plan)
        document_name: str | None = None
        if task_plan.source and task_plan.source.file_name:
            document_name = task_plan.source.file_name
        elif task_plan.source_constraints and task_plan.source_constraints.document_name:
            document_name = task_plan.source_constraints.document_name
        else:
            doc_match = DOCUMENT_RE.search(normalized)
            if doc_match:
                document_name = doc_match.group(1).strip()
            elif "商业银行资本管理办法" in normalized:
                document_name = "商业银行资本管理办法"

        if document_name:
            entities["document"] = document_name
            filters["title"] = document_name
        elif semantic.get("document_name"):
            document_name = str(semantic["document_name"]).strip()
            entities["document"] = document_name
            filters["title"] = document_name

        # Document Number
        doc_num_match = DOCUMENT_NUMBER_RE.search(normalized)
        if doc_num_match:
            doc_num = re.sub(r"\s+", "", doc_num_match.group(0))
            entities["document_number"] = doc_num

        # 2. Regulator (Strict: only if explicitly present, NEVER guess)
        regulator: str | None = None
        for candidate in ISSUERS:
            if candidate in normalized:
                regulator = candidate
                entities["issuer"] = candidate
                filters["issuer"] = candidate
                break

        # 3. Institution Type (Strict: only if explicitly present)
        institution_type: str | None = None
        for inst in INSTITUTION_TYPES:
            if inst in normalized:
                institution_type = inst
                if "第" in inst and "档" in inst:
                    entities["bank_tier"] = (
                        "第一档商业银行" if "第一档" in inst else
                        "第二档商业银行" if "第二档" in inst else "第三档商业银行"
                    )
                entities["institution"] = institution_type
                break

        # 4. Indicator / Metric (Strict: only if explicitly present)
        indicator: str | None = None
        for m in METRICS:
            if m in normalized:
                indicator = m
                entities["metric"] = m
                break
        if not indicator and semantic.get("indicator"):
            indicator = str(semantic["indicator"]).strip()
            entities["metric"] = indicator

        # 5. Article Number (Strict: only if explicitly present)
        article_number: str | None = None
        if task_plan.source_constraints and task_plan.source_constraints.article_number:
            article_number = task_plan.source_constraints.article_number
        else:
            clause_match = CLAUSE_RE.search(normalized)
            if clause_match:
                article_number = clause_match.group(0)
        if article_number:
            entities["clause_no"] = article_number

        # 6. Time Period (Strict: only if explicitly present, NEVER guess)
        time_period: str | None = None
        date_match = FULL_DATE_RE.search(normalized)
        period_match = PERIOD_RE.search(normalized)
        year_range_match = YEAR_RANGE_RE.search(normalized)

        if year_range_match:
            time_period = f"{year_range_match.group('start')}年至{year_range_match.group('end')}年"
            entities["start_year"] = year_range_match.group("start")
            entities["end_year"] = year_range_match.group("end")
        elif date_match:
            time_period = date_match.group(0)
            entities["date"] = time_period
        elif period_match:
            time_period = period_match.group(0)
            entities["period"] = time_period
            norm_period = self._normalize_period(period_match.group(0))
            if norm_period:
                entities["normalized_period"] = norm_period
            year_match = YEAR_RE.search(period_match.group(0))
            if year_match:
                filters["publish_date"] = re.sub(r"\D", "", year_match.group(0))
        if not time_period and semantic.get("time_period"):
            time_period = str(semantic["time_period"]).strip()
            entities["period"] = time_period

        # Operators & Values
        val_match = VALUE_RE.search(normalized)
        if val_match:
            entities["value"] = re.sub(r"\s+", "", val_match.group(0))
        op = self._extract_operator(normalized)
        if op:
            entities["operator"] = op

        # 7. Rule Type
        rule_type: str | None = None
        for r_name, r_markers in RULE_TYPE_PATTERNS:
            if any(marker in normalized for marker in r_markers):
                rule_type = r_name
                break
        if not rule_type and (query_type == "table_lookup" or (time_period and any(w in normalized for w in ("报表", "情况表", "统计表", "数值是多少", "是多少")))):
            rule_type = "统计报表取数"

        # 8. Topic
        topic = "银行业监管制度"
        for t_name, t_markers in TOPIC_PATTERNS:
            if any(marker in normalized for marker in t_markers):
                topic = t_name
                break

        # Preferred chunk type
        preferred_chunk_type: ChunkType | None = None
        if task_plan.task_type in {"TABLE_LOOKUP", "TABLE_COMPARE", "TABLE_CALCULATION"} or query_type == "table_lookup":
            preferred_chunk_type = "table"
        elif query_type in {"regulation_fact", "clause_threshold", "business_procedure", "cross_document"}:
            preferred_chunk_type = "clause"
        elif rule_type == "合规判定" or "合规" in normalized:
            preferred_chunk_type = "clause"

        # 9. Compact, ordered keywords
        keywords = self._build_keywords(
            question=normalized,
            entities=entities,
            institution_type=institution_type,
            indicator=indicator,
            regulator=regulator,
            document_name=document_name,
            article_number=article_number,
            time_period=time_period,
            rule_type=rule_type,
        )
        semantic_scope = str(semantic.get("scope") or "").strip()
        if semantic_scope and semantic_scope not in keywords:
            keywords.append(semantic_scope)
        for value in semantic.get("keywords") or []:
            value = str(value).strip()
            if value and value not in keywords:
                keywords.append(value)
        if semantic.get("sheet_name"):
            entities["sheet_name"] = str(semantic["sheet_name"]).strip()
            if entities["sheet_name"] and entities["sheet_name"] not in keywords:
                keywords.append(entities["sheet_name"])

        analysis = QueryAnalysis(
            question=normalized,
            query_type=query_type,
            keywords=keywords,
            filters=filters,
            entities=entities,
            preferred_chunk_type=preferred_chunk_type,
            topic=topic,
            institution_type=institution_type,
            regulator=regulator,
            document_name=document_name,
            article_number=article_number,
            indicator=indicator,
            time_period=time_period,
            rule_type=rule_type,
            task_type=task_plan.task_type,
            task_plan=task_plan,
        )

        logger.info(
            f"[QueryAnalyzer] 解析完成 | query='{analysis.question}' | task_type='{analysis.task_type}' | "
            f"topic='{analysis.topic}' | institution='{analysis.institution_type}' | "
            f"indicator='{analysis.indicator}' | period='{analysis.time_period}' | rule='{analysis.rule_type}'"
        )
        return analysis

    def _build_keywords(
        self,
        question: str,
        entities: dict[str, str],
        institution_type: str | None,
        indicator: str | None,
        regulator: str | None,
        document_name: str | None,
        article_number: str | None,
        time_period: str | None,
        rule_type: str | None,
    ) -> list[str]:
        keywords: list[str] = []

        is_compliance = rule_type == "合规判定" or any(
            w in question for w in ("合规吗", "是否合规", "能否办理", "是否违规", "是否允许")
        )

        # Explicit entity prioritization
        if regulator and regulator not in keywords:
            keywords.append(regulator)
        if document_name and document_name not in keywords:
            keywords.append(document_name)
        if institution_type and institution_type not in keywords:
            keywords.append(institution_type)
        if indicator and indicator not in keywords:
            keywords.append(indicator)
        if article_number and article_number not in keywords:
            keywords.append(article_number)
        if time_period and time_period not in keywords:
            keywords.append(time_period)

        # Rule type qualifiers
        if "最低监管要求" in question or "最低要求" in question:
            kw = "最低要求"
            if kw not in keywords:
                keywords.append(kw)
        elif "监管底线" in question or "底线" in question:
            if "监管底线" not in keywords:
                keywords.append("监管底线")
        elif "不低于" in question and "不低于" not in keywords:
            keywords.append("不低于")
        elif "不得高于" in question and "不得高于" not in keywords:
            keywords.append("不得高于")
        elif "不超过" in question and "不超过" not in keywords:
            keywords.append("不超过")

        # Entity dictionary fallback for additional tokens
        # For compliance questions, skip arbitrary monetary numbers to avoid noisy retrieval
        for key in ("document_number", "value"):
            if is_compliance and key == "value":
                continue
            v = entities.get(key)
            if v and v not in keywords:
                keywords.append(v)

        # Compliance specific conceptual keywords
        if is_compliance:
            if any(w in question for w in ("单一客户", "单一企业", "某企业", "企业A", "客户A", "贷款")):
                for k in ("单一客户", "资本净额", "大额风险暴露", "贷款"):
                    if k not in keywords:
                        keywords.append(k)
            if any(w in question for w in ("董事", "监事", "高管", "股东", "关系人", "关联方")):
                for k in ("关系人", "信用贷款", "禁止"):
                    if k not in keywords:
                        keywords.append(k)

        # Residual clean semantic words
        core = question
        for p in QUESTION_PHRASES:
            core = core.replace(p, " ")
        for r_name, r_markers in RULE_TYPE_PATTERNS:
            for m in r_markers:
                core = core.replace(m, " ")
        for kw in list(keywords):
            core = core.replace(kw, " ")
        core = PUNCTUATION_RE.sub(" ", core)
        for tok in core.split():
            tok_clean = tok.strip()
            # In compliance queries, filter out hypothetical numbers and placeholder entity tokens
            if is_compliance and (re.search(r"\d", tok_clean) or tok_clean.startswith("拟向") or "客户" in tok_clean):
                continue
            if len(tok_clean) >= 2 and tok_clean not in keywords and tok_clean not in {"规定", "情况", "标准", "要求", "指标", "监管"}:
                keywords.append(tok_clean)

        if not keywords and question:
            keywords.append(question)

        return keywords

    def _normalize_period(self, period: str) -> str:
        month_match = re.search(r"年(0?[1-9]|1[0-2])月", period)
        dashed_month_match = re.search(r"-((?:0[1-9]|1[0-2]))", period)
        quarter_match = re.search(r"第?([一二三四1234])季度", period)
        q_match = re.search(r"[Qq]([1-4])", period)
        year_match = re.search(r"(?:19|20)\d{2}", period)
        if not year_match:
            return ""
        year = year_match.group(0)
        if month_match:
            return f"{year}-{int(month_match.group(1)):02d}"
        if dashed_month_match:
            return f"{year}-{dashed_month_match.group(1)}"
        if q_match:
            return f"{year}Q{q_match.group(1)}"
        if quarter_match:
            q_map = {"一": "1", "二": "2", "三": "3", "四": "4"}
            q = q_map.get(quarter_match.group(1), quarter_match.group(1))
            return f"{year}Q{q}"
        return ""

    def _extract_operator(self, text: str) -> str:
        markers = (
            ("not_less_than", ("不得低于", "不低于", "不少于")),
            ("not_more_than", ("不得高于", "不得超过", "不高于", "不超过")),
            ("minimum", ("最低", "下限", "至少")),
            ("maximum", ("最高", "上限", "至多")),
            ("year_on_year", ("同比",)),
            ("month_on_month", ("环比",)),
            ("compare", ("比较", "对比", "差异")),
        )
        for op, ms in markers:
            if any(m in text for m in ms):
                return op
        return ""


query_analyzer = QueryAnalyzer()
analyze_query = query_analyzer.analyze

__all__ = [
    "QueryAnalyzer",
    "query_analyzer",
    "analyze_query",
    "TaskPlanner",
    "task_planner",
    "extract_choice_options",
    "extract_sheet_name",
]
