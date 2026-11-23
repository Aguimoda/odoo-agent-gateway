import { describe, expect, it } from "vitest";

import { expectedLogin, isEmbedded, ticketFromHash } from "./embed";

describe("panel inside Odoo (ADR 0021)", () => {
  it("is the app under /app/embed", () => {
    expect(isEmbedded("/app/embed")).toBe(true);
    expect(isEmbedded("/app/embed/chat/123")).toBe(true);
    expect(isEmbedded("/app/chat")).toBe(false);
    expect(isEmbedded("/app/embedded")).toBe(false);
  });

  it("reads the ticket from the fragment, and only a well-formed one", () => {
    const ticket = "a".repeat(43);
    expect(ticketFromHash(`#ticket=${ticket}`)).toBe(ticket);
    expect(ticketFromHash(`#x=1&ticket=${ticket}`)).toBe(ticket);
    expect(ticketFromHash("")).toBeNull();
    expect(ticketFromHash("#ticket=short")).toBeNull();
    expect(ticketFromHash("#ticket=<script>alert(1)</script>xxxxxxxxxxxxxxxxxxxx")).toBeNull();
  });

  it("knows which Odoo user the panel is for, so another person's session is never reused", () => {
    expect(expectedLogin("?as=ana")).toBe("ana");
    expect(expectedLogin("?open=1&as=luis%40example.com")).toBe("luis@example.com");
    expect(expectedLogin("")).toBeNull();
    expect(expectedLogin("?as=")).toBeNull();
  });
});
