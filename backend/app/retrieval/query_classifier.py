from __future__ import annotations

import re

from app.schemas.retrieval_schema import QueryType


SPACE_RE = re.compile(r"\s+")

AMBIGUOUS_QUESTIONS = {
    "这个是什么",
    "那个是什么",
    "怎么办",
    "什么意思",
    "有什么规定",
}
CROSS_DOCUMENT_MARKERS = (
    "综合判断",
    "对比",
    "比较",
    "分别规定",
    "是否合规",
    "能否认定",
    "多个文件",
)
THRESHOLD_MARKERS = (
    "不得低于",
    "不低于",
    "不得高于",
    "不得超过",
    "最低",
    "最高",
    "上限",
    "下限",
    "至少",
    "至多",
    "阈值",
    "比例要求",
)
PROCEDURE_MARKERS = (
    "如何办理",
    "如何管理",
    "如何申请",
    "操作流程",
    "办理流程",
    "需要哪些材料",
    "哪些步骤",
    "从哪些方面",
    "包括哪些内容",
    "包括哪些机制",
    "程序是什么",
)
TABLE_MARKERS = (
    "统计表",
    "统计报表",
    "报表",
    "指标值",
    "数值",
    "余额",
    "同比",
    "环比",
    "季度",
    "年末",
    "上半年",
    "下半年",
    "月度",
    "月份",
)
DOMAIN_MARKERS = (
    "银行", "金融", "监管", "资本", "贷款", "保险", "报表", "指标",
    "风险", "流动性", "杠杆率", "拨备", "不良",
)
OUT_OF_SCOPE_MARKERS = (
    "天气", "菜谱", "旅游攻略", "电影推荐", "游戏攻略", "写一首诗", "写代码",
)
# Explicit non-regulatory subjects should never be sent to the knowledge base.
# Lexical overlap such as two organizations both containing "finance" or
# "university" is not evidence that the question belongs to this corpus.
NON_REGULATORY_SUBJECT_MARKERS = (
    "大学",
    "学院",
    "学校",
    "校长",
    "院长",
    "教授",
    "老师",
    "天气",
    "旅游",
    "景点",
    "电影",
    "电视剧",
    "游戏",
    "菜谱",
    "食谱",
    "写诗",
    "写代码",
)
FINANCE_SCOPE_MARKERS = (
    "银行",
    "金融",
    "监管",
    "资本",
    "贷款",
    "保险",
    "证券",
    "基金",
    "信贷",
    "报表",
    "指标",
    "风险",
    "合规",
    "条款",
    "办法",
    "规定",
    "通知",
    "机构",
    "文号",
    "统计",
    "利率",
    "资产",
    "负债",
    "流动性",
    "拨备",
)
REGULATORY_CONTEXT_MARKERS = (
    "监管", "报表", "指标", "资本充足率", "贷款", "保险监管", "规定", "办法",
    "条款", "统计", "合规", "风险", "拨备", "流动性", "制度", "政策",
    "任职资格", "任职条件", "行政许可", "核准", "审批", "信息披露",
)
OPEN_DOMAIN_FACT_MARKERS = (
    "校长", "院长", "董事长", "行长是谁", "总经理", "创始人", "地址", "电话", "官网",
    "客服电话", "营业时间", "几点下班", "下班时间", "几点营业", "网点", "招聘", "校招", "工资", "薪资", "股价", "股票代码",
)
STATISTICAL_METRIC_MARKERS = (
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


def classify_query(question: str) -> QueryType:
    text = SPACE_RE.sub("", question or "").strip("，。！？?；;：:")
    if len(text) < 3 or text in AMBIGUOUS_QUESTIONS:
        return "ambiguous"
    if any(marker in text for marker in OUT_OF_SCOPE_MARKERS):
        return "unsupported"
    has_regulatory_context = any(
        marker in text for marker in REGULATORY_CONTEXT_MARKERS
    )
    if any(marker in text for marker in NON_REGULATORY_SUBJECT_MARKERS) and not has_regulatory_context:
        return "unsupported"
    if any(marker in text for marker in OPEN_DOMAIN_FACT_MARKERS) and not has_regulatory_context:
        return "unsupported"
    if any(marker in text for marker in CROSS_DOCUMENT_MARKERS):
        return "cross_document"
    if any(marker in text for marker in PROCEDURE_MARKERS):
        return "business_procedure"
    if any(marker in text for marker in THRESHOLD_MARKERS):
        return "clause_threshold"
    if any(marker in text for marker in TABLE_MARKERS) or re.search(
        r"(?:19|20)\d{2}\s*[Qq][1-4]", text
    ):
        return "table_lookup"
    if re.search(r"(?:19|20)\d{2}", text) and any(
        marker in text for marker in STATISTICAL_METRIC_MARKERS
    ):
        return "table_lookup"
    if re.search(r"(?:19|20)\d{2}(?:年(?:\d{1,2}月)?|-\d{2})", text) and any(
        marker in text for marker in ("是多少", "多少", "数值", "情况")
    ):
        return "table_lookup"
    if not any(marker in text for marker in FINANCE_SCOPE_MARKERS):
        return "unsupported"
    return "regulation_fact"
