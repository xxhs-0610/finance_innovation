"""RAG Business Service Layer.
Orchestrates Query Understanding, Hybrid Retrieval, Evidence Refinement, Generation, and Hallucination Verification.
"""
from __future__ import annotations

import time
from typing import Any

from app.generation.answer_generator import generate_answer
from app.generation.deepseek_client import deepseek_enabled, deepseek_generator
from app.retrieval.hybrid_retriever import retrieve


class RAGService:
    """Core RAG pipeline service orchestrator."""

    def retrieve(self, question: str, top_k: int = 5):
        """Execute Module 3 hybrid retrieval."""
        return retrieve(question, top_k=top_k)

    def ask(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """Execute end-to-end Module 3 Retrieval -> Module 4 Verified Generation."""
        q = question.strip()
        if not q:
            raise ValueError("问题不能为空")

        t0 = time.perf_counter()
        retrieval_response = self.retrieve(q, top_k=top_k)
        t1 = time.perf_counter()

        generator = deepseek_generator if deepseek_enabled() else None
        answer_result = generate_answer(q, retrieval_response, generator=generator)
        t2 = time.perf_counter()

        retrieval_ms = int((t1 - t0) * 1000)
        gen_ms = int((t2 - t1) * 1000)

        if "diagnostics" not in answer_result or not isinstance(answer_result["diagnostics"], dict):
            answer_result["diagnostics"] = {}
        answer_result["diagnostics"]["retrieval_latency_ms"] = retrieval_ms
        answer_result["diagnostics"]["generation_latency_ms"] = gen_ms
        answer_result["diagnostics"]["total_latency_ms"] = retrieval_ms + gen_ms

        return answer_result


rag_service = RAGService()
