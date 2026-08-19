from __future__ import annotations

from app.generation.answer_generator import generate_answer
from app.retrieval.hybrid_retriever import retrieve


def ask(question: str) -> dict:
    """Run the formal module 3 -> module 4 pipeline."""
    response = retrieve(question)
    return generate_answer(question, response)

