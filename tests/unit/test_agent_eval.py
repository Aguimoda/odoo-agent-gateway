import json
from pathlib import Path

import httpx2
import pytest

from odoo_agent_gateway.evals.agent import (
    AgentRun,
    OpenAICompatibleLLM,
    ProviderError,
    Scenario,
    load_scenarios,
    run_agent,
    score,
    summarize,
    to_openai_tools,
)

pytestmark = pytest.mark.anyio

SCENARIOS = Path(__file__).resolve().parents[2] / "evals" / "agent_scenarios.json"
KEY = "sk-provider-secret-123456"

MCP_TOOLS = [
    {
        "name": "search_knowledge",
        "description": "Search the handbook.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "propose_change",
        "description": "Propose a change.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def tool_call(name: str, arguments: dict, call_id: str = "c1") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def answer(text: str) -> dict:
    return {"role": "assistant", "content": text}


class ScriptedLLM:
    """Replies with a fixed script and records the conversations it receives."""

    def __init__(self, *replies: dict) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    async def complete(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


class FakeGateway:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, str, dict]] = []

    async def list_tools(self, user):
        return MCP_TOOLS

    async def call_tool(self, user, name, arguments):
        self.calls.append((user, name, arguments))
        return False, self.results.get(name, "{}")


def test_the_scenarios_load_and_cover_the_four_checks():
    scenarios = load_scenarios(SCENARIOS)

    kinds = {key for s in scenarios for key in s.expect}
    assert {"first_tool", "must_cite", "must_not_contain", "must_not_call"} <= kinds
    assert {s.user for s in scenarios} == {"ana", "luis"}


def test_mcp_tools_become_openai_function_tools():
    (first, _) = to_openai_tools(MCP_TOOLS)

    assert first == {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the handbook.",
            "parameters": MCP_TOOLS[0]["inputSchema"],
        },
    }


async def test_the_agent_loop_calls_tools_as_the_user_and_returns_the_answer():
    llm = ScriptedLLM(
        tool_call("search_knowledge", {"query": "Canarias"}),
        answer("Entre 5 y 7 días laborables (shipping.md)."),
    )
    gateway = FakeGateway(
        {"search_knowledge": '{"results": [{"source": {"path": "shipping.md"}}]}'}
    )

    run = await run_agent(llm, gateway, Scenario("s", "ana", "¿Envío a Canarias?", {}))

    assert gateway.calls == [("ana", "search_knowledge", {"query": "Canarias"})]
    assert run.tools_called == ["search_knowledge"]
    assert run.answer == "Entre 5 y 7 días laborables (shipping.md)."
    tool_message = llm.seen[1][-1]
    assert tool_message["role"] == "tool" and "shipping.md" in tool_message["content"]


async def test_the_loop_stops_after_a_maximum_number_of_steps():
    llm = ScriptedLLM(*[tool_call("search_knowledge", {"query": "x"}, f"c{i}") for i in range(10)])

    run = await run_agent(llm, FakeGateway(), Scenario("s", "ana", "loop", {}), max_steps=3)

    assert len(run.tools_called) == 3
    assert run.stopped == "max_steps"


async def test_malformed_tool_arguments_are_reported_to_the_model_not_crashing():
    bad = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "search_knowledge", "arguments": "{not json"},
            }
        ],
    }
    llm = ScriptedLLM(bad, answer("done"))
    gateway = FakeGateway()

    run = await run_agent(llm, gateway, Scenario("s", "ana", "q", {}))

    assert gateway.calls == []
    assert "invalid JSON" in llm.seen[1][-1]["content"]
    assert run.answer == "done"


def test_scoring_checks_each_expectation():
    scenario = Scenario(
        "s",
        "ana",
        "q",
        {
            "first_tool": ["search_knowledge"],
            "must_cite": "shipping.md",
            "must_contain_any": ["7"],
            "must_not_contain": ["30%"],
            "must_not_call": ["propose_change"],
            "must_call": ["search_knowledge"],
        },
    )
    good = AgentRun(scenario, ["search_knowledge"], "Tarda de 5 a 7 días (fuente: shipping.md).")
    bad = AgentRun(scenario, ["propose_change"], "Hay un 30% de descuento.", stopped="max_steps")

    assert all(score(good).values())
    assert not any(score(bad).values())


def test_the_summary_reports_rates_by_check():
    s1 = Scenario("a", "ana", "q", {"first_tool": ["search_knowledge"], "must_cite": "shipping.md"})
    s2 = Scenario("b", "ana", "q", {"must_not_contain": ["30%"]})
    runs = [AgentRun(s1, ["search_knowledge"], "no source"), AgentRun(s2, [], "Nothing found.")]

    summary = summarize(runs, model="m", provider="api.example.com")

    assert summary["rates"]["first_tool"] == 1.0
    assert summary["rates"]["must_cite"] == 0.0
    assert summary["rates"]["must_not_contain"] == 1.0
    assert summary["passed"] == 1 and summary["scenarios"] == 2


