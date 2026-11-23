import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { isEmbedded } from "./embed";
import { readPreference, writePreference } from "./preferences";

export type ThemeChoice = "system" | "light" | "dark";

interface Theme {
  choice: ThemeChoice;
  resolved: "light" | "dark";
  setChoice: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<Theme | null>(null);

function systemDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => {
    const saved = readPreference("theme");
    if (saved === "light" || saved === "dark") return saved;
    return isEmbedded() ? "light" : "system"; // inside Odoo, match Odoo, which is light
  });
  const [prefersDark, setPrefersDark] = useState(systemDark);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const listener = (event: MediaQueryListEvent) => setPrefersDark(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);

  const resolved = choice === "system" ? (prefersDark ? "dark" : "light") : choice;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const value = useMemo<Theme>(
    () => ({
      choice,
      resolved,
      setChoice: (next) => {
        setChoiceState(next);
        writePreference("theme", next);
      },
    }),
    [choice, resolved],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme outside ThemeProvider");
  return context;
}
