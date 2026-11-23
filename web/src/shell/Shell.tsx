import { Inbox, Menu, MessageSquare, PanelLeftClose, PanelLeftOpen, Settings2, SquarePen } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";

import { useI18n } from "../i18n";
import { readPreference, writePreference } from "../preferences";
import { useSession } from "../session";
import { BrandMark } from "../ui/BrandMark";
import { useWorkspace } from "../workspace";
import { History } from "./History";
import { modKey } from "./keys";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { UserMenu } from "./UserMenu";

function typingIn(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(element.tagName));
}

export function Shell({ title, children }: { title?: string; children: ReactNode }) {
  const { t } = useI18n();
  const { me } = useSession();
  const { pendingCount } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => readPreference("sidebar") === "collapsed");
  const [mobileOpenAt, setMobileOpenAt] = useState<string | null>(null);
  const mobileOpen = mobileOpenAt === location.pathname; // navigating closes it
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const toggleSidebar = useCallback(() => {
    if (window.matchMedia("(max-width: 860px)").matches) {
      setMobileOpenAt((open) => (open === location.pathname ? null : location.pathname));
      return;
    }
    setCollapsed((value) => {
      writePreference("sidebar", value ? "open" : "collapsed");
      return !value;
    });
  }, [location.pathname]);

  const newChat = useCallback(() => {
    navigate("/chat");
    setMobileOpenAt(null);
    window.setTimeout(() => document.getElementById("composer-input")?.focus(), 0);
  }, [navigate]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        newChat();
      } else if (mod && !event.shiftKey && event.key.toLowerCase() === "b") {
        event.preventDefault();
        toggleSidebar();
      } else if (!mod && event.key === "?" && !typingIn(event.target)) {
        event.preventDefault();
        setShortcutsOpen(true);
      } else if (!mod && event.key === "/" && !typingIn(event.target)) {
        const input = document.getElementById("composer-input");
        if (input) {
          event.preventDefault();
          input.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, toggleSidebar]);

  const inChat = location.pathname === "/chat" || location.pathname.startsWith("/chat/");

  return (
    <div className="shell" data-collapsed={collapsed} data-mobile-open={mobileOpen}>
      <aside className="sidebar" aria-label={t("nav.history")}>
        <div className="sidebar-inner">
          <div className="sidebar-head">
            <NavLink to="/chat" className="brand" aria-label={t("app.name")}>
              <BrandMark />
              <span>{t("app.name")}</span>
            </NavLink>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-icon"
              onClick={toggleSidebar}
              aria-label={t("nav.collapse")}
              title={`${t("nav.collapse")} (${modKey}+B)`}
            >
              <PanelLeftClose />
            </button>
          </div>

          <nav className="sidebar-actions">
            <button type="button" className="nav-item" onClick={newChat}>
              <SquarePen aria-hidden />
              {t("nav.newChat")}
              <kbd>{modKey}⇧O</kbd>
            </button>
            <NavLink to="/chat" className={() => (inChat ? "nav-item active" : "nav-item")}>
              <MessageSquare aria-hidden />
              {t("nav.chat")}
            </NavLink>
            <NavLink to="/approvals" className="nav-item">
              <Inbox aria-hidden />
              {t("nav.approvals")}
              {pendingCount > 0 && <span className="count">{pendingCount}</span>}
            </NavLink>
            {me?.is_admin && (
              <NavLink to="/admin" className="nav-item">
                <Settings2 aria-hidden />
                {t("nav.admin")}
              </NavLink>
            )}
          </nav>

          <History />

          <div className="sidebar-foot">
            <UserMenu onShortcuts={() => setShortcutsOpen(true)} />
          </div>
        </div>
      </aside>
      <div className="scrim" onClick={() => setMobileOpenAt(null)} aria-hidden />

      <main className="main">
        <header className="topbar">
          <button
            type="button"
            className={`btn btn-ghost btn-sm btn-icon ${collapsed ? "" : "only-mobile"}`}
            onClick={toggleSidebar}
            aria-label={t("nav.expand")}
            title={`${t("nav.expand")} (${modKey}+B)`}
          >
            <PanelLeftOpen className="only-desktop" />
            <Menu className="only-mobile" />
          </button>
          <button
            type="button"
            className={`btn btn-ghost btn-sm btn-icon ${collapsed ? "" : "only-mobile"}`}
            onClick={newChat}
            aria-label={t("nav.newChat")}
            title={`${t("nav.newChat")} (${modKey}+Shift+O)`}
          >
            <SquarePen />
          </button>
          {title && <div className="topbar-title">{title}</div>}
        </header>
        {children}
      </main>

      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
