from __future__ import annotations

from app.generation.answer_generator import generate_answer
from app.retrieval.hybrid_retriever import retrieve_evidence


def ask(question: str) -> dict:
    """Temporary callable API entry until FastAPI is added by module 5."""
    evidence = retrieve_evidence(question)
    return generate_answer(question, evidence)

