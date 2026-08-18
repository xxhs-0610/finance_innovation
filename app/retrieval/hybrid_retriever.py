from __future__ import annotations

from app.indexing.index_reader import KnowledgeBaseReader


def retrieve_evidence(
    question: str,
    top_k: int = 5,
    *,
    db_path: str = "data/processed/kb_rebuild/metadata.db",
    index_dir: str = "indexes/kb_rebuild",
    mode: str = "hybrid",
) -> list[dict]:
    """Module-3 friendly evidence retrieval entrypoint.

    Module 2 owns the local indexes. Module 3 can call this function first, then
    add its own query understanding, filtering and final reranking logic.
    """
    reader = KnowledgeBaseReader(db_path, vector_index_dir=index_dir)
    if mode == "bm25":
        results = reader.search(question, top_k=top_k)
    elif mode == "vector":
        results = reader.vector_search(question, top_k=top_k)
    else:
        results = reader.hybrid_search(question, top_k=top_k)
    return [result.to_dict() for result in results]
