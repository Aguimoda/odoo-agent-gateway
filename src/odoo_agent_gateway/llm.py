"""Client for OpenAI-compatible Chat Completions APIs, with failures explained (ADR 0017).

Streams the answer token by token, assembles tool calls, classifies every failure into a
small set of kinds, retries only what is worth retrying and only before any text was
streamed, and never follows redirects (a key is only sent to the configured URL).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx2

logger = logging.getLogger(__name__)

KINDS = (
    "rate_limited",
    "quota_exhausted",
    "auth_failed",
    "model_unavailable",
    "context_too_long",
    "provider_unavailable",
    "bad_request",
)

MESSAGES = {
    "rate_limited": "The provider's per-minute limit was reached.",
    "quota_exhausted": "The provider's daily quota is used up.",
    "auth_failed": "The provider did not accept the API key.",
    "model_unavailable": "The provider says this model is not available.",
    "context_too_long": "The conversation is too long for this model.",
    "provider_unavailable": "The provider is down or too slow right now.",
    "bad_request": "The provider refused the request.",
}

_QUOTA_HINTS = ("per day", "(tpd)", "(rpd)", "quota", "daily")
_CONTEXT_HINTS = (
    "context_length",
    "context length",
    "maximum context",
    "too long",
    "reduce the length",
    "too many tokens",
    "request too large",
)
_MODEL_HINTS = ("decommissioned", "does not exist", "model not found", "unknown model")

RETRY_WAITS = (0.5, 1.5)  # provider_unavailable, before any text was streamed
MAX_WAITED_RETRY_AFTER = 5.0

Sleep = Callable[[float], Awaitable[None]]
OnToken = Callable[[str], Awaitable[None]]


class ProviderFailure(Exception):
    """A classified provider failure. The message is ours, never the provider's text."""

    def __init__(
        self,
        kind: str,
        retry_after: float | None = None,
        status: int | None = None,
        code: str | None = None,
    ):
        super().__init__(MESSAGES[kind])
        self.kind = kind
        self.message = MESSAGES[kind]
        self.retry_after = retry_after
        self.status = status
        self.code = code  # the provider's short error code, for diagnosis (ADR 0020)

    def __repr__(self) -> str:
        return f"ProviderFailure({self.kind!r}, retry_after={self.retry_after!r})"


@dataclass(frozen=True)
class Target:
    """One model on one provider, with its decrypted key, for a single turn."""

    model_id: int
    provider_id: int
    provider: str
    model: str
    label: str
    base_url: str
    api_key: str = field(repr=False)


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return max(float(value), 0.0)
            except ValueError:
                return None
    return None


_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,60}$")


def _error_code(body: str, status: int) -> str:
    """The provider's short error code (never its message): safe to store and log."""
    try:
        data: Any = json.loads(body)
    except (ValueError, TypeError):
        return str(status)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return str(status)
    error = data.get("error")
    if not isinstance(error, dict):
        errors = data.get("errors")
        error = errors[0] if isinstance(errors, list) and errors else data
    if not isinstance(error, dict):
        return str(status)
    for key in ("status", "code", "type"):
        value = error.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value)
            if text != str(status) or key == "code":
                return text if _CODE.match(text) else str(status)
    return str(status)


def classify_stream_error(error: Any) -> ProviderFailure:
    """An `error` event inside a stream, classified like an HTTP error (ADR 0020)."""
    raw = error if isinstance(error, dict) else {"message": str(error)}
    code = raw.get("code")
    status = raw.get("status_code") or (code if isinstance(code, int) else None)
    text = json.dumps(raw).lower()
    if not isinstance(status, int) or not 400 <= status < 600:
        if "rate limit" in text or "rate_limit" in text or "429" in text:
            status = 429
        elif any(w in text for w in ("overloaded", "unavailable", "timeout", "internal", "server")):
            status = 503
        else:
            status = 400
    return classify_http(status, json.dumps({"error": raw}), {})


def classify_http(status: int, body: str, headers: Mapping[str, str]) -> ProviderFailure:
    text = (body or "").lower()
    retry_after = _retry_after(headers)
    if status in (401, 403):
        kind = "auth_failed"
    elif status == 404:
        kind = "model_unavailable"
    elif status == 429:
        kind = "quota_exhausted" if any(h in text for h in _QUOTA_HINTS) else "rate_limited"
    elif status == 413 or (status in (400, 422) and any(h in text for h in _CONTEXT_HINTS)):
        kind = "context_too_long"
    elif status in (400, 422) and any(h in text for h in _MODEL_HINTS):
        kind = "model_unavailable"
    elif status == 408 or status >= 500:
        kind = "provider_unavailable"
    else:
        kind = "bad_request"
    return ProviderFailure(
        kind, retry_after=retry_after, status=status, code=_error_code(body, status)
    )


