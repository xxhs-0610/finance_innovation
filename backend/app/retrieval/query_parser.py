"""Query Parser facade providing backward compatibility with Module 3 retrieval."""

from __future__ import annotations

from app.retrieval.query_analyzer import (
    DOCUMENT_NUMBER_RE,
    DOCUMENT_RE,
    FULL_DATE_RE,
    ISSUERS,
    INSTITUTION_TYPES as INSTITUTIONS,
    METRICS,
    PERIOD_RE,
    QUESTION_PHRASES,
    RULE_TYPE_PATTERNS as OPERATOR_MARKERS,
    TOPIC_PATTERNS,
    VALUE_RE,
    YEAR_RANGE_RE,
    YEAR_RE,
    QueryAnalyzer,
    TaskPlanner,
    analyze_query,
    extract_choice_options,
    extract_sheet_name,
    query_analyzer,
    task_planner,
)
<<<<<<< HEAD
from app.schemas.retrieval_schema import QueryAnalysis, QueryType
from app.schemas.task_plan_schema import (
    ChoiceOption,
    SourceConstraints,
    TableCandidate,
    TableOperand,
    TableSource,
    TableTarget,
    TaskPlan,
=======
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
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
ORGANIZATION_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9·]{2,40}?"
    r"(?:大学|学院|学校|银行|保险公司|保险集团|证券公司|基金公司|信托公司|"
    r"金融控股公司|监管局|管理局|委员会|监督管理总局)"
)
GENERIC_ORGANIZATIONS = {
    "银行", "商业银行", "城市商业银行", "农村商业银行", "政策性银行",
    "保险公司", "证券公司", "基金公司", "金融机构",
}
VALUE_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?\s*(?:[%％]|亿元|万元|元|个|家)")
PUNCTUATION_RE = re.compile(r"[，。！？?；;：:、“”‘’（）()【】\[\]<>《》]+")

ISSUERS = (
    "国家金融监督管理总局",
    "中国银行保险监督管理委员会",
    "中国银行业监督管理委员会",
    "中国人民银行",
    "原中国银保监会",
    "财政部",
)
INSTITUTIONS = (
    "农村商业银行",
    "银行业金融机构",
    "商业银行",
    "政策性银行",
    "城市商业银行",
    "农村信用社",
    "金融机构",
)
BANK_TIERS = (
    "第一档商业银行",
    "第二档商业银行",
    "第三档商业银行",
    "第一档银行",
    "第二档银行",
    "第三档银行",
)
METRICS = (
    "核心一级资本充足率",
    "一级资本充足率",
    "资本充足率",
    "流动性覆盖率",
    "净稳定资金比例",
    "拨备覆盖率",
    "不良贷款率",
    "贷款拨备率",
    "流动性比例",
    "存贷比",
    "净息差",
    "不良贷款余额",
    "原保险保费收入",
    "保险保费收入",
    "资产总额",
    "负债总额",
    "杠杆率",
)
OPERATOR_MARKERS = (
    ("not_less_than", ("不得低于", "不低于", "不少于")),
    ("not_more_than", ("不得高于", "不得超过", "不高于", "不超过")),
    ("minimum", ("最低", "下限", "至少")),
    ("maximum", ("最高", "上限", "至多")),
    ("year_on_year", ("同比",)),
    ("month_on_month", ("环比",)),
    ("compare", ("比较", "对比", "差异")),
)
QUESTION_PHRASES = (
    "请问",
    "请说明",
    "请介绍",
    "请列出",
    "是多少",
    "是什么",
    "有哪些",
    "如何",
    "吗",
>>>>>>> bf680b9d6881c682d5c0b0a3dc42cfa36a310898
)

# Direct alias to the enhanced QueryAnalyzer / TaskPlanner
parse_query = query_analyzer.analyze

