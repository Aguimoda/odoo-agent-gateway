"""The OpenAI-compatible client: streaming, failure classification, retries, circuit breaker."""

import json

import httpx2
import pytest

from odoo_agent_gateway.llm import (
    ChatClient,
    CircuitBreaker,
    ProviderFailure,
    Target,
    classify_http,
)

pytestmark = pytest.mark.anyio

FAKE_KEY = "fake-provider-key-for-tests-only"
TARGET = Target(
    model_id=1,
    provider_id=1,
    provider="groq",
    model="openai/gpt-oss-120b",
    label="GPT-OSS 120B",
    base_url="https://api.groq.test/openai/v1",
    api_key=FAKE_KEY,
)


def sse(*chunks) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def delta(**values):
    return {"choices": [{"index": 0, "delta": values}]}


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(recorder, sleeps=None):
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(recorder))
    return ChatClient(http, sleep=sleep)


def stream_response(*chunks):
    return httpx2.Response(200, content=sse(*chunks), headers={"content-type": "text/event-stream"})


# Classification (ADR 0017)


@pytest.mark.parametrize(
    "status, body, kind",
    [
        (401, '{"error": {"message": "Invalid API Key"}}', "auth_failed"),
        (403, "forbidden", "auth_failed"),
        (404, '{"error": {"message": "model not found"}}', "model_unavailable"),
        (
            429,
            '{"error": {"message": "Rate limit reached on requests per minute"}}',
            "rate_limited",
        ),
        (
            429,
            '{"error": {"message": "Rate limit reached on tokens per day (TPD)"}}',
            "quota_exhausted",
        ),
        (429, '{"error": {"code": "insufficient_quota"}}', "quota_exhausted"),
        (
            400,
            '{"error": {"message": "Please reduce the length of the messages"}}',
            "context_too_long",
        ),
        (413, '{"error": {"message": "Request too large"}}', "context_too_long"),
        (
            400,
            '{"error": {"message": "The model `x` has been decommissioned"}}',
            "model_unavailable",
        ),
        (400, '{"error": {"message": "temperature must be a number"}}', "bad_request"),
        (500, "boom", "provider_unavailable"),
        (503, "", "provider_unavailable"),
        (408, "", "provider_unavailable"),
    ],
)
def test_classify_http(status, body, kind):
    failure = classify_http(status, body, {})
    assert failure.kind == kind
    assert body not in failure.message or not body  # the provider's text is never passed on


def test_retry_after_is_read():
    failure = classify_http(429, "slow down", {"retry-after": "12"})
    assert failure.retry_after == 12.0


def test_failure_never_shows_the_key():
    failure = classify_http(401, f"bad key {FAKE_KEY}", {})
    assert FAKE_KEY not in str(failure) and FAKE_KEY not in repr(failure)


def test_target_repr_hides_the_key():
    assert FAKE_KEY not in repr(TARGET)


# Streaming


async def test_streams_tokens_and_assembles_tool_calls_and_usage():
    recorder = Recorder(
        stream_response(
            delta(role="assistant", content="Hola"),
            delta(content=", "),
            delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search_knowledge", "arguments": '{"qu'},
                    }
                ]
            ),
            delta(tool_calls=[{"index": 0, "function": {"arguments": 'ery": "envío"}'}}]),
            {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "x_groq": {"usage": {"prompt_tokens": 120, "completion_tokens": 30}},
            },
        )
    )
    tokens = []

    async def on_token(text):
        tokens.append(text)

    result = await client(recorder).complete(
        TARGET, [{"role": "user", "content": "hi"}], [], on_token
    )
    assert tokens == ["Hola", ", "]
    assert result.content == "Hola, "
    assert result.tool_calls == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "search_knowledge", "arguments": '{"query": "envío"}'},
        }
    ]
    assert (result.prompt_tokens, result.completion_tokens) == (120, 30)
    sent = recorder.requests[0]
    assert sent.headers["authorization"] == f"Bearer {FAKE_KEY}"


