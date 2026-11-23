import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/types";
import { secondsLeft } from "./FailureCard";
import { chatReducer, emptyChat, fromStored, type ChatState } from "./state";

const now = 1_700_000_000_000;

function play(state: ChatState, ...events: AgentEvent[]): ChatState {
  return events.reduce((s, event) => chatReducer(s, { type: "event", event, now }), state);
}

describe("chat state", () => {
  it("builds an answer from tokens, tools and the end of the stream", () => {
    let state = chatReducer(emptyChat, { type: "sent", text: "¿Plazo de envío?", now });
    expect(state.streaming).toBe(true);
    state = play(
      state,
      { type: "start", data: { conversation_id: "c", model: { id: 1, provider: "groq", model: "m", label: "GPT OSS" } } },
      { type: "token", data: { text: "Voy a mirar." } },
      { type: "tool_call", data: { name: "search_knowledge", arguments: { query: "plazo" } } },
      { type: "tool_result", data: { name: "search_knowledge", ok: true, count: 2 } },
      { type: "token", data: { text: "Son 3 días." } },
      { type: "done", data: { message_id: 9, prompt_tokens: 10, completion_tokens: 5 } },
    );
    const answer = state.messages[1]!;
    expect(state.streaming).toBe(false);
    expect(answer).toMatchObject({ id: 9, status: "complete", model: "GPT OSS", provider: "groq" });
    // text after a tool starts a new paragraph, as the server joins the stored answer
    expect(answer.content).toBe("Voy a mirar.\n\nSon 3 días.");
    expect(answer.tools).toEqual([{ name: "search_knowledge", arguments: { query: "plazo" }, ok: true, count: 2 }]);
  });

  it("matches each result to the tool call still running", () => {
    let state = chatReducer(emptyChat, { type: "sent", text: "x", now });
    state = play(
      state,
      { type: "tool_call", data: { name: "read_record", arguments: { id: 1 } } },
      { type: "tool_result", data: { name: "read_record", ok: true, count: 1 } },
      { type: "tool_call", data: { name: "read_record", arguments: { id: 2 } } },
      { type: "tool_result", data: { name: "read_record", ok: false, count: null } },
    );
    expect(state.messages[1]!.tools.map((t) => t.ok)).toEqual([true, false]);
  });

  it("keeps a provider failure with its alternatives and when to retry", () => {
    let state = chatReducer(emptyChat, { type: "sent", text: "Hola", now });
    state = play(state, {
      type: "error",
      data: {
        kind: "rate_limited",
        message: "limit",
        retry_after: 40,
        alternatives: [{ id: 2, provider: "cerebras", model: "x", label: "X", is_default: false }],
        message_id: 4,
      },
    });
    const failure = state.messages[1]!.failure!;
    expect(state.streaming).toBe(false);
    expect(failure.kind).toBe("rate_limited");
    expect(failure.alternatives.map((m) => m.id)).toEqual([2]);
    expect(secondsLeft(failure, now + 15_500)).toBe(25);
    expect(secondsLeft(failure, now + 60_000)).toBe(0);
  });

  it("marks an answer stopped by the person, and refused sends", () => {
    let state = chatReducer(emptyChat, { type: "sent", text: "Hola", now });
    state = chatReducer(state, { type: "stopped" });
    expect(state.messages[1]!.status).toBe("stopped");

    state = chatReducer(state, { type: "sent", text: "Otra", now });
    state = chatReducer(state, { type: "refused", now, kind: "rate_limited", message: "Espera" });
    expect(state.messages[3]!).toMatchObject({ status: "error", failure: { kind: "rate_limited", message: "Espera" } });
  });

  it("loads stored messages with their model and failure kind", () => {
    const message = fromStored({
      id: 3,
      at: "2026-11-23T10:00:00Z",
      role: "assistant",
      content: "",
      tools: [],
      model: "groq/openai/gpt-oss-120b",
      status: "error",
      error: "quota_exhausted",
    });
    expect(message).toMatchObject({ provider: "groq", model: "openai/gpt-oss-120b", status: "error" });
    expect(message.failure?.kind).toBe("quota_exhausted");
  });
});
