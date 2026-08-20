"""DeepSeek OpenAI-compatible client for evidence-bound module 4 generation."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib import error, request

from app.generation.prompt_builder import build_generation_prompt


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONFIG_PATH = PROJECT_ROOT / "configs" / "generation.json"
LOCAL_ENV_PATH = PROJECT_ROOT / ".env"


class DeepSeekConfigError(RuntimeError):
    """Raised when DeepSeek is enabled without usable configuration."""


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek request or response is invalid."""


def deepseek_enabled() -> bool:
    return _as_bool(_setting("DEEPSEEK_ENABLED", "enabled", False))


def deepseek_generator(
    question: str,
    evidence: list[dict[str, Any]],
) -> str:
    """Generate an answer through DeepSeek and return only answer text.

    The caller remains responsible for deterministic verification. The model is
    given the same evidence-aware prompt used by the optional LLM adapter.
    """

    api_key = _env_value("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise DeepSeekConfigError("DEEPSEEK_API_KEY 未配置。")

    base_url = str(_setting("DEEPSEEK_BASE_URL", "base_url", DEFAULT_BASE_URL)).strip().rstrip("/")
    model = str(_setting("DEEPSEEK_MODEL", "model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    timeout = _as_float(str(_setting("DEEPSEEK_TIMEOUT_SECONDS", "timeout_seconds", 45)), 45.0)
    retries = max(0, _as_int(str(_setting("DEEPSEEK_MAX_RETRIES", "max_retries", 2)), 2))
    prompt = build_generation_prompt(question, evidence)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你必须严格遵守证据约束，只输出可由证据支持的答案。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    endpoint = f"{base_url}/chat/completions"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = _post_json(endpoint, api_key, body, timeout)
            return _extract_answer(response)
        except (DeepSeekAPIError, TimeoutError, error.URLError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2.0 * (attempt + 1), 5.0))
    raise DeepSeekAPIError(f"DeepSeek 调用失败：{last_error}")


def _post_json(endpoint: str, api_key: str, body: bytes, timeout: float) -> dict[str, Any]:
    req = request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise DeepSeekAPIError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError:
        raise
    except TimeoutError:
        raise
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeepSeekAPIError("DeepSeek 返回了无法解析的 JSON。") from exc
    if not isinstance(data, dict):
        raise DeepSeekAPIError("DeepSeek 返回格式不是 JSON 对象。")
    return data


def _extract_answer(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DeepSeekAPIError("DeepSeek 返回中缺少 choices。")
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekAPIError("DeepSeek 返回中缺少 message.content。")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, Mapping):
        answer = parsed.get("answer")
        status = str(parsed.get("status") or "").lower()
        if status == "refused" and not answer:
            return "REFUSE"
        if isinstance(answer, str):
            answer_text = answer.strip()
            citations = parsed.get("citations")
            if isinstance(citations, list) and citations and not _has_citation(answer_text):
                citation_text = " ".join(
                    f"[{str(item).strip().upper()}]"
                    for item in citations
                    if str(item).strip()
                )
                if citation_text:
                    answer_text = f"{answer_text} {citation_text}"
            return answer_text
    return text


def _has_citation(text: str) -> bool:
    return bool(re.search(r"\[(E\d+)\]|\b(E\d+)\b", text, re.IGNORECASE))


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_value(name: str, default: str = "") -> str:
    """Read an environment variable, then fall back to the local ignored .env."""

    if name in os.environ:
        return os.environ[name]
    if not LOCAL_ENV_PATH.exists():
        return default
    try:
        lines = LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    return default


def _setting(env_name: str, config_name: str, default: Any) -> Any:
    """Resolve shared config with deployment env and local .env overrides."""

    if env_name in os.environ:
        return os.environ[env_name]
    local_value = _env_value(env_name, "")
    if local_value:
        return local_value
    config = _load_public_config().get("deepseek", {})
    if isinstance(config, Mapping) and config_name in config:
        return config[config_name]
    return default


def _load_public_config() -> dict[str, Any]:
    if not PUBLIC_CONFIG_PATH.exists():
        return {}
    try:
        value = json.loads(PUBLIC_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["DeepSeekAPIError", "DeepSeekConfigError", "deepseek_enabled", "deepseek_generator"]
