"""Module 4: evidence-bound answer generation and trust controls."""

from app.generation.answer_generator import generate_answer
from app.generation.prompt_builder import build_generation_prompt
from app.generation.verifier import verify_answer

__all__ = ["build_generation_prompt", "generate_answer", "verify_answer"]

