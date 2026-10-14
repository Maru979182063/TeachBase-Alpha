from __future__ import annotations

import email.utils
import base64
import json
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


DEFAULT_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
DEFAULT_EMBEDDING_API_URL = "https://ark.cn-beijing.volces.com/api/v3/embeddings"


@dataclass(frozen=True)
class ModelTransportSettings:
    max_connections: int = 8
    max_keepalive_connections: int = 8
    requests_per_second: float = 2.0
    burst: int = 4
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 20.0
    retry_jitter: str = "full"
    circuit_breaker_failures: int = 8
    circuit_breaker_cooldown_seconds: float = 30.0


class TokenBucket:
    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = max(float(rate), 0.001)
        self.capacity = max(int(capacity), 1)
        self.tokens = float(self.capacity)
        self.updated_at = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self.updated_at)
                self.tokens = min(float(self.capacity), self.tokens + elapsed * self.rate)
                self.updated_at = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait_seconds = (1.0 - self.tokens) / self.rate
            time.sleep(wait_seconds)


class CircuitBreaker:
    def __init__(self, failure_limit: int, cooldown_seconds: float) -> None:
        self.failure_limit = max(1, int(failure_limit))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.lock = threading.Lock()

    def before_request(self) -> float:
        with self.lock:
            remaining = self.open_until - time.monotonic()
            if remaining > 0:
                return remaining
            if self.open_until:
                self.open_until = 0.0
                self.consecutive_failures = 0
            return 0.0

    def record_success(self) -> None:
        with self.lock:
            self.consecutive_failures = 0
            self.open_until = 0.0

    def record_retryable_failure(self) -> None:
        with self.lock:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.failure_limit:
                self.open_until = time.monotonic() + self.cooldown_seconds


class ModelClientState:
    def __init__(self, settings: ModelTransportSettings, transport: httpx.BaseTransport | None = None) -> None:
        limits = httpx.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        )
        self.client = httpx.Client(limits=limits, transport=transport)
        self.semaphore = threading.BoundedSemaphore(settings.max_connections)
        self.limiter = TokenBucket(settings.requests_per_second, settings.burst)
        self.settings = settings
        self.breakers: dict[str, CircuitBreaker] = {}
        self.breakers_lock = threading.Lock()

    def breaker_for(self, api_url: str) -> CircuitBreaker:
        # 对话和 embedding 端点分别熔断，避免一个端点故障拖垮另一条链路。
        with self.breakers_lock:
            breaker = self.breakers.get(api_url)
            if breaker is None:
                breaker = CircuitBreaker(
                    self.settings.circuit_breaker_failures,
                    self.settings.circuit_breaker_cooldown_seconds,
                )
                self.breakers[api_url] = breaker
            return breaker

    def close(self) -> None:
        self.client.close()


_SETTINGS = ModelTransportSettings()
_CLIENT_STATE: ModelClientState | None = None
_CLIENT_STATE_LOCK = threading.Lock()
_TEST_TRANSPORT: httpx.BaseTransport | None = None