async def test_provider_extras_on_a_tool_call_are_kept():
    # Gemini adds a thought_signature that must go back unchanged in the next request.
    recorder = Recorder(
        stream_response(
            delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search_knowledge", "arguments": "{}"},
                        "extra_content": {"google": {"thought_signature": "c2ln"}},
                    }
                ]
            ),
        )
    )

    async def on_token(text):
        pass

    result = await client(recorder).complete(
        TARGET, [{"role": "user", "content": "hi"}], [], on_token
    )
    assert result.tool_calls[0]["extra_content"] == {"google": {"thought_signature": "c2ln"}}
    assert result.tool_calls[0]["function"] == {"name": "search_knowledge", "arguments": "{}"}


async def test_non_text_content_pieces_are_turned_into_text():
    # Cloudflare's Llama sometimes streams a number as the content piece.
    recorder = Recorder(
        stream_response(delta(content="Son "), delta(content=3), delta(content=" días"))
    )
    tokens = []

    async def on_token(text):
        tokens.append(text)

    result = await client(recorder).complete(
        TARGET, [{"role": "user", "content": "hi"}], [], on_token
    )
    assert tokens == ["Son ", "3", " días"]
    assert result.content == "Son 3 días"


async def test_streams_tokens_request_shape():
    recorder = Recorder(stream_response(delta(content="ok")))

    async def on_token(text):
        pass

    await client(recorder).complete(TARGET, [{"role": "user", "content": "hi"}], [], on_token)
    sent = recorder.requests[0]
    assert str(sent.url) == "https://api.groq.test/openai/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(sent.content)
    assert body["stream"] is True and body["model"] == "openai/gpt-oss-120b"
    assert "tools" not in body  # no tools offered: none sent


async def test_plain_json_answer_is_accepted_too():
    recorder = Recorder(
        httpx2.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Listo"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )
    )
    tokens = []

    async def on_token(text):
        tokens.append(text)

    result = await client(recorder).complete(TARGET, [], [], on_token)
    assert result.content == "Listo" and tokens == ["Listo"]


async def test_error_inside_the_stream_is_a_failure_and_retried_before_any_text():
    recorder = Recorder(*(stream_response({"error": {"message": "internal"}}) for _ in range(3)))
    with pytest.raises(ProviderFailure) as raised:
        await client(recorder).complete(TARGET, [], [], _ignore)
    assert raised.value.kind == "provider_unavailable"
    assert len(recorder.requests) == 3


@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        ({"message": "Rate limit reached", "code": 429}, "rate_limited", "429"),
        (
            {"message": "tool call failed", "code": "tool_use_failed"},
            "bad_request",
            "tool_use_failed",
        ),
        (
            {"message": "The model is overloaded", "type": "server_error"},
            "provider_unavailable",
            "server_error",
        ),
    ],
)
async def test_errors_inside_the_stream_are_classified_by_their_content(error, kind, code):
    """ADR 0020: a stream error is not always "provider down"."""
    recorder = Recorder(*(stream_response({"error": error}) for _ in range(3)))
    with pytest.raises(ProviderFailure) as raised:
        await client(recorder).complete(TARGET, [], [], _ignore)
    assert raised.value.kind == kind
    assert raised.value.code == code


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (400, '{"error": {"code": "tool_use_failed", "message": "x"}}', "tool_use_failed"),
        (400, '{"errors": [{"code": 5006, "message": "AiError"}], "success": false}', "5006"),
        (400, '[{"error": {"code": 400, "status": "INVALID_ARGUMENT"}}]', "INVALID_ARGUMENT"),
        (503, "<html>busy</html>", "503"),
        (400, '{"error": {"code": "bad <script> code with spaces and more"}}', "400"),
    ],
)
def test_the_providers_short_error_code_is_kept(status, body, code):
    assert classify_http(status, body, {}).code == code


