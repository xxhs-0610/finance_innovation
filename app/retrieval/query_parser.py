from __future__ import annotations


def parse_query(question: str) -> dict:
    """Module 3 placeholder: parse question type, keywords, and filters."""
    return {
        "question": question,
        "qa_type": "unknown",
        "keywords": [question],
        "filters": {},
    }

