import { describe, expect, it } from "vitest";

import type { CatalogModel } from "../api/types";
import { filterCatalog, formatTokens } from "./catalog";

const model = (id: string, changes: Partial<CatalogModel> = {}): CatalogModel => ({
  id,
  owned_by: null,
  active: null,
  context_window: null,
  max_output_tokens: null,
  tools: null,
  kind: "chat",
  added: false,
  ...changes,
});

const MODELS = [
  model("openai/gpt-oss-120b", { tools: true, context_window: 131072 }),
  model("liquid/lfm-3:free", { tools: false }),
  model("models/gemini-3.5-flash-lite"),
  model("whisper-large-v3", { kind: "audio" }),
  model("text-embedding-small", { kind: "embedding" }),
];

describe("model catalog", () => {
  it("shows chat models by default, the ones that take tools first", () => {
    const shown = filterCatalog(MODELS, { query: "", toolsOnly: false, allKinds: false });
    expect(shown.map((m) => m.id)).toEqual(["openai/gpt-oss-120b", "models/gemini-3.5-flash-lite", "liquid/lfm-3:free"]);
  });

  it("shows every kind on request", () => {
    expect(filterCatalog(MODELS, { query: "", toolsOnly: false, allKinds: true })).toHaveLength(5);
  });

  it("keeps models whose tool support is unknown when asked for tools, but drops the ones that say no", () => {
    const shown = filterCatalog(MODELS, { query: "", toolsOnly: true, allKinds: false });
    expect(shown.map((m) => m.id)).toEqual(["openai/gpt-oss-120b", "models/gemini-3.5-flash-lite"]);
  });

  it("searches by name, ignoring case and spaces", () => {
    expect(filterCatalog(MODELS, { query: "  GEMINI ", toolsOnly: false, allKinds: false }).map((m) => m.id)).toEqual([
      "models/gemini-3.5-flash-lite",
    ]);
  });

  it("writes token counts the way people read them", () => {
    expect(formatTokens(131072)).toBe("131K");
    expect(formatTokens(1048576)).toBe("1M");
    expect(formatTokens(4096)).toBe("4K");
    expect(formatTokens(800)).toBe("800");
    expect(formatTokens(null)).toBe("—");
  });
});