async def test_failure_after_text_was_streamed_is_not_retried():
    recorder = Recorder(stream_response(delta(content="Hola"), {"error": {"message": "x"}}))
    with pytest.raises(ProviderFailure):
        await client(recorder).complete(TARGET, [], [], _ignore)
    assert len(recorder.requests) == 1


# Retries


async def _ignore(_):
    return None


async def test_provider_down_is_retried_twice_then_fails():
    sleeps = []
    recorder = Recorder(*(httpx2.Response(502) for _ in range(3)))
    with pytest.raises(ProviderFailure) as raised:
        await client(recorder, sleeps).complete(TARGET, [], [], _ignore)
    assert raised.value.kind == "provider_unavailable"
    assert len(recorder.requests) == 3 and sleeps == [0.5, 1.5]


async def test_connection_error_is_provider_unavailable_and_recovers():
    recorder = Recorder(httpx2.ConnectError("refused"), stream_response(delta(content="ok")))
    result = await client(recorder, []).complete(TARGET, [], [], _ignore)
    assert result.content == "ok"


async def test_short_rate_limit_is_waited_once():
    sleeps = []
    recorder = Recorder(
        httpx2.Response(429, headers={"retry-after": "2"}, text="per minute"),
        stream_response(delta(content="ok")),
    )
    result = await client(recorder, sleeps).complete(TARGET, [], [], _ignore)
    assert result.content == "ok" and sleeps == [2.0]


async def test_long_rate_limit_is_not_waited():
    sleeps = []
    recorder = Recorder(httpx2.Response(429, headers={"retry-after": "40"}, text="per minute"))
    with pytest.raises(ProviderFailure) as raised:
        await client(recorder, sleeps).complete(TARGET, [], [], _ignore)
    assert raised.value.kind == "rate_limited" and raised.value.retry_after == 40.0
    assert sleeps == []


async def test_auth_failure_is_not_retried():
    recorder = Recorder(httpx2.Response(401))
    with pytest.raises(ProviderFailure):
        await client(recorder, []).complete(TARGET, [], [], _ignore)
    assert len(recorder.requests) == 1


async def test_redirects_are_not_followed():
    recorder = Recorder(httpx2.Response(307, headers={"location": "https://elsewhere.test/"}))
    with pytest.raises(ProviderFailure) as raised:
        await client(recorder, []).complete(TARGET, [], [], _ignore)
    assert raised.value.kind == "bad_request"
    assert len(recorder.requests) == 1


async def test_list_models():
    recorder = Recorder(httpx2.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}))
    assert await client(recorder).list_models(TARGET.base_url, FAKE_KEY) == ["a", "b"]
    assert str(recorder.requests[0].url) == "https://api.groq.test/openai/v1/models"


# Circuit breaker


def test_breaker_opens_after_three_failures_and_half_opens_after_cooldown():
    now = [0.0]
    breaker = CircuitBreaker(threshold=3, cooldown=60, clock=lambda: now[0])
    for _ in range(2):
        breaker.failure("groq")
    assert breaker.allow("groq")
    breaker.failure("groq")
    assert not breaker.allow("groq")
    assert breaker.open_for("groq") == pytest.approx(60)
    now[0] = 61
    assert breaker.allow("groq")  # one trial call
    assert not breaker.allow("groq")  # and only one
    breaker.failure("groq")
    assert not breaker.allow("groq")  # trial failed: open again
    now[0] = 122
    assert breaker.allow("groq")
    breaker.success("groq")
    assert breaker.allow("groq") and breaker.open_for("groq") == 0


def test_breaker_is_per_provider_and_success_resets_the_count():
    breaker = CircuitBreaker(threshold=2, cooldown=60, clock=lambda: 0.0)
    breaker.failure("groq")
    breaker.success("groq")
    breaker.failure("groq")
    breaker.failure("cerebras")
    assert breaker.allow("groq") and breaker.allow("cerebras")
