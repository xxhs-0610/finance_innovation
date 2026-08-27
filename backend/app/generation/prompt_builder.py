"""Evidence-aware prompt construction for optional LLM backends."""

from __future__ import annotations

from typing import Any

from app.schemas.answer_schema import normalize_evidence


SYSTEM_INSTRUCTION = """你是面向银行业监管制度与统计报表的可信问答专家（Answer Generator）。
【前置状态】：当前问题与证据已通过 Evidence Verifier 充分性核验（answerable=true）。

【核心准则】：
你【只能使用给定证据回答】（只能且必须依据传入的 evidence 回答），绝对严禁脱离证据进行自由发挥或事实外推！

【严格禁止行为（零容忍红线）】：
1. 严禁使用模型自身记忆补充监管事实、条款或数据；
2. 严禁猜数字；
3. 严禁猜日期；
4. 严禁猜比例；
5. 严禁猜机构；
6. 严禁猜文件名；
7. 严禁猜文号；
8. 严禁篡改监管制度效力级别与规范用语：
   - 严禁将“可以”写成“应当”；
   - 严禁将“原则上”写成“必须”；
   - 严禁将“不得”弱化为“不建议”；
9. 严禁忽略适用对象（如严格区分第一档、第二档、第三档商业银行或其他特定机构类型）；
10. 严禁忽略前提条件（如达标前提、前置审批要求）；
11. 严禁忽略例外条件（如豁免情形、过渡期安排）。

【回答输出结构规范】：
回答必须清晰客观、层级分明，结构尽量包含以下三部分（各部分间以空行分隔）：
1. 直接答案：开门见山给出最核心明确的结论，并在结论末尾标注引用编号（如 [E1]）；
2. 必要说明：说明适用对象、计算口径、前提条件或例外条款（如果是简单事实问题，不要生成很长的解释，保持一两句话即可；如果是复杂问题，再展开说明）；
3. 监管依据/数据来源：简要列出依据的制度文件名称、附件编号、条款号或报表表名（如：《商业银行资本管理办法》附件23 [E1]）。

【引用规则】：每个事实判断和数据结论必须严格对应证据来源编号 [E1]、[E2] 等。"""


def build_generation_prompt(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    max_evidence_chars: int = 1500,
) -> str:
    """Build a deterministic prompt with numbered, traceable evidence and strict regulatory constraints."""

    records = normalize_evidence(evidence)
    blocks: list[str] = []
    for item in records:
        source = item.get("source") or {}
        metadata = item.get("metadata") or {}
        section_path = source.get("section_path") or metadata.get("section_path") or []
        section_text = " > ".join(str(s) for s in section_path) if section_path else ""
        source_bits = [
            source.get("title"),
            section_text,
            source.get("issuer"),
            source.get("publish_date"),
            source.get("clause_no"),
            source.get("sheet_name"),
            source.get("table_name"),
            source.get("cell_ref") or metadata.get("cell_ref"),
        ]
        source_text = " | ".join(str(bit).strip() for bit in source_bits if str(bit or "").strip())
        text = item["text"][:max_evidence_chars]
        derived_values = metadata.get("derived_values")
        derived_text = ""
        if isinstance(derived_values, list):
            explanations = [
                str(value.get("explanation"))
                for value in derived_values
                if isinstance(value, dict) and value.get("explanation")
            ]
            if explanations:
                derived_text = "\n【确定性换算】：" + "；".join(explanations)
        blocks.append(
            f"[{item['citation_id']}] 来源：{source_text or '未提供'}\n"
            f"内容：{text}{derived_text}"
        )

    evidence_text = "\n\n".join(blocks) or "（无可用证据）"
    return (
        f"【系统角色与指令】：\n{SYSTEM_INSTRUCTION}\n\n"
        f"【用户问题】：\n{str(question or '').strip()}\n\n"
        f"【可信证据包（Evidence）】：\n{evidence_text}\n\n"
        "【关键约束】：\n"
        "1. 表格证据如包含“确定性换算”，必须原样优先使用换算后的展示值，不得给原始存储值直接添加百分号。\n"
        "2. 只能依据上述证据回答，严禁使用模型自身记忆补充监管事实，禁止猜数字、猜日期、猜比例、猜机构、猜文件名、猜文号。\n"
        "3. 严禁改动“可以/应当/原则上/必须/不得”等法律效力语调。\n"
        "4. 严禁忽略适用对象、前提条件和例外条件。\n"
        "5. 输出结构尽量为：直接答案 -> 必要说明（简单事实不要生成冗长解释，保持简短；复杂问题再展开） -> 监管依据/数据来源。\n\n"
        "【输出格式】：请输出合法 JSON：{\"status\":\"answered|refused\",\"direct_answer\":\"...[E1]\",\"necessary_notes\":\"...\",\"regulatory_basis\":\"...[E1]\",\"answer\":\"...\",\"citations\":[\"E1\"],\"risk_tips\":[]}"
    )


__all__ = ["SYSTEM_INSTRUCTION", "build_generation_prompt"]