def configure_model_transport(
    settings: ModelTransportSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    global _SETTINGS, _CLIENT_STATE, _TEST_TRANSPORT
    with _CLIENT_STATE_LOCK:
        if _CLIENT_STATE is not None:
            _CLIENT_STATE.close()
        _SETTINGS = settings
        _TEST_TRANSPORT = transport
        _CLIENT_STATE = None


def close_model_transport() -> None:
    global _CLIENT_STATE
    with _CLIENT_STATE_LOCK:
        if _CLIENT_STATE is not None:
            _CLIENT_STATE.close()
        _CLIENT_STATE = None


def _client_state() -> ModelClientState:
    global _CLIENT_STATE
    with _CLIENT_STATE_LOCK:
        if _CLIENT_STATE is None:
            _CLIENT_STATE = ModelClientState(_SETTINGS, transport=_TEST_TRANSPORT)
        return _CLIENT_STATE


def _escape_invalid_json_backslashes(text: str) -> str:
    """只修复 JSON 字符串中的非法反斜杠，不改变字段和值的语义。"""
    valid_simple_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t"}
    hex_digits = set("0123456789abcdefABCDEF")
    output: list[str] = []
    in_string = False
    index = 0

    while index < len(text):
        char = text[index]
        if char == '"':
            # 只有未被奇数个反斜杠转义的引号才切换字符串状态。
            slash_count = 0
            cursor = index - 1
            while cursor >= 0 and text[cursor] == "\\":
                slash_count += 1
                cursor -= 1
            if slash_count % 2 == 0:
                in_string = not in_string
            output.append(char)
            index += 1
            continue

        if in_string and char == "\\":
            next_char = text[index + 1] if index + 1 < len(text) else ""
            valid_unicode_escape = (
                next_char == "u"
                and index + 5 < len(text)
                and all(item in hex_digits for item in text[index + 2 : index + 6])
            )
            if next_char not in valid_simple_escapes and not valid_unicode_escape:
                output.append("\\\\")
                index += 1
                continue

        output.append(char)
        index += 1

    return "".join(output)


def _load_json_object(text: str) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as first_error:
        repaired = _escape_invalid_json_backslashes(text)
        if repaired == text:
            return None, str(first_error)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError as repaired_error:
            return None, str(repaired_error)
    return payload if isinstance(payload, dict) else None, "" if isinstance(payload, dict) else "json_not_object"


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    clean = str(text or "").strip()
    payload, error = _load_json_object(clean)
    if payload is not None or not error:
        return payload, error

    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        return _load_json_object(clean[start : end + 1])
    return None, error


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = str(response.headers.get("Retry-After", "") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    cap = min(_SETTINGS.retry_max_seconds, _SETTINGS.retry_base_seconds * (2 ** max(0, attempt - 1)))
    delay = random.uniform(0.0, cap) if _SETTINGS.retry_jitter == "full" else cap
    retry_after = _retry_after_seconds(response) if response is not None else None
    return max(delay, retry_after or 0.0)


def _post_json(
    *,
    api_url: str,
    api_key: str,
    body: dict[str, Any],
    timeout: float,
    attempts: int,
) -> tuple[httpx.Response | None, list[dict[str, Any]], str]:
    state = _client_state()
    breaker = state.breaker_for(api_url)
    attempt_rows: list[dict[str, Any]] = []
    last_error = "unknown_error"
    for attempt in range(1, max(1, attempts) + 1):
        breaker_wait = breaker.before_request()
        if breaker_wait > 0:
            return None, attempt_rows, "circuit_open"

        state.limiter.acquire()
        try:
            with state.semaphore:
                response = state.client.post(
                    api_url,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=httpx.Timeout(timeout),
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = type(exc).__name__
            attempt_rows.append(
                {"attempt": attempt, "error": last_error, "message": str(exc)[:2000], "retryable": True}
            )
            breaker.record_retryable_failure()
            if attempt < attempts:
                time.sleep(_retry_delay(attempt))
                continue
            return None, attempt_rows, last_error

        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"http_{response.status_code}"
            attempt_rows.append(
                {
                    "attempt": attempt,
                    "error": last_error,
                    "http_status": response.status_code,
                    "retryable": True,
                    "body_preview": response.text[:2000],
                }
            )
            breaker.record_retryable_failure()
            if attempt < attempts:
                time.sleep(_retry_delay(attempt, response))
                continue
            return response, attempt_rows, last_error

        if response.status_code >= 400:
            breaker.record_success()
            return response, [
                {
                    "attempt": attempt,
                    "error": f"http_{response.status_code}",
                    "http_status": response.status_code,
                    "retryable": False,
                    "body_preview": response.text[:2000],
                }
            ], f"http_{response.status_code}"

        breaker.record_success()
        return response, attempt_rows, ""
    return None, attempt_rows, last_error


def call_json_model(
    *,
    api_key: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    image_paths: list[Path] | None = None,
    model: str = DEFAULT_MODEL,
    api_url: str = DEFAULT_API_URL,
    timeout: float = 120,
    max_tokens: int = 4000,
    retries: int = 2,
    reasoning_effort: str | None = None,
    validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    few_shots: list[tuple[dict[str, Any], dict[str, Any]]] | None = None,
    repair_invalid_output: bool = False,
) -> dict[str, Any]:
    # 图片作为真正的多模态内容发送，不能只把本地路径写进文字提示。
    content: Any = json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    if image_paths:
        content = [{"type": "text", "text": content}]
        for path in image_paths:
            path = Path(path)
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
            if not mime:
                raise ValueError(f"不支持的模型图片格式：{path.suffix}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for example_input, example_output in few_shots or []:
        messages.extend(
            [
                {
                    "role": "user",
                    "content": json.dumps(example_input, ensure_ascii=False, separators=(",", ":")),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(example_output, ensure_ascii=False, separators=(",", ":")),
                },
            ]
        )
    messages.append({"role": "user", "content": content})

    body: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    started = time.time()
    attempt_budget = max(1, int(retries) + 1)
    consumed_attempts = 0
    attempt_rows: list[dict[str, Any]] = []
    last_raw: dict[str, Any] = {}
    last_content = ""
    last_error = "unknown_error"

    while consumed_attempts < attempt_budget:
        response, transport_rows, transport_error = _post_json(
            api_url=api_url,
            api_key=api_key,
            body=body,
            timeout=timeout,
            attempts=attempt_budget - consumed_attempts,
        )
        for row in transport_rows:
            normalized = dict(row)
            normalized["attempt"] = consumed_attempts + int(row.get("attempt", 1))
            attempt_rows.append(normalized)

        if response is None or response.status_code >= 400:
            consumed_attempts += len(transport_rows)
            last = attempt_rows[-1] if attempt_rows else {}
            return {
                "called": True,
                "ok": False,
                "latency_seconds": round(time.time() - started, 3),
                "attempt_count": consumed_attempts,
                "attempts": attempt_rows,
                "http_status": last.get("http_status"),
                "error": transport_error,
                "body_preview": last.get("body_preview"),
                "message": last.get("message"),
                "reasoning_effort": reasoning_effort or "provider_default",
                "parsed": None,
                "parse_error": transport_error,
            }

        # transport_rows 只记录失败请求，当前成功响应也占用一次尝试。
        consumed_attempts += len(transport_rows) + 1
        parse_error = ""
        try:
            raw = response.json()
            content = str(raw["choices"][0]["message"]["content"])
            last_raw = raw
            last_content = content
            parsed, parse_error = extract_json(content)
            if parsed is not None and validator is not None:
                parsed = validator(parsed)
        except Exception as exc:
            parsed = None
            parse_error = f"contract_or_response_error: {exc}"

        if parsed is not None and not parse_error:
            return {
                "called": True,
                "ok": True,
                "latency_seconds": round(time.time() - started, 3),
                "attempt_count": consumed_attempts,
                "attempts": attempt_rows,
                "usage": last_raw.get("usage") or {},
                "reasoning_effort": reasoning_effort or "provider_default",
                "raw_response": last_raw,
                "raw_content": last_content,
                "parsed": parsed,
                "parse_error": "",
            }

        last_error = parse_error or "invalid_model_json"
        attempt_rows.append(
            {
                "attempt": consumed_attempts,
                "error": "invalid_model_output",
                "message": last_error[:2000],
                "retryable": consumed_attempts < attempt_budget,
            }
        )
        if consumed_attempts < attempt_budget:
            if repair_invalid_output and last_content:
                body["messages"].extend(
                    [
                        {"role": "assistant", "content": last_content},
                        {
                            "role": "user",
                            "content": (
                                "上一输出未通过 JSON 合同校验。只修复结构、字段名、枚举值、固定分数、"
                                "合计或标签映射错误；保留已有题意判断和证据，不重新发挥，不输出解释。"
                                f"\n校验错误：{last_error[:1800]}"
                            ),
                        },
                    ]
                )
            time.sleep(_retry_delay(consumed_attempts))

    return {
        "called": True,
        "ok": False,
        "latency_seconds": round(time.time() - started, 3),
        "attempt_count": consumed_attempts,
        "attempts": attempt_rows,
        "error": "invalid_model_output",
        "message": last_error[:2000],
        "reasoning_effort": reasoning_effort or "provider_default",
        "raw_response": last_raw,
        "raw_content": last_content,
        "parsed": None,
        "parse_error": last_error,
    }


def call_embeddings(
    *,
    api_key: str,
    api_url: str,
    model: str,
    texts: list[str],
    timeout: float = 120,
    retries: int = 2,
) -> dict[str, Any]:
    started = time.time()
    response, attempts, error = _post_json(
        api_url=api_url,
        api_key=api_key,
        body={"model": model, "input": texts},
        timeout=timeout,
        attempts=max(1, retries + 1),
    )
    if response is None or response.status_code >= 400:
        last = attempts[-1] if attempts else {}
        return {
            "ok": False,
            "latency_seconds": round(time.time() - started, 3),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "http_status": last.get("http_status"),
            "error": error,
            "message": last.get("message"),
        }
    try:
        raw = response.json()
        embeddings = [item.get("embedding") for item in raw.get("data", [])]
    except Exception as exc:
        return {
            "ok": False,
            "latency_seconds": round(time.time() - started, 3),
            "attempt_count": max(1, len(attempts) + 1),
            "attempts": attempts,
            "error": type(exc).__name__,
            "message": str(exc)[:2000],
        }
    if len(embeddings) != len(texts) or not all(isinstance(item, list) for item in embeddings):
        return {
            "ok": False,
            "latency_seconds": round(time.time() - started, 3),
            "attempt_count": max(1, len(attempts) + 1),
            "attempts": attempts,
            "error": "invalid_embedding_response",
            "raw_response": raw,
        }
    return {
        "ok": True,
        "latency_seconds": round(time.time() - started, 3),
        "attempt_count": max(1, len(attempts) + 1),
        "attempts": attempts,
        "usage": raw.get("usage") or {},
        "embeddings": embeddings,
        "raw_response": raw,
    }
