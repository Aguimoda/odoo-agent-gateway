// Shapes of the gateway API, as the Python side returns them.

export interface Me {
  login: string;
  uid: number;
  name: string;
  is_admin: boolean;
}

export interface ModelChoice {
  id: number;
  provider: string;
  model: string;
  label: string;
  is_default: boolean;
}

export interface ModelsResponse {
  models: ModelChoice[];
  default: number | null;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ToolUse {
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean | null; // null while the tool is running
  count: number | null;
}

export interface StoredMessage {
  id: number;
  at: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolUse[];
  model: string | null;
  status: "complete" | "incomplete" | "error";
  error: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: StoredMessage[];
}

export type FailureKind =
  | "rate_limited"
  | "quota_exhausted"
  | "auth_failed"
  | "model_unavailable"
  | "context_too_long"
  | "provider_unavailable"
  | "bad_request"
  | "internal_error";

// Server-Sent Events of one answer (ADR 0016).
export type AgentEvent =
  | {
      type: "start";
      data: {
        conversation_id: string;
        model: { id: number; provider: string; model: string; label: string };
      };
    }
  | { type: "token"; data: { text: string } }
  | { type: "tool_call"; data: { name: string; arguments: Record<string, unknown> } }
  | { type: "tool_result"; data: { name: string; ok: boolean; count: number | null } }
  | { type: "proposal"; data: { proposal_id: number; status: string | null } }
  | { type: "notice"; data: { kind: "step_limit" | "history_trimmed" | string; message: string } }
  | {
      type: "error";
      data: {
        kind: FailureKind | string;
        message: string;
        retry_after: number | null;
        alternatives: ModelChoice[];
        message_id: number;
      };
    }
  | {
      type: "done";
      data: {
        message_id: number;
        prompt_tokens: number | null;
        completion_tokens: number | null;
      };
    };

export type ProposalStatus =
  | "pending"
  | "applied"
  | "rejected"
  | "conflict"
  | "expired"
  | "failed";

export interface Proposal {
  proposal_id: number;
  status: ProposalStatus;
  model: string;
  record_id: number;
  changes: Record<string, unknown>;
  reason: string;
  proposer: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  error_code: string | null;
  current?: Record<string, unknown>; // pending proposals: the live values in Odoo
}

export interface ProviderModel {
  id: number;
  name: string;
  label: string | null;
  enabled: boolean;
  is_default: boolean;
  status: string;
}

export type ProviderStatus = "ok" | "disabled" | "no_key" | "auth_failed" | "exhausted" | "circuit_open";

export interface Provider {
  id: number;
  name: string;
  base_url: string;
  enabled: boolean;
  key_set: boolean;
  key_updated_at: string | null;
  requests_per_minute: number | null;
  requests_per_day: number | null;
  tokens_per_minute: number | null;
  status: ProviderStatus | string;
  status_until: string | null;
  last_error: string | null;
  last_error_at: string | null;
  last_ok_at: string | null;
  models: ProviderModel[];
}

export interface AgentSettings {
  instructions: string;
  retention_days: number;
  disabled_tools: string[];
  max_steps: number;
  updated_at: string | null;
  updated_by: string | null;
  tools: string[];
}

export interface UsageRow {
  provider: string;
  model: string;
  calls: number;
  ok: number;
  prompt_tokens: number;
  completion_tokens: number;
  p50_ms: number;
  p95_ms: number;
  errors: Record<string, number>;
}

export interface TestResult {
  ok: boolean;
  models?: string[];
  error?: string;
  message?: string;
}
