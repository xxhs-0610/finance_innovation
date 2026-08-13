from __future__ import annotations

from app.indexing.index_reader import KnowledgeBaseReader


def retrieve_evidence(question: str, top_k: int = 5) -> list[dict]:
    """Module 3 placeholder built on module-2 keyword search."""
    reader = KnowledgeBaseReader()
    return [result.to_dict() for result in reader.search(question, top_k=top_k)]

