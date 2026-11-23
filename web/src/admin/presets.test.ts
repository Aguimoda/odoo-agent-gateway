import { describe, expect, it } from "vitest";

import { PRESETS, presetBaseUrl } from "./presets";

// Same rule as the llm_providers.name check in migration 005.
const PROVIDER_NAME = /^[a-z0-9][a-z0-9_-]{0,39}$/;

describe("provider templates", () => {
  it("keep the earlier templates and add the free platforms", () => {
    const names = PRESETS.map((p) => p.name);
    for (const name of ["groq", "cerebras", "openai", "local", "gemini", "openrouter", "nvidia", "cloudflare", "mistral", "lmstudio"]) {
      expect(names).toContain(name);
    }
  });

  it("have unique names the gateway accepts", () => {
    const names = PRESETS.map((p) => p.name);
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) expect(name).toMatch(PROVIDER_NAME);
  });

  it("use https unless the model runs on this computer", () => {
    for (const preset of PRESETS) {
      const url = new URL(presetBaseUrl(preset, { account_id: "0".repeat(32) }) ?? "");
      if (preset.tier === "local") expect(url.hostname).toBe("localhost");
      else expect(url.protocol, preset.name).toBe("https:");
    }
  });

  it("say what kind of plan each one has, with the date it was checked", () => {
    for (const preset of PRESETS) {
      expect(["free", "trial", "paid", "local"]).toContain(preset.tier);
      if (preset.tier !== "local") {
        expect(preset.checked, preset.name).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        expect(new URL(preset.limitsUrl ?? "").protocol, preset.name).toBe("https:");
      }
    }
  });

  it("build the Cloudflare address from the account id, and only from a valid one", () => {
    const cloudflare = PRESETS.find((p) => p.name === "cloudflare")!;
    expect(cloudflare.needsAccountId).toBe(true);
    const id = "a36775ed720079f8fed7c763b489bab5";
    expect(presetBaseUrl(cloudflare, { account_id: id })).toBe(
      `https://api.cloudflare.com/client/v4/accounts/${id}/ai/v1`,
    );
    expect(presetBaseUrl(cloudflare, { account_id: "" })).toBeNull();
    expect(presetBaseUrl(cloudflare, { account_id: "../../other" })).toBeNull();
  });

  it("leave the address untouched for templates without an account id", () => {
    const groq = PRESETS.find((p) => p.name === "groq")!;
    expect(presetBaseUrl(groq, {})).toBe("https://api.groq.com/openai/v1");
  });
});
