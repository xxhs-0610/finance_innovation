"""DeepSeek OpenAI-compatible client for evidence-bound module 4 generation."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib import error, request

import certifi

from app.generation.prompt_builder import build_generation_prompt
from app.utils.logger import get_logger

logger = get_logger("app.generation.deepseek")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONFIG_PATH = BACKEND_ROOT / "configs" / "generation.json"

ENV_CANDIDATES = [
    REPO_ROOT / ".env",
    BACKEND_ROOT / ".env",
    Path.cwd() / ".env",
]

# Ensure environment variables from .env are loaded
try:
    from dotenv import load_dotenv
    for p in ENV_CANDIDATES:
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)
            break
except Exception:
    pass


class DeepSeekConfigError(RuntimeError):
    """Raised when DeepSeek is enabled without usable configuration."""


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek request or response is invalid."""


def deepseek_enabled() -> bool:
    return _as_bool(_setting("DEEPSEEK_ENABLED", "enabled", True))


def deepseek_api_key() -> str:
    return _env_value("DEEPSEEK_API_KEY", "").strip()


def deepseek_base_url() -> str:
    return str(_setting("DEEPSEEK_BASE_URL", "base_url", DEFAULT_BASE_URL)).strip().rstrip("/")


def deepseek_model() -> str:
    return str(_setting("DEEPSEEK_MODEL", "model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL


def deepseek_timeout_seconds() -> float:
    return _as_float(str(_setting("DEEPSEEK_TIMEOUT_SECONDS", "timeout_seconds", 45)), 45.0)


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
        logger.error("[DeepSeek] 未找到 DEEPSEEK_API_KEY 配置，无法调用大模型")
        raise DeepSeekConfigError("DEEPSEEK_API_KEY 未配置。")

    base_url = str(_setting("DEEPSEEK_BASE_URL", "base_url", DEFAULT_BASE_URL)).strip().rstrip("/")
    model = str(_setting("DEEPSEEK_MODEL", "model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    timeout = _as_float(str(_setting("DEEPSEEK_TIMEOUT_SECONDS", "timeout_seconds", 45)), 45.0)
    retries = max(0, _as_int(str(_setting("DEEPSEEK_MAX_RETRIES", "max_retries", 2)), 2))
    
    prompt = build_generation_prompt(question, evidence)
    system_msg = (
        "你是面向银行业监管制度与统计报表的可信问答专家（Answer Generator）。\n"
        "【执行前提】：当前问题与证据已通过 Evidence Verifier 充分性核验（answerable=true）。\n"
        "【核心准则】：只能依据传入的 evidence 回答，严禁使用自身记忆补充监管事实！\n"
        "【严禁红线】：\n"
        "1. 严禁猜数字、猜日期、猜比例、猜机构、猜文件名、猜文号；\n"
        "2. 严禁篡改法律效力：严禁将“可以”写成“应当”，严禁将“原则上”写成“必须”，严禁将“不得”弱化为“不建议”；\n"
        "3. 严禁忽略适用对象、前提条件和例外条件。\n"
        "【输出结构】：直接答案 -> 必要说明（简单事实不要生成冗长解释，保持简短；复杂问题再展开） -> 监管依据/数据来源。\n"
        "每个事实结论句末必须标注 [E1] 引用编号。"
    )
    # Keep the provider response machine-readable. Deterministic module-4
    # verification remains authoritative, but the model should still emit the
    # option label explicitly so API clients and evaluators can parse it.
    system_msg += (
        "\nSTRICT OUTPUT CONTRACT:\n"
        "If this is a multiple-choice question, direct_answer MUST begin with "
        "the uppercase option letter(s), e.g. 'Answer: A' or 'Answer: A,C'. "
        "Never omit the option letters. If a deterministic verification result "
        "appears in the user prompt, preserve its verified option, value, and "
        "calculation exactly; do not override it."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    endpoint = f"{base_url}/chat/completions"
    
    logger.info(
        f"[DeepSeek] 正在向大模型发起生成请求 | 模型: {model} | 端点: {endpoint} | 证据数: {len(evidence)}条 | 超时: {timeout}s"
    )

    last_error: Exception | None = None
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        try:
            response = _post_json(endpoint, api_key, body, timeout)
            answer_text = _extract_answer(response)
            duration = time.perf_counter() - t0
            logger.info(
                f"[DeepSeek] 大模型调用成功 | 耗时: {duration:.2f}s | 模型: {model} | 生成长度: {len(answer_text)} 字符"
            )
            return answer_text
        except (DeepSeekAPIError, TimeoutError, error.URLError, ssl.SSLError) as exc:
            last_error = exc
            logger.warning(
                f"[DeepSeek] 第 {attempt + 1}/{retries + 1} 次调用遇到异常: {type(exc).__name__}: {exc}"
            )
            if attempt >= retries:
                break
            time.sleep(min(2.0 * (attempt + 1), 5.0))

    logger.error(f"[DeepSeek] 大模型调用最终失败: {last_error}")
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
        # Do not load the Windows certificate store here. Some machines contain
        # malformed certificates that make OpenSSL fail with
        # ASN1: NOT_ENOUGH_DATA before the HTTPS request is even sent. Certifi's
        # maintained CA bundle gives this client a deterministic trust store
        # while keeping normal TLS certificate and hostname verification on.
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        with request.urlopen(req, timeout=timeout, context=ssl_context) as response:
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
        status = str(parsed.get("status") or "").lower()
        answer = parsed.get("answer")
        direct_answer = parsed.get("direct_answer")
        necessary_notes = parsed.get("necessary_notes")
        regulatory_basis = parsed.get("regulatory_basis")
        citations = parsed.get("citations")

        if status == "refused" and (not answer or str(answer).strip().upper() == "REFUSE"):
            return "REFUSE"

        # Assemble clean tripartite structure if direct_answer is given and answer is not explicitly detailed
        if isinstance(direct_answer, str) and direct_answer.strip():
            da = direct_answer.strip()
            nn = str(necessary_notes).strip() if necessary_notes and str(necessary_notes).strip() else ""
            rb = str(regulatory_basis).strip() if regulatory_basis and str(regulatory_basis).strip() else ""

            if not isinstance(answer, str) or not answer.strip() or answer.strip() == da:
                parts = [da]
                if nn:
                    note_prefix = "" if any(nn.startswith(p) for p in ("必要说明", "【必要说明】", "说明：", "说明:")) else "必要说明："
                    parts.append(f"{note_prefix}\n{nn}" if note_prefix else nn)
                if rb:
                    basis_prefix = "" if any(rb.startswith(p) for p in ("监管依据", "【监管依据】", "数据来源", "【数据来源】", "依据：", "依据:")) else "监管依据："
                    parts.append(f"{basis_prefix}{rb}" if basis_prefix else rb)
                answer = "\n\n".join(parts)

        if isinstance(answer, str) and answer.strip():
            answer_text = answer.strip()
            if answer_text.upper() == "REFUSE":
                return "REFUSE"
            if isinstance(citations, list) and citations and not _has_citation(answer_text):
                clean_cites = [f"[{str(item).strip(' []').upper()}]" for item in citations if str(item).strip()]
                if clean_cites:
                    answer_text = f"{answer_text} {' '.join(clean_cites)}"
            return answer_text
    return text


def _has_citation(text: str) -> bool:
    return bool(re.search(r"\[(E\d+)\]|\b(E\d+)\b", text, re.IGNORECASE))


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_value(name: str, default: str = "") -> str:
    """Read an environment variable, then fall back to local .env candidate paths."""

    if name in os.environ and os.environ[name]:
        return os.environ[name]
    for env_path in ENV_CANDIDATES:
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
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

    if env_name in os.environ and os.environ[env_name]:
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


def deepseek_grounded_regenerator(
    question: str,
    evidence: list[dict[str, Any]],
    issues: list[str] | None = None,
) -> str:
    """Generate a strictly constrained, minimal-sufficient regenerated answer when initial generation failed."""
    api_key = _env_value("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise DeepSeekConfigError("DEEPSEEK_API_KEY 未配置。")

    base_url = str(_setting("DEEPSEEK_BASE_URL", "base_url", DEFAULT_BASE_URL)).strip().rstrip("/")
    model = str(_setting("DEEPSEEK_MODEL", "model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    timeout = _as_float(str(_setting("DEEPSEEK_TIMEOUT_SECONDS", "timeout_seconds", 45)), 45.0)

    prompt = build_generation_prompt(question, evidence)
    issue_text = "；".join(issues) if issues else "初次回答存在未经支持的内容"
    system_msg = (
        "你是面向银行业监管制度与统计报表的可信受控修正专家（Grounded Regenerator）。\n"
        f"【修正指令】：上一次生成的回答未通过事实与证据校验（问题原因：{issue_text}）。\n"
        "请重新回答用户问题，【严格遵循最小充分答案原则】：\n"
        "1. 只能且必须依据给定的证据，绝对严禁使用模型自身记忆补充任何监管事实！\n"
        "2. 严禁编造任何数字、日期、比例、机构名或法条！\n"
        "3. 不要添加任何未在证据中出现的背景、原因、趋势或推测性总结！\n"
        "4. 直接给出最短、最明确的核心结论，并在句末标注引用编号（如 [E1]）。\n"
        "【输出结构】：直接答案 [E1] -> 监管依据。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    endpoint = f"{base_url}/chat/completions"
    logger.info(f"[DeepSeek] 触发 Grounded Regeneration 受控重生 | issues={issues}")
    response = _post_json(endpoint, api_key, body, timeout)
    return _extract_answer(response)


def _as_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "DeepSeekAPIError",
    "DeepSeekConfigError",
    "deepseek_enabled",
    "deepseek_generator",
    "deepseek_grounded_regenerator",
    "deepseek_api_key",
    "deepseek_base_url",
    "deepseek_model",
    "deepseek_timeout_seconds",
]
