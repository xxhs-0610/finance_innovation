from __future__ import annotations


def generate_answer(question: str, evidence: list[dict]) -> dict:
    """Module 4 placeholder: return evidence-aware answer shape."""
    if not evidence:
        return {
            "status": "refused",
            "answer": "当前知识库中没有找到足够依据，建议补充问题条件或检查资料范围。",
            "evidence": [],
            "risk_tips": ["证据不足，未生成确定性答案。"],
        }
    return {
        "status": "answered",
        "answer": "已找到相关证据，后续由模块4接入大模型生成可核验答案。",
        "evidence": evidence,
        "risk_tips": [],
    }

