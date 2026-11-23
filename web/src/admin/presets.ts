// Templates fill the address (and a suggested model when we know one that uses tools);
// the key is always typed by the admin. Plans and limits change often: each template says
// what kind of plan it had when it was checked, and links the provider's own limits page
// instead of copying numbers that would go stale.

export type PresetTier = "free" | "trial" | "paid" | "local";

export interface Preset {
  name: string;
  label: string;
  base_url: string;
  model?: string;
  tier: PresetTier;
  checked?: string; // when the plan was checked, YYYY-MM-DD
  limitsUrl?: string;
  needsAccountId?: boolean; // the address contains {account_id}
}

export const PRESETS: Preset[] = [
  {
    name: "groq",
    label: "Groq",
    base_url: "https://api.groq.com/openai/v1",
    model: "openai/gpt-oss-120b",
    tier: "free",
    checked: "2026-11-23",
    limitsUrl: "https://console.groq.com/docs/rate-limits",
  },
  {
    name: "gemini",
    label: "Google Gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    model: "models/gemini-3.5-flash-lite",
    tier: "free",
    checked: "2026-11-23",
    limitsUrl: "https://aistudio.google.com/rate-limit",
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    base_url: "https://openrouter.ai/api/v1",
    model: "nvidia/nemotron-3-ultra-550b-a55b:free",
    tier: "free",
    checked: "2026-11-23",
    limitsUrl: "https://openrouter.ai/pricing",
  },
  {
    name: "nvidia",
    label: "NVIDIA NIM",
    base_url: "https://integrate.api.nvidia.com/v1",
    tier: "free",
    checked: "2026-11-23",
    limitsUrl: "https://build.nvidia.com/",
  },
  {
    name: "cloudflare",
    label: "Cloudflare Workers AI",
    base_url: "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
    model: "@cf/openai/gpt-oss-120b",
    tier: "free",
    checked: "2026-11-23",
    limitsUrl: "https://developers.cloudflare.com/workers-ai/platform/pricing/",
    needsAccountId: true,
  },
  {
    name: "cerebras",
    label: "Cerebras",
    base_url: "https://api.cerebras.ai/v1",
    model: "gpt-oss-120b",
    tier: "trial",
    checked: "2026-11-23",
    limitsUrl: "https://inference-docs.cerebras.ai/support/rate-limits",
  },
  {
    name: "mistral",
    label: "Mistral",
    base_url: "https://api.mistral.ai/v1",
    tier: "paid",
    checked: "2026-11-23",
    limitsUrl: "https://docs.mistral.ai/",
  },
  {
    name: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
    tier: "paid",
    checked: "2026-11-23",
    limitsUrl: "https://platform.openai.com/docs/guides/rate-limits",
  },
  { name: "local", label: "Ollama (local)", base_url: "http://localhost:11434/v1", model: "qwen2.5:7b", tier: "local" },
  { name: "lmstudio", label: "LM Studio (local)", base_url: "http://localhost:1234/v1", tier: "local" },
];

const ACCOUNT_ID = /^[0-9a-f]{32}$/;

/** The template's address, or null while a required account id is missing or malformed. */
export function presetBaseUrl(preset: Preset, values: { account_id?: string }): string | null {
  if (!preset.needsAccountId) return preset.base_url;
  const id = (values.account_id ?? "").trim().toLowerCase();
  return ACCOUNT_ID.test(id) ? preset.base_url.replace("{account_id}", id) : null;
}
