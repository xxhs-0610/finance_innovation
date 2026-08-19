"""Evidence-aware prompt construction for optional LLM backends."""

from __future__ import annotations

from typing import Any

from app.schemas.answer_schema import normalize_evidence


SYSTEM_INSTRUCTION = """你是银行业监管制度与统计报表问答助手。
只能使用给定证据回答，不得补充证据中没有的事实、数字、日期、文号或机构名称。
每个结论都必须在句末用 [E1] 形式引用证据。证据不足、证据冲突或问题条件不完整时，输出 REFUSE，不要猜测。
回答应简洁，优先给出结论，再说明依据和必要的风险提示。"""


def build_generation_prompt(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    max_evidence_chars: int = 1200,
) -> str:
    """Build a deterministic prompt with numbered, traceable evidence."""

    records = normalize_evidence(evidence)
    blocks: list[str] = []
    for item in records:
        source = item.get("source") or {}
        metadata = item.get("metadata") or {}
        source_bits = [
            source.get("title"),
            source.get("issuer"),
            source.get("publish_date"),
            source.get("clause_no"),
            source.get("sheet_name"),
            source.get("table_name"),
            source.get("cell_ref") or metadata.get("cell_ref"),
        ]
        source_text = " | ".join(str(bit).strip() for bit in source_bits if str(bit or "").strip())
        text = item["text"][:max_evidence_chars]
        blocks.append(f"[{item['citation_id']}] 来源：{source_text or '未提供'}\n内容：{text}")

    evidence_text = "\n\n".join(blocks) or "（无可用证据）"
    return (
        f"系统指令：\n{SYSTEM_INSTRUCTION}\n\n"
        f"用户问题：\n{str(question or '').strip()}\n\n"
        f"证据包：\n{evidence_text}\n\n"
        "请输出 JSON：{\"status\":\"answered|refused\",\"answer\":\"...\","
        "\"citations\":[\"E1\"],\"risk_tips\":[\"...\"]}"
    )


__all__ = ["SYSTEM_INSTRUCTION", "build_generation_prompt"]
