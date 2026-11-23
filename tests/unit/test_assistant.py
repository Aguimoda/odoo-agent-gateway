"""The agent loop (ADR 0016): streaming events, tools, step limit, trimming, failures."""

import json

import pytest

from odoo_agent_gateway.assistant import (
    DEFAULT_INSTRUCTIONS,
    TurnFailed,
    internal_host,
    run_turn,
    system_prompt,
)
from odoo_agent_gateway.llm import ChatResult, ProviderFailure

pytestmark = pytest.mark.anyio

TOOLS = [
    {"name": "search_knowledge", "description": "Search", "inputSchema": {"type": "object"}},
    {"name": "propose_change", "description": "Propose", "inputSchema": {"type": "object"}},
]


def call(name, arguments, call_id="c1"):
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


class FakeModel:
    """Scripted answers; records what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []

    async def __call__(self, messages, tools, on_token):
        self.sent.append({"messages": [dict(m) for m in messages], "tools": tools})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if answer.content:
            for word in answer.content.split(" "):
                await on_token(word)
        return answer


class FakeTools:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    async def list_tools(self):
        return TOOLS

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, (True, json.dumps({"results": [1, 2]})))


class Events:
    def __init__(self):
        self.items = []

    async def __call__(self, kind, data):
        self.items.append((kind, data))

    def kinds(self):
        return [kind for kind, _ in self.items]


async def turn(model, tools=None, history=None, disabled=(), max_steps=6):
    events = Events()
    result = await run_turn(
        model,
        tools or FakeTools(),
        history or [],
        "¿Plazo de envío?",
        instructions="",
        disabled_tools=frozenset(disabled),
        max_steps=max_steps,
        emit=events,
    )
    return result, events


async def test_answer_with_a_tool_streams_events_and_records_tools_without_results():
    model = FakeModel(
        ChatResult(tool_calls=[call("search_knowledge", {"query": "envío"})]),
        ChatResult(content="Son 3 días (shipping.md)."),
    )
    tools = FakeTools()
    result, events = await turn(model, tools)

    assert result.content == "Son 3 días (shipping.md)."
    assert result.tools == [
        {"name": "search_knowledge", "arguments": {"query": "envío"}, "ok": True, "count": 2}
    ]
    assert events.kinds() == ["tool_call", "tool_result"] + ["token"] * 4
    assert events.items[1] == ("tool_result", {"name": "search_knowledge", "ok": True, "count": 2})
    # The tool result went to the model, but no event or record carries it.
    assert model.sent[1]["messages"][-1]["role"] == "tool"
    assert all("results" not in json.dumps(data) for _, data in events.items)


async def test_tool_call_turn_sends_text_content_and_keeps_provider_extras():
    # Cloudflare refuses content null; Gemini needs its thought_signature sent back as given.
    signed = call("search_knowledge", {"query": "envío"})
    signed["extra_content"] = {"google": {"thought_signature": "c2lnbmF0dXJl"}}
    model = FakeModel(ChatResult(tool_calls=[signed]), ChatResult(content="Son 3 días."))
    await turn(model)

    assistant = model.sent[1]["messages"][-2]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == ""
    assert assistant["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "c2lnbmF0dXJl"}
    }


async def test_the_first_message_is_the_safe_system_prompt():
    model = FakeModel(ChatResult(content="Hola"))
    await turn(model)
    first = model.sent[0]["messages"][0]
    assert first["role"] == "system" and DEFAULT_INSTRUCTIONS in first["content"]


def test_company_instructions_are_added_never_replace():
    prompt = system_prompt("Responde siempre de usted.")
    assert prompt.startswith(DEFAULT_INSTRUCTIONS)
    assert "Responde siempre de usted." in prompt
    assert system_prompt("") == DEFAULT_INSTRUCTIONS


def test_default_instructions_carry_the_lessons_from_the_evaluation():
    text = DEFAULT_INSTRUCTIONS.lower()
    assert "propose_change" in text and "approval" in text
    assert "never say" in text  # never claim a change was made
    assert "could not find" in text  # say so instead of searching forever


async def test_proposals_are_announced():
    proposal = {"proposal_id": 42, "status": "pending", "notice": "awaits approval"}
    model = FakeModel(
        ChatResult(tool_calls=[call("propose_change", {"model": "res.partner"})]),
        ChatResult(content="He propuesto el cambio; espera aprobación."),
    )
    tools = FakeTools({"propose_change": (True, json.dumps(proposal))})
    _, events = await turn(model, tools)
    assert ("proposal", {"proposal_id": 42, "status": "pending"}) in events.items


async def test_disabled_tools_are_neither_offered_nor_run():
    model = FakeModel(
        ChatResult(tool_calls=[call("propose_change", {"x": 1})]),
        ChatResult(content="No puedo proponer cambios."),
    )
    tools = FakeTools()
    result, _ = await turn(model, tools, disabled={"propose_change"})
    offered = [t["function"]["name"] for t in model.sent[0]["tools"]]
    assert offered == ["search_knowledge"]
    assert tools.calls == []
    assert result.tools[0]["ok"] is False
    assert "not available" in model.sent[1]["messages"][-1]["content"]


async def test_broken_arguments_are_explained_to_the_model():
    model = FakeModel(
        ChatResult(tool_calls=[call("search_knowledge", "{not json")]),
        ChatResult(content="ok"),
    )
    tools = FakeTools()
    await turn(model, tools)
    assert tools.calls == []
    assert "invalid JSON" in model.sent[1]["messages"][-1]["content"]


async def test_step_limit_asks_for_a_final_answer_without_tools():
    """Scenario: no da vueltas sin fin."""
    searching = [
        ChatResult(tool_calls=[call("search_knowledge", {"query": str(i)}, f"c{i}")])
        for i in range(2)
    ]
    model = FakeModel(*searching, ChatResult(content="No lo he encontrado."))
    result, events = await turn(model, max_steps=2)
    assert result.content == "No lo he encontrado."
    assert model.sent[-1]["tools"] == []
    assert "could not find" in model.sent[-1]["messages"][-1]["content"].lower()
    assert ("notice", {"kind": "step_limit"}) in [
        (k, {"kind": d["kind"]}) for k, d in events.items if k == "notice"
    ]


async def test_history_goes_before_the_question():
    model = FakeModel(ChatResult(content="ok"))
    history = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola!"}]
    await turn(model, history=history)
    roles = [m["role"] for m in model.sent[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


async def test_too_long_drops_the_history_once_and_says_so():
    model = FakeModel(ProviderFailure("context_too_long"), ChatResult(content="ok"))
    history = [{"role": "user", "content": "x" * 50}, {"role": "assistant", "content": "y"}]
    result, events = await turn(model, history=history)
    assert result.content == "ok"
    assert [m["role"] for m in model.sent[1]["messages"]] == ["system", "user"]
    assert any(k == "notice" and d["kind"] == "history_trimmed" for k, d in events.items)


async def test_too_long_twice_is_a_failure():
    model = FakeModel(ProviderFailure("context_too_long"), ProviderFailure("context_too_long"))
    history = [{"role": "user", "content": "x"}]
    with pytest.raises(TurnFailed) as raised:
        await turn(model, history=history)
    assert raised.value.failure.kind == "context_too_long"


async def test_failure_keeps_what_was_written_and_the_tools_used():
    model = FakeModel(
        ChatResult(tool_calls=[call("search_knowledge", {"query": "a"})]),
        ProviderFailure("rate_limited", retry_after=30),
    )
    with pytest.raises(TurnFailed) as raised:
        await turn(model)
    assert raised.value.failure.kind == "rate_limited"
    assert raised.value.tools[0]["name"] == "search_knowledge"


def test_internal_host_satisfies_the_mcp_host_check():
    assert internal_host(("127.0.0.1:*", "localhost:*")) == "127.0.0.1:8000"
    assert internal_host(("gateway.example.com",)) == "gateway.example.com"
