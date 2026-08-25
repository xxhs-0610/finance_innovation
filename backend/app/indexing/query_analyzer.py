from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.indexing.text_utils import clean_text, query_tokens


QueryType = Literal["clause", "table", "mixed"]


QUESTION_WORDS = (
    "请问",
    "是多少",
    "有多少",
    "分别是多少",
    "多少",
    "哪些",
    "什么",
    "如何",
    "怎么",
    "怎样",
    "是否",
    "吗",
    "？",
    "?",
)

CLAUSE_CUES = (
    "应当",
    "应该",
    "不得",
    "不应",
    "禁止",
    "可以",
    "规定",
    "要求",
    "办法",
    "指引",
    "分级",
    "分类",
    "流程",
    "机制",
    "职责",
    "包括",
    "至少",
    "低于",
    "高于",
    "不低于",
    "不超过",
    "处置",
    "治理",
    "管理",
)

TABLE_CUES = (
    "报表",
    "情况表",
    "指标",
    "统计",
    "数据",
    "数值",
    "余额",
    "金额",
    "总资产",
    "总负债",
    "亿元",
    "万亿元",
    "同比",
    "环比",
    "月度",
    "季度",
    "年度",
    "一季度",
    "二季度",
    "三季度",
    "四季度",
)

KNOWN_TERMS = (
    "核心一级资本充足率",
    "一级资本充足率",
    "资本充足率",
    "商业银行主要监管指标",
    "商业银行主要指标",
    "数据安全事件",
    "恢复计划",
    "恢复措施",
    "现场检查",
    "非现场监测",
    "监管统计",
    "总资产",
    "总负债",
    "不良贷款率",
    "流动性比例",
    "商业银行",
    "保险公司",
    "银行业金融机构",
)

GENERIC_TERMS = {
    "多少",
    "哪些",
    "什么",
    "如何",
    "怎么",
    "怎样",
    "是否",
    "内容",
    "情况",
    "进行",
    "可以",
    "需要",
    "有关",
    "规定",
}

YEAR_RE = re.compile(r"(?:19|20)\d{2}")


@dataclass
class QueryAnalysis:
    original_query: str
    search_text: str
    query_type: QueryType
    important_terms: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    clause_score: int = 0
    table_score: int = 0
    intents: set[str] = field(default_factory=set)

    @property
    def preferred_chunk_type(self) -> str | None:
        if self.query_type in {"clause", "table"}:
            return self.query_type
        return None


def analyze_query(query: str) -> QueryAnalysis:
    original_query = clean_text(query)
    years = _unique(YEAR_RE.findall(original_query))
    clause_score = _score_cues(original_query, CLAUSE_CUES)
    table_score = _score_cues(original_query, TABLE_CUES)
    intents: set[str] = set()

    if years:
        table_score += 2
        intents.add("period")
    if any(item in original_query for item in ("多少", "是多少", "数值", "余额", "金额")):
        table_score += 2
        intents.add("value")
    if any(item in original_query for item in ("不得低于", "不低于", "不得高于", "不得超过", "至少", "最低")):
        clause_score += 4
        intents.add("threshold")
    if any(item in original_query for item in ("包括", "哪些", "什么内容", "有哪些")):
        clause_score += 3
        intents.add("list")
    if any(item in original_query for item in ("如何", "怎么", "怎样", "流程", "机制", "分级", "分类")):
        clause_score += 2
        intents.add("explain")

    if clause_score >= table_score + 2:
        query_type: QueryType = "clause"
    elif table_score >= clause_score + 2:
        query_type = "table"
    else:
        query_type = "mixed"

    search_text = normalize_search_text(original_query)
    important_terms = extract_important_terms(original_query, search_text, years)
    important_terms.extend(_query_expansions(original_query, query_type))
    important_terms = _unique(important_terms)
    if important_terms:
        search_text = clean_text(" ".join([search_text, *important_terms]))

    return QueryAnalysis(
        original_query=original_query,
        search_text=search_text or original_query,
        query_type=query_type,
        important_terms=important_terms,
        years=years,
        clause_score=clause_score,
        table_score=table_score,
        intents=intents,
    )


def normalize_search_text(query: str) -> str:
    text = clean_text(query)
    for word in QUESTION_WORDS:
        text = text.replace(word, " ")
    return clean_text(text)


def extract_important_terms(query: str, search_text: str, years: list[str] | None = None) -> list[str]:
    terms: list[str] = []
    for term in KNOWN_TERMS:
        if term in query:
            terms.append(term)
    for year in years or []:
        terms.extend([year, f"{year}年"])
    for token in query_tokens(search_text, max_tokens=40):
        if len(token) < 2:
            continue
        if token in GENERIC_TERMS:
            continue
        if token.isdigit() and token not in (years or []):
            continue
        terms.append(token)
    return _unique(terms)[:24]


def _score_cues(text: str, cues: tuple[str, ...]) -> int:
    score = 0
    for cue in cues:
        if cue in text:
            score += 2 if len(cue) >= 4 else 1
    return score


def _unique(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _query_expansions(query: str, query_type: QueryType) -> list[str]:
    expansions: list[str] = []
    if query_type == "table" and "商业银行" in query and "资本充足率" in query:
        expansions.extend(["商业银行主要监管指标", "主要监管指标情况表"])
    return expansions
