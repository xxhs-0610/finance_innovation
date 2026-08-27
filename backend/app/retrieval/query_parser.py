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
from app.schemas.retrieval_schema import QueryAnalysis, QueryType
from app.schemas.task_plan_schema import (
    ChoiceOption,
    SourceConstraints,
    TableCandidate,
    TableOperand,
    TableSource,
    TableTarget,
    TaskPlan,
)

# Direct alias to the enhanced QueryAnalyzer / TaskPlanner
parse_query = query_analyzer.analyze

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