class CircuitBreaker:
    """Per provider: opens after `threshold` consecutive failures, one trial after `cooldown`."""

    def __init__(
        self,
        threshold: int = 3,
        cooldown: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._trial: set[str] = set()

    def open_for(self, provider: str) -> float:
        """Seconds until a trial call is allowed; 0 when the breaker is closed."""
        opened = self._opened_at.get(provider)
        if opened is None:
            return 0.0
        return max(self._cooldown - (self._clock() - opened), 0.0)

    def allow(self, provider: str) -> bool:
        if provider not in self._opened_at:
            return True
        if provider in self._trial or self.open_for(provider) > 0:
            return False
        self._trial.add(provider)
        return True

    def success(self, provider: str) -> None:
        self._failures.pop(provider, None)
        self._opened_at.pop(provider, None)
        self._trial.discard(provider)

    def failure(self, provider: str) -> None:
        if provider in self._trial:  # the trial call failed: open again
            self._trial.discard(provider)
            self._opened_at[provider] = self._clock()
            return
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= self._threshold:
            self._opened_at[provider] = self._clock()


class ChatClient:
    def __init__(self, http: httpx2.AsyncClient, sleep: Sleep = anyio.sleep) -> None:
        self._http = http
        self._sleep = sleep

    async def complete(
        self,
        target: Target,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_token: OnToken,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": target.model,
            "messages": messages,
            "temperature": 0,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        streamed = False

        async def token(text: str) -> None:
            nonlocal streamed
            streamed = True
            await on_token(text)

        waits = list(RETRY_WAITS)
        waited_rate_limit = False
        while True:
            try:
                return await self._attempt(target, body, token)
            except ProviderFailure as failure:
                if streamed:
                    raise
                if failure.kind == "provider_unavailable" and waits:
                    await self._sleep(waits.pop(0))
                    continue
                if (
                    failure.kind == "rate_limited"
                    and not waited_rate_limit
                    and failure.retry_after is not None
                    and failure.retry_after <= MAX_WAITED_RETRY_AFTER
                ):
                    waited_rate_limit = True
                    await self._sleep(failure.retry_after)
                    continue
                raise

    async def _attempt(self, target: Target, body: dict[str, Any], on_token: OnToken) -> ChatResult:
        url = target.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {target.api_key}", "Accept": "text/event-stream"}
        try:
            async with self._http.stream(
                "POST", url, json=body, headers=headers, timeout=httpx2.Timeout(60, connect=10)
            ) as response:
                if response.status_code >= 300:
                    text = (await response.aread()).decode("utf-8", "replace")[:4000]
                    failure = classify_http(response.status_code, text, response.headers)
                    # The provider's own reason, for diagnosis. The key is never part of it.
                    logger.warning(
                        "provider refused: %s %s %s", failure.kind, response.status_code, text[:500]
                    )
                    raise failure
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    return await _from_json(json.loads(await response.aread()), on_token)
                return await _from_stream(response, on_token)
        except httpx2.HTTPError:
            raise ProviderFailure("provider_unavailable") from None

    async def list_models(self, base_url: str, api_key: str) -> list[str]:
        url = base_url.rstrip("/") + "/models"
        try:
            response = await self._http.get(
                url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20
            )
        except httpx2.HTTPError:
            raise ProviderFailure("provider_unavailable") from None
        if response.status_code >= 300:
            raise classify_http(response.status_code, response.text[:4000], response.headers)
        try:
            data = response.json().get("data") or []
            return sorted(str(item["id"]) for item in data if isinstance(item, dict))
        except (ValueError, KeyError, AttributeError):
            raise ProviderFailure("bad_request") from None


def _usage(chunk: dict[str, Any], result: ChatResult) -> None:
    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
    if isinstance(usage, dict):
        result.prompt_tokens = usage.get("prompt_tokens", result.prompt_tokens)
        result.completion_tokens = usage.get("completion_tokens", result.completion_tokens)


async def _from_json(data: dict[str, Any], on_token: OnToken) -> ChatResult:
    if "error" in data:
        raise ProviderFailure("provider_unavailable")
    message = data["choices"][0]["message"]
    result = ChatResult(
        content=str(message.get("content") or ""),
        tool_calls=message.get("tool_calls") or [],
        finish_reason=data["choices"][0].get("finish_reason"),
    )
    _usage(data, result)
    if result.content:
        await on_token(result.content)
    return result


async def _from_stream(response: httpx2.Response, on_token: OnToken) -> ChatResult:
    result = ChatResult()
    calls: dict[int, dict[str, Any]] = {}
    parts: list[str] = []
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in chunk:
            logger.warning("provider error in stream: %s", json.dumps(chunk["error"])[:500])
            raise classify_stream_error(chunk["error"])
        _usage(chunk, result)
        for choice in chunk.get("choices") or []:
            result.finish_reason = choice.get("finish_reason") or result.finish_reason
            change = choice.get("delta") or {}
            piece_text = change.get("content")
            # Some providers (Cloudflare's Llama) stream a number as the content piece.
            if text := ("" if piece_text is None else str(piece_text)):
                parts.append(text)
                await on_token(text)
            for piece in change.get("tool_calls") or []:
                call = calls.setdefault(
                    piece.get("index", 0),
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                call["id"] = piece.get("id") or call["id"]
                # Provider extras (Gemini's thought_signature) must go back unchanged.
                for key, value in piece.items():
                    if key not in ("index", "id", "type", "function") and value is not None:
                        call[key] = value
                function = piece.get("function") or {}
                call["function"]["name"] += function.get("name") or ""
                call["function"]["arguments"] += function.get("arguments") or ""
    result.content = "".join(parts)
    result.tool_calls = [calls[index] for index in sorted(calls)]
    return result
