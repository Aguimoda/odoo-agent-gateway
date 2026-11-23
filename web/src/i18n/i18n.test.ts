import { describe, expect, it } from "vitest";

import { display } from "../pages/ApprovalsPage";
import { groupByAge } from "../shell/History";
import { initials } from "../shell/UserMenu";
import { en } from "./en";
import { es } from "./es";
import { format } from "./index";

const placeholders = (text: string) =>
  [...text.matchAll(/\{(\w+)[,}]/g)].map((m) => m[1]).sort();

describe("translations", () => {
  it("have exactly the same keys in both languages", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  it("use the same placeholders in both languages", () => {
    for (const key of Object.keys(es) as (keyof typeof es)[]) {
      expect(placeholders(en[key]), key).toEqual(placeholders(es[key]));
    }
  });

  it("are not left empty", () => {
    for (const [key, value] of Object.entries(en)) expect(value.trim(), key).not.toBe("");
  });

  it("never use the banned wording", () => {
    for (const value of [...Object.values(es), ...Object.values(en)]) {
      expect(value.toLowerCase()).not.toContain("restar permisos");
    }
  });
});

describe("format", () => {
  it("fills placeholders and plurals", () => {
    expect(format(es["tools.summary"], { count: 1, login: "ana" }, "es")).toBe("Usó 1 herramienta como ana");
    expect(format(es["tools.summary"], { count: 3, login: "ana" }, "es")).toBe("Usó 3 herramientas como ana");
    expect(format(en["tools.ok"], { count: 1 }, "en")).toBe("1 result");
    expect(format("{missing} stays", {}, "en")).toBe("{missing} stays");
  });
});

describe("small helpers", () => {
  it("groups conversations by age", () => {
    const now = new Date("2026-11-23T12:00:00");
    const at = (iso: string) => ({ id: iso, title: iso, created_at: iso, updated_at: iso });
    const groups = groupByAge([at("2026-11-23T09:00:00"), at("2026-11-20T09:00:00"), at("2026-10-01T09:00:00")], now);
    expect(groups.map(([label, list]) => [label, list.length])).toEqual([
      ["nav.today", 1],
      ["nav.week", 1],
      ["nav.older", 1],
    ]);
  });

  it("shows Odoo values the way people read them", () => {
    expect(display([7, "Acme Demo SL"])).toBe("Acme Demo SL");
    expect(display(false)).toBeNull();
    expect(display("")).toBeNull();
    expect(display(12.5)).toBe("12.5");
  });

  it("makes initials from names", () => {
    expect(initials("Ana García López")).toBe("AL");
    expect(initials("carmen")).toBe("CA");
    expect(initials("Ana (Sales)")).toBe("AN");
  });
});
