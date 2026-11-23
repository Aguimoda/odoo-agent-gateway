import { Check, ChevronsUpDown, Keyboard, Languages, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n, type Language } from "../i18n";
import { useSession } from "../session";
import { useTheme, type ThemeChoice } from "../theme";

const THEMES: { value: ThemeChoice; key: "user.themeSystem" | "user.themeLight" | "user.themeDark"; icon: typeof Sun }[] = [
  { value: "system", key: "user.themeSystem", icon: Monitor },
  { value: "light", key: "user.themeLight", icon: Sun },
  { value: "dark", key: "user.themeDark", icon: Moon },
];

const LANGUAGE_NAMES: Record<Language, string> = { es: "Español", en: "English" };

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter((part) => /^\p{L}/u.test(part));
  const letters = parts.length > 1 ? parts[0]![0]! + parts[parts.length - 1]![0]! : (parts[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}

export function UserMenu({ onShortcuts }: { onShortcuts: () => void }) {
  const { t, language, setLanguage } = useI18n();
  const { me, signOut } = useSession();
  const { choice, setChoice } = useTheme();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    root.current?.querySelector<HTMLButtonElement>(".menu .menu-item")?.focus();
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (!me) return null;
  return (
    <div ref={root}>
      <button
        type="button"
        className="user-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("user.menu")}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden>
          {initials(me.name)}
        </span>
        <span className="user-text">
          <strong>{me.name}</strong>
          <span>{me.is_admin ? t("user.admin") : me.login}</span>
        </span>
        <ChevronsUpDown aria-hidden />
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-label">{t("user.theme")}</div>
          {THEMES.map(({ value, key, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="menuitemradio"
              aria-checked={choice === value}
              className="menu-item"
              onClick={() => setChoice(value)}
            >
              <Icon aria-hidden />
              {t(key)}
              {choice === value && <Check className="check-mark" aria-hidden />}
            </button>
          ))}
          <div className="menu-separator" />
          <div className="menu-label">{t("user.language")}</div>
          {(Object.keys(LANGUAGE_NAMES) as Language[]).map((code) => (
            <button
              key={code}
              type="button"
              role="menuitemradio"
              aria-checked={language === code}
              className="menu-item"
              lang={code}
              onClick={() => setLanguage(code)}
            >
              <Languages aria-hidden />
              {LANGUAGE_NAMES[code]}
              {language === code && <Check className="check-mark" aria-hidden />}
            </button>
          ))}
          <div className="menu-separator" />
          <button
            type="button"
            role="menuitem"
            className="menu-item"
            onClick={() => {
              setOpen(false);
              onShortcuts();
            }}
          >
            <Keyboard aria-hidden />
            {t("user.shortcuts")}
            <kbd style={{ marginLeft: "auto" }}>?</kbd>
          </button>
          <button type="button" role="menuitem" className="menu-item" onClick={() => void signOut()}>
            <LogOut aria-hidden />
            {t("user.signOut")}
          </button>
        </div>
      )}
    </div>
  );
}
