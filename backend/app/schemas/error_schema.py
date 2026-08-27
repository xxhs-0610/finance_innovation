"""Standard Error Codes and Failure Attribution Schema (Prompt 11).

Defines granular error codes and failure attribution across the entire Q&A lifecycle:
  - AMBIGUOUS_QUERY: User input incomplete, dangling pronouns, missing required factual input
  - RETRIEVAL_FAILED: Retrieval stage failed or recalled 0 documents
  - MISSING_EVIDENCE: Valid query but knowledge base lacks supporting clauses/rules
  - MISSING_OPERAND: Table comparison/calculation missing required numeric targets or candidates
  - CONFLICTING_EVIDENCE: Mutually contradictory clauses or conflicting table metrics
  - CALCULATION_FAILED: Division by zero, illegal expression, or arithmetic error
  - OPTION_NOT_VERIFIED: Choice option lacks sufficient positive/negative evidence chain
  - INSUFFICIENT_OPTIONS: Verification failed to find required number of valid options
  - GROUNDING_FAILED: Generated answer failed post-generation factual grounding check
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

StandardErrorCode = Literal[
    "AMBIGUOUS_QUERY",
    "RETRIEVAL_FAILED",
    "MISSING_EVIDENCE",
    "MISSING_OPERAND",
    "CONFLICTING_EVIDENCE",
    "CALCULATION_FAILED",
    "OPTION_NOT_VERIFIED",
    "INSUFFICIENT_OPTIONS",
    "GROUNDING_FAILED",
]

FailureStage = Literal[
    "ROUTER",
    "PLANNER",
    "RETRIEVAL",
    "TABLE_EXECUTION",
    "OPTION_VERIFICATION",
    "INTERMEDIATE_VERIFICATION",
    "POST_VERIFICATION",
    "GENERATION",
]

ERROR_CODE_DESCRIPTIONS: dict[str, str] = {
    "AMBIGUOUS_QUERY": "用户提问不完整、存在未指明的代词或缺少业务必要输入事实，需用户澄清。",
    "RETRIEVAL_FAILED": "检索层未召回任何相关知识切片，或底层检索服务响应异常。",
    "MISSING_EVIDENCE": "已定位法规主题，但在当前知识库中缺少支持该具体条款或事实的有效依据。",
    "MISSING_OPERAND": "表格比较或算术运算缺少必要的指标候选值或操作数值，无法完成确定性计算。",
    "CONFLICTING_EVIDENCE": "知识库中检索到相互冲突的规定版本或不一致的统计数据，无法得出唯一结论。",
    "CALCULATION_FAILED": "执行程序计算时发生数学运算错误（如除以零、非法操作符或量纲不匹配）。",
    "OPTION_NOT_VERIFIED": "选择题选项在知识库中未找到充分的事实依据支持，或存在悬空子断言。",
    "INSUFFICIENT_OPTIONS": "未能选出满足题目要求数量（单选1项/多选N项）的明确支持选项。",
    "GROUNDING_FAILED": "生成内容未能通过事后证据一致性核验（存在幻觉或超出依据的陈述）。",
}

ERROR_CODE_USER_MESSAGES: dict[str, str] = {
    "AMBIGUOUS_QUERY": "您的问题表述不够明确或缺少具体的业务判断条件，请补充具体机构、指标或业务背景后再次提问。",
    "RETRIEVAL_FAILED": "系统检索未能定位到与该问题相关的制度或报表切片，请确认提问是否在监管知识库收录范围内。",
    "MISSING_EVIDENCE": "该问题属于监管问答范围，但当前知识库中未收录能够支撑可靠回答的对应条款依据。",
    "MISSING_OPERAND": "系统已定位目标表格，但未能在表格中完整提取到全部必要操作数数值，无法完成确定性比对或计算。",
    "CONFLICTING_EVIDENCE": "检索到的多份监管文件中存在相互冲突的规定或数值口径，无法给出唯一确定性结论。",
    "CALCULATION_FAILED": "表格确定性算术执行失败（数学计算异常），无法生成可靠计算结果。",
    "OPTION_NOT_VERIFIED": "经逐项条款比对，选项依据不足或未在指定监管文件中找到明确正向支持。",
    "INSUFFICIENT_OPTIONS": "选项验证未能筛选出符合题目数量要求的确定性正确答案。",
    "GROUNDING_FAILED": "回答内容在最终事实核验中未通过可信度检查（包含未充分证实的推测），系统已自动拦截。",
}


@dataclass(slots=True)
class ErrorDetail:
    """Detailed error and diagnostic context."""
    error_code: StandardErrorCode
    stage: FailureStage
    message: str = ""
    user_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.message and self.error_code in ERROR_CODE_DESCRIPTIONS:
            self.message = ERROR_CODE_DESCRIPTIONS[self.error_code]
        if not self.user_message and self.error_code in ERROR_CODE_USER_MESSAGES:
            self.user_message = ERROR_CODE_USER_MESSAGES[self.error_code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "stage": self.stage,
            "message": self.message,
            "user_message": self.user_message,
            "details": self.details,
        }
