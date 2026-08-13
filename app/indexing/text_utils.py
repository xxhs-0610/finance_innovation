from __future__ import annotations

import re
from typing import Any


SPACE_RE = re.compile(r"\s+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
TOKEN_RE = re.compile(r"[0-9A-Za-z_.%-]+|[\u4e00-\u9fff]+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return SPACE_RE.sub(" ", str(value).strip())


def join_non_empty(parts: list[str], sep: str = " ") -> str:
    return sep.join(part for part in (clean_text(item) for item in parts) if part)


def normalize_section_path(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    return [item.strip() for item in re.split(r"[>/|]", text) if item.strip()]


def stable_id_part(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", text)
    return text.strip("_") or "unknown"


def cjk_ngrams(text: str, min_n: int = 2, max_n: int = 8) -> list[str]:
    grams: list[str] = []
    seen: set[str] = set()
    for match in CJK_RE.finditer(clean_text(text)):
        segment = match.group(0)
        upper = min(max_n, len(segment))
        for size in range(min_n, upper + 1):
            for start in range(0, len(segment) - size + 1):
                gram = segment[start : start + size]
                if gram not in seen:
                    seen.add(gram)
                    grams.append(gram)
    return grams


def augment_for_fts(text: str) -> str:
    return join_non_empty([text, " ".join(cjk_ngrams(text))])


def query_tokens(text: str, max_tokens: int = 80) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(clean_text(text)):
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    for gram in cjk_ngrams(text):
        if gram and gram not in seen:
            seen.add(gram)
            tokens.append(gram)
    tokens.sort(key=len, reverse=True)
    return tokens[:max_tokens]
