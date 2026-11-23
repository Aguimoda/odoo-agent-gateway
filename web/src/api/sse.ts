// Server-Sent Events over a POST response. EventSource only does GET, so the stream is read
// with fetch and parsed here. The parser is pure and keeps partial input between chunks.

import type { AgentEvent } from "./types";

export interface RawEvent {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";

  /** Feed a chunk of text; get back the events it completed. */
  push(chunk: string): RawEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: RawEvent[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const parsed = parseBlock(block);
      if (parsed) events.push(parsed);
      end = this.buffer.indexOf("\n\n");
    }
    return events;
  }
}

function parseBlock(block: string): RawEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment or keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

const KNOWN = new Set(["start", "token", "tool_call", "tool_result", "proposal", "notice", "error", "done"]);

export function toAgentEvent(raw: RawEvent): AgentEvent | null {
  if (!KNOWN.has(raw.event)) return null;
  try {
    return { type: raw.event, data: JSON.parse(raw.data) } as AgentEvent;
  } catch {
    return null;
  }
}

/** Read an SSE response body as agent events, in order. */
export async function* agentEvents(response: Response): AsyncGenerator<AgentEvent> {
  if (!response.body) return;
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const raw of parser.push(value)) {
        const event = toAgentEvent(raw);
        if (event) yield event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
