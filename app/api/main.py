from __future__ import annotations

from app.generation.answer_generator import generate_answer
from app.generation.deepseek_client import deepseek_enabled, deepseek_generator
from app.retrieval.hybrid_retriever import retrieve


def ask(question: str) -> dict:
    """Run the formal module 3 -> module 4 pipeline."""
    response = retrieve(question)
    generator = deepseek_generator if deepseek_enabled() else None
    return generate_answer(question, response, generator=generator)