def openai_reply(message: dict) -> httpx2.Response:
    return httpx2.Response(200, json={"choices": [{"message": message}]})


async def test_the_provider_client_sends_the_key_only_as_a_header():
    sent = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return openai_reply(answer("hi"))

    llm = OpenAICompatibleLLM(
        "https://api.example.com/openai/v1",
        "model-x",
        KEY,
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )

    reply = await llm.complete([{"role": "user", "content": "hello"}], to_openai_tools(MCP_TOOLS))

    assert reply["content"] == "hi"
    assert sent[0].url.path == "/openai/v1/chat/completions"
    assert sent[0].headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(sent[0].content)
    assert body["model"] == "model-x" and body["tool_choice"] == "auto"
    assert "parallel_tool_calls" not in body  # some providers reject it
    assert KEY not in repr(llm)


async def test_rate_limits_are_retried_and_other_errors_never_echo_the_key():
    responses = [httpx2.Response(429, headers={"retry-after": "0"}), openai_reply(answer("ok"))]
    llm = OpenAICompatibleLLM(
        "https://api.example.com/v1",
        "m",
        KEY,
        httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: responses.pop(0))),
    )
    assert (await llm.complete([], []))["content"] == "ok"

    failing = OpenAICompatibleLLM(
        "https://api.example.com/v1",
        "m",
        KEY,
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda r: httpx2.Response(401, json={"error": f"bad key {KEY}"})
            )
        ),
    )
    with pytest.raises(ProviderError) as error:
        await failing.complete([], [])
    assert KEY not in str(error.value)


# --- running it by hand: provider presets, demo credentials, a hidden key prompt -----------


def test_provider_presets_fill_the_url_and_model_but_never_a_key():
    from odoo_agent_gateway.evals.agent import PROVIDERS, resolve_settings

    settings = resolve_settings({}, provider="groq", ask_key=lambda: "typed-key")

    assert settings["AGENT_EVAL_BASE_URL"] == PROVIDERS["groq"]["base_url"]
    assert settings["AGENT_EVAL_MODEL"] == PROVIDERS["groq"]["model"]
    assert settings["AGENT_EVAL_API_KEY"] == "typed-key"
    assert all("key" not in preset for preset in PROVIDERS.values())


def test_explicit_environment_values_win_over_presets():
    from odoo_agent_gateway.evals.agent import resolve_settings

    env = {"AGENT_EVAL_MODEL": "my-model", "AGENT_EVAL_API_KEY": "from-env"}

    settings = resolve_settings(env, provider="cerebras", ask_key=lambda: pytest.fail("asked"))

    assert settings["AGENT_EVAL_MODEL"] == "my-model"
    assert settings["AGENT_EVAL_API_KEY"] == "from-env"


def test_without_a_provider_or_url_it_refuses():
    from odoo_agent_gateway.evals.agent import resolve_settings

    with pytest.raises(SystemExit, match="AGENT_EVAL_BASE_URL"):
        resolve_settings({}, provider=None, ask_key=lambda: "k")


def test_an_empty_typed_key_is_refused():
    from odoo_agent_gateway.evals.agent import resolve_settings

    with pytest.raises(SystemExit, match="key"):
        resolve_settings({}, provider="groq", ask_key=lambda: "  ")


def test_demo_credentials_are_loaded_from_the_keys_file(tmp_path):
    from odoo_agent_gateway.evals.agent import load_demo_env

    keys = tmp_path / ".env.demo-keys"
    keys.write_text("# comment\nDEMO_ANA_LOGIN=ana\nDEMO_ANA_API_KEY=abc\n", encoding="utf-8")

    env = load_demo_env({"DEMO_ANA_LOGIN": "already-set"}, keys)

    assert env["DEMO_ANA_LOGIN"] == "already-set"  # the environment wins
    assert env["DEMO_ANA_API_KEY"] == "abc"


def test_finished_is_always_scored_so_its_rate_is_meaningful():
    """Regression: 'finished' only appeared when false, so its rate always read 0%."""
    s = Scenario("a", "ana", "q", {"must_not_call": ["propose_change"]})
    runs = [AgentRun(s, [], "done"), AgentRun(s, ["search_records"], "", stopped="max_steps")]

    summary = summarize(runs, model="m", provider="p")

    assert summary["rates"]["finished"] == 0.5
    assert score(runs[0])["finished"] is True
