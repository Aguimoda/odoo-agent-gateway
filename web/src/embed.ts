// The app inside Odoo's side panel (ADR 0021): served under /app/embed, signed in with a
// one-time ticket that Odoo puts in the URL fragment, which never reaches any server.

export const EMBED_BASE = "/app/embed";

export function isEmbedded(pathname: string = window.location.pathname): boolean {
  return pathname === EMBED_BASE || pathname.startsWith(`${EMBED_BASE}/`);
}

export function ticketFromHash(hash: string): string | null {
  const match = /(?:^#|&)ticket=([A-Za-z0-9_-]{20,200})(?:&|$)/.exec(hash);
  return match ? match[1]! : null;
}

/** The Odoo login the panel is for (`?as=`): another person's session is never reused. */
export function expectedLogin(search: string): string | null {
  return new URLSearchParams(search).get("as") || null;
}

export const panelLogin =
  typeof window !== "undefined" && isEmbedded() ? expectedLogin(window.location.search) : null;

/** The ticket of this page load, taken once and removed from the address bar and history. */
function takeTicket(): string | null {
  if (typeof window === "undefined" || !isEmbedded()) return null;
  const ticket = ticketFromHash(window.location.hash);
  if (ticket) {
    const { pathname, search } = window.location;
    window.history.replaceState(window.history.state, "", pathname + search);
  }
  return ticket;
}

export const initialTicket = takeTicket();

/** Ask the Odoo panel around us for a new ticket. Carries no data, so any origin may read it. */
export function askOdooToReopen(): void {
  window.parent?.postMessage({ type: "agent-gateway:reopen" }, "*");
}
