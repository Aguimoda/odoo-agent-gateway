// The messages of one conversation, as a pure reducer over stored messages and live events.

import type { AgentEvent, ModelChoice, StoredMessage, ToolUse } from "../api/types";

export interface Failure {
  kind: string;
  message: string;
  retryAfter: number | null; // seconds, when the provider said
  receivedAt: number; // ms since epoch, to count down
  alternatives: ModelChoice[];
}

export interface ChatMessage {
  key: string;
  id: number | null;
  role: "user" | "assistant";
  content: string;
  tools: ToolUse[];
  status: "streaming" | "complete" | "incomplete" | "error" | "stopped";
  model: string | null;
  provider: string | null;
  notices: string[];
  proposals: { id: number; status: string | null }[];
  failure: Failure | null;
  paragraphBreak: boolean; // the next token starts a new paragraph (after tools)
}

export interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
}

export type ChatAction =
  | { type: "load"; messages: StoredMessage[] }
  | { type: "sent"; text: string; now: number }
  | { type: "retrying"; now: number }
  | { type: "event"; event: AgentEvent; now: number }
  | { type: "stopped" }
  | { type: "refused"; now: number; kind: string; message: string };

export const emptyChat: ChatState = { messages: [], streaming: false };

let sequence = 0;
const nextKey = () => `local-${++sequence}`;

function assistant(now: number): ChatMessage {
  return {
    key: nextKey() + "-" + now,
    id: null,
    role: "assistant",
    content: "",
    tools: [],
    status: "streaming",
    model: null,
    provider: null,
    notices: [],
    proposals: [],
    failure: null,
    paragraphBreak: false,
  };
}

export function fromStored(message: StoredMessage): ChatMessage {
  return {
    key: `stored-${message.id}`,
    id: message.id,
    role: message.role,
    content: message.content,
    tools: message.tools ?? [],
    status: message.status,
    model: message.model ? message.model.split("/").slice(1).join("/") || message.model : null,
    provider: message.model?.includes("/") ? message.model.split("/")[0]! : null,
    notices: [],
    proposals: [],
    failure: message.error
      ? { kind: message.error, message: "", retryAfter: null, receivedAt: 0, alternatives: [] }
      : null,
    paragraphBreak: false,
  };
}

function updateLast(state: ChatState, change: (message: ChatMessage) => ChatMessage): ChatState {
  const last = state.messages[state.messages.length - 1];
  if (!last || last.role !== "assistant") return state;
  return { ...state, messages: [...state.messages.slice(0, -1), change(last)] };
}

function applyEvent(state: ChatState, event: AgentEvent, now: number): ChatState {
  switch (event.type) {
    case "start":
      return updateLast(state, (m) => ({
        ...m,
        model: event.data.model.label,
        provider: event.data.model.provider,
      }));
    case "token":
      return updateLast(state, (m) => {
        const glue = m.paragraphBreak && m.content && !m.content.endsWith("\n") ? "\n\n" : "";
        return { ...m, content: m.content + glue + event.data.text, paragraphBreak: false };
      });
    case "tool_call":
      return updateLast(state, (m) => ({
        ...m,
        tools: [...m.tools, { name: event.data.name, arguments: event.data.arguments, ok: null, count: null }],
        paragraphBreak: true,
      }));
    case "tool_result":
      return updateLast(state, (m) => {
        const index = m.tools.findLastIndex((t) => t.name === event.data.name && t.ok === null);
        if (index === -1) return m;
        const tools = m.tools.slice();
        tools[index] = { ...tools[index]!, ok: event.data.ok, count: event.data.count };
        return { ...m, tools };
      });
    case "proposal":
      return updateLast(state, (m) => ({
        ...m,
        proposals: [...m.proposals, { id: event.data.proposal_id, status: event.data.status }],
      }));
    case "notice":
      return updateLast(state, (m) => ({ ...m, notices: [...m.notices, event.data.kind] }));
    case "error":
      return {
        ...updateLast(state, (m) => ({
          ...m,
          id: event.data.message_id,
          status: "error",
          tools: m.tools.map((t) => (t.ok === null ? { ...t, ok: false } : t)),
          failure: {
            kind: event.data.kind,
            message: event.data.message,
            retryAfter: event.data.retry_after,
            receivedAt: now,
            alternatives: event.data.alternatives ?? [],
          },
        })),
        streaming: false,
      };
    case "done":
      return {
        ...updateLast(state, (m) => ({ ...m, id: event.data.message_id, status: "complete" })),
        streaming: false,
      };
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "load":
      return { messages: action.messages.map(fromStored), streaming: false };
    case "sent": {
      const user: ChatMessage = { ...assistant(action.now), role: "user", content: action.text, status: "complete" };
      return { messages: [...state.messages, user, assistant(action.now)], streaming: true };
    }
    case "retrying":
      return { messages: [...state.messages, assistant(action.now)], streaming: true };
    case "event":
      return applyEvent(state, action.event, action.now);
    case "stopped":
      return {
        ...updateLast(state, (m) => (m.status === "streaming" ? { ...m, status: "stopped" } : m)),
        streaming: false,
      };
    case "refused": {
      // The gateway refused before streaming (rate limit, provider settings...): no answer.
      const failed = updateLast(state, (m) =>
        m.status === "streaming"
          ? {
              ...m,
              status: "error",
              failure: {
                kind: action.kind,
                message: action.message,
                retryAfter: null,
                receivedAt: action.now,
                alternatives: [],
              },
            }
          : m,
      );
      return { ...failed, streaming: false };
    }
  }
}
