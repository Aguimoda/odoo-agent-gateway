import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { en } from "./en";
import { es, type MessageKey, type Messages } from "./es";
import { readPreference, writePreference } from "../preferences";

export const LANGUAGES = { es, en } as const;
export type Language = keyof typeof LANGUAGES;
export type Values = Record<string, string | number>;

const PLURAL = /\{(\w+), plural, ((?:[^{}]|\{[^{}]*\})*)\}/g;
const OPTION = /(\w+|=\d+) \{([^{}]*)\}/g;

/** Fill `{name}` placeholders and `{count, plural, one {…} other {…}}` blocks. */
export function format(template: string, values: Values = {}, language: Language = "es"): string {
  const rules = new Intl.PluralRules(language);
  const withPlurals = template.replace(PLURAL, (_, name: string, body: string) => {
    const count = Number(values[name] ?? 0);
    const options = new Map<string, string>();
    for (const match of body.matchAll(OPTION)) options.set(match[1]!, match[2]!);
    const chosen = options.get(`=${count}`) ?? options.get(rules.select(count)) ?? options.get("other") ?? "";
    return chosen.replace(/#/g, new Intl.NumberFormat(language).format(count));
  });
  return withPlurals.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  );
}

export function detectLanguage(): Language {
  const saved = readPreference("language");
  if (saved === "es" || saved === "en") return saved;
  const browser = (typeof navigator !== "undefined" ? navigator.language : "es").toLowerCase();
  return browser.startsWith("es") ? "es" : "en";
}

interface I18n {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: MessageKey, values?: Values) => string;
  formatDate: (iso: string | null) => string;
  formatNumber: (value: number) => string;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Language }) {
  const [language, setLanguageState] = useState<Language>(initial ?? detectLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    writePreference("language", next);
  }, []);

  const value = useMemo<I18n>(() => {
    const messages: Messages = LANGUAGES[language];
    const dates = new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" });
    const numbers = new Intl.NumberFormat(language);
    return {
      language,
      setLanguage,
      t: (key, values) => format(messages[key], values, language),
      formatDate: (iso) => (iso ? dates.format(new Date(iso)) : "—"),
      formatNumber: (n) => numbers.format(n),
    };
  }, [language, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n outside I18nProvider");
  return context;
}

export type { MessageKey };
