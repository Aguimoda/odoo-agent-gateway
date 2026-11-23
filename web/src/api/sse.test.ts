import { describe, expect, it } from "vitest";

import { agentEvents, SseParser, toAgentEvent } from "./sse";

describe("SseParser", () => {
  it("parses whole events and keeps partial ones for the next chunk", () => {
    const parser = new SseParser();
    expect(parser.push('event: token\ndata: {"text":"Hol')).toEqual([]);
    expect(parser.push('a"}\n\nevent: done\n')).toEqual([{ event: "token", data: '{"text":"Hola"}' }]);
    expect(parser.push('data: {"message_id":3}\n\n')).toEqual([{ event: "done", data: '{"message_id":3}' }]);
  });

  it("handles CRLF, comments, keep-alives and multi-line data", () => {
    const parser = new SseParser();
    const events = parser.push(": ping\r\n\r\nevent: notice\r\ndata: line one\r\ndata: line two\r\n\r\n");
    expect(events).toEqual([{ event: "notice", data: "line one\nline two" }]);
  });

  it("drops unknown events and broken JSON instead of failing", () => {
    expect(toAgentEvent({ event: "surprise", data: "{}" })).toBeNull();
    expect(toAgentEvent({ event: "token", data: "{not json" })).toBeNull();
    expect(toAgentEvent({ event: "token", data: '{"text":"a"}' })).toEqual({ type: "token", data: { text: "a" } });
  });
});

describe("agentEvents", () => {
  it("reads a streamed response split at awkward places", async () => {
    const body = 'event: start\ndata: {"conversation_id":"c","model":{"id":1,"provider":"groq","model":"m","label":"M"}}\n\nevent: token\ndata: {"text":"¿Sí?"}\n\nevent: done\ndata: {"message_id":7,"prompt_tokens":1,"completion_tokens":2}\n\n';
    const bytes = new TextEncoder().encode(body);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        // split inside a multi-byte character and inside a line
        for (const [from, to] of [
          [0, 40],
          [40, 131],
          [131, 133],
          [133, bytes.length],
        ]) {
          controller.enqueue(bytes.slice(from, to));
        }
        controller.close();
      },
    });
    const types: string[] = [];
    let text = "";
    for await (const event of agentEvents(new Response(stream))) {
      types.push(event.type);
      if (event.type === "token") text += event.data.text;
    }
    expect(types).toEqual(["start", "token", "done"]);
    expect(text).toBe("¿Sí?");
  });
});