<<<<<<< HEAD
__all__ = [
    "DOCUMENT_RE",
    "DOCUMENT_NUMBER_RE",
    "FULL_DATE_RE",
    "PERIOD_RE",
    "YEAR_RANGE_RE",
    "YEAR_RE",
    "VALUE_RE",
    "ISSUERS",
    "INSTITUTIONS",
    "METRICS",
    "OPERATOR_MARKERS",
    "QUESTION_PHRASES",
    "QueryAnalyzer",
    "query_analyzer",
    "analyze_query",
    "parse_query",
    "TaskPlanner",
    "task_planner",
    "extract_choice_options",
    "extract_sheet_name",
    "TaskPlan",
    "TableSource",
    "TableTarget",
    "TableCandidate",
    "TableOperand",
    "SourceConstraints",
    "ChoiceOption",
]
=======
def parse_query(question: str) -> QueryAnalysis:
    normalized = " ".join((question or "").split()).strip()
    query_type = classify_query(normalized)
    entities: dict[str, str] = {}
    filters: dict[str, str] = {}

    document_match = DOCUMENT_RE.search(normalized)
    if document_match:
        entities["document"] = document_match.group(1).strip()
        filters["title"] = entities["document"]

    document_number_match = DOCUMENT_NUMBER_RE.search(normalized)
    if document_number_match:
        entities["document_number"] = re.sub(
            r"\s+", "", document_number_match.group(0)
        )

    issuer = _first_contained(normalized, ISSUERS)
    if issuer:
        entities["issuer"] = issuer
        filters["issuer"] = issuer

    institution = _first_contained(normalized, INSTITUTIONS)
    if institution:
        entities["institution"] = institution

    subject_entity = _extract_subject_entity(normalized)
    if subject_entity:
        entities["subject_entity"] = subject_entity

    bank_tier = _extract_bank_tier(normalized)
    if bank_tier:
        entities["bank_tier"] = bank_tier

    metric = _first_contained(normalized, METRICS)
    if metric:
        entities["metric"] = metric

    clause_match = CLAUSE_RE.search(normalized)
    if clause_match:
        entities["clause_no"] = clause_match.group(0)

    operator = _extract_operator(normalized)
    if operator:
        entities["operator"] = operator

    value_match = VALUE_RE.search(normalized)
    if value_match:
        entities["value"] = re.sub(r"\s+", "", value_match.group(0))

    date_match = FULL_DATE_RE.search(normalized)
    period_match = PERIOD_RE.search(normalized)
    year_range_match = YEAR_RANGE_RE.search(normalized)
    if date_match:
        entities["date"] = date_match.group(0)
    if period_match and not year_range_match:
        entities["period"] = period_match.group(0)
        normalized_period = _normalize_period(period_match.group(0))
        if normalized_period:
            entities["normalized_period"] = normalized_period

    if year_range_match:
        entities["start_year"] = year_range_match.group("start")
        entities["end_year"] = year_range_match.group("end")

    year_match = YEAR_RE.search(normalized)
    if year_match and not year_range_match:
        filters["publish_date"] = year_match.group(0)

    preferred_chunk_type = None
    if query_type == "table_lookup":
        preferred_chunk_type = "table"
    elif query_type in {
        "regulation_fact",
        "clause_threshold",
        "business_procedure",
    }:
        preferred_chunk_type = "clause"

    keywords = _build_keywords(normalized, entities)
    return QueryAnalysis(
        question=normalized,
        query_type=query_type,
        keywords=keywords,
        filters=filters,
        entities=entities,
        preferred_chunk_type=preferred_chunk_type,
    )


def _first_contained(text: str, candidates: tuple[str, ...]) -> str:
    return next((candidate for candidate in candidates if candidate in text), "")


def _build_keywords(question: str, entities: dict[str, str]) -> list[str]:
    keywords: list[str] = []
    for key in (
        "document",
        "document_number",
        "issuer",
        "institution",
        "subject_entity",
        "bank_tier",
        "metric",
        "clause_no",
        "period",
        "date",
        "value",
    ):
        value = entities.get(key)
        if value and value not in keywords:
            keywords.append(value)

    core_question = question
    for phrase in QUESTION_PHRASES:
        core_question = core_question.replace(phrase, " ")
    core_question = PUNCTUATION_RE.sub(" ", core_question)
    core_question = " ".join(core_question.split())
    if core_question and core_question not in keywords:
        keywords.append(core_question)
    if not keywords and question:
        keywords.append(question)
    return keywords


def _extract_subject_entity(text: str) -> str:
    cleaned = re.sub(r"^(?:请问|请说明|想问|查询|帮我查一下)", "", text.strip())
    for match in ORGANIZATION_RE.finditer(cleaned):
        value = _strip_subject_context(match.group(0).strip())
        if any(marker in value for marker in ("哪个", "哪些", "哪所", "什么", "谁")):
            continue
        if value not in GENERIC_ORGANIZATIONS:
            return value
    return ""


def _strip_subject_context(value: str) -> str:
    value = re.sub(
        r"^(?:(?:19|20)\d{2}年(?:第?[一二三四1234]季度|\d{1,2}月|上半年|下半年|年末|年度)?|"
        r"第?[一二三123]档)",
        "",
        value,
    )
    return value.strip()


def _extract_operator(text: str) -> str:
    for operator, markers in OPERATOR_MARKERS:
        if any(marker in text for marker in markers):
            return operator
    return ""


def _normalize_period(period: str) -> str:
    month_match = re.search(r"年(0?[1-9]|1[0-2])月", period)
    dashed_month_match = re.search(r"-((?:0[1-9]|1[0-2]))", period)
    quarter_match = re.search(r"第?([一二三四1234])季度", period)
    q_match = re.search(r"[Qq]([1-4])", period)
    year_match = YEAR_RE.search(period)
    if not year_match:
        return ""
    if month_match:
        return f"{year_match.group(0)}-{int(month_match.group(1)):02d}"
    if dashed_month_match:
        return f"{year_match.group(0)}-{dashed_month_match.group(1)}"
    if q_match:
        return f"{year_match.group(0)}Q{q_match.group(1)}"
    if quarter_match:
        quarter_map = {"一": "1", "二": "2", "三": "3", "四": "4"}
        quarter = quarter_map.get(quarter_match.group(1), quarter_match.group(1))
        return f"{year_match.group(0)}Q{quarter}"
    return ""


def _extract_bank_tier(text: str) -> str:
    matched = _first_contained(text, BANK_TIERS)
    if not matched:
        return ""
    if "第一档" in matched:
        return "第一档商业银行"
    if "第二档" in matched:
        return "第二档商业银行"
    return "第三档商业银行"
>>>>>>> bf680b9d6881c682d5c0b0a3dc42cfa36a310898
