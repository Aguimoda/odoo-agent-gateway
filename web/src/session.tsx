import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, del, get, onSignedOut, post } from "./api/client";
import type { Me } from "./api/types";
import { initialTicket, panelLogin } from "./embed";

type State =
  | { status: "loading" }
  | { status: "signed-out"; reason?: "expired" | "ticket" }
  | { status: "signed-in"; me: Me }
  | { status: "unreachable" };

interface Session {
  state: State;
  me: Me | null;
  signIn: (login: string, apiKey: string) => Promise<void>;
  signOut: () => Promise<void>;
  reload: () => void;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    if (attempt === 0 && initialTicket) {
      // Inside Odoo: exchange the one-time ticket for the session cookie (ADR 0021).
      post<Me>("/session/redeem", { ticket: initialTicket })
        .then((me) => active && setState({ status: "signed-in", me }))
        .catch(() => active && setState({ status: "signed-out", reason: "ticket" }));
      return () => {
        active = false;
      };
    }
    get<Me>("/session")
      .then((me) => {
        if (!active) return;
        if (panelLogin && me.login !== panelLogin) {
          // Someone else's session in this browser: close it, Odoo opens one for this person.
          void del("/session").finally(() => active && setState({ status: "signed-out" }));
          return;
        }
        setState({ status: "signed-in", me });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const unreachable = error instanceof ApiError && (error.status === 0 || error.status >= 500);
        setState(unreachable ? { status: "unreachable" } : { status: "signed-out" });
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  useEffect(
    () =>
      onSignedOut(() =>
        setState((current) =>
          current.status === "signed-in" ? { status: "signed-out", reason: "expired" } : current,
        ),
      ),
    [],
  );

  const signIn = useCallback(async (login: string, apiKey: string) => {
    const me = await post<Me>("/session", { login, api_key: apiKey });
    setState({ status: "signed-in", me });
  }, []);

  const signOut = useCallback(async () => {
    try {
      await del("/session");
    } finally {
      setState({ status: "signed-out" });
    }
  }, []);

  const value = useMemo<Session>(
    () => ({
      state,
      me: state.status === "signed-in" ? state.me : null,
      signIn,
      signOut,
      reload: () => {
        setState({ status: "loading" });
        setAttempt((n) => n + 1);
      },
    }),
    [state, signIn, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession outside SessionProvider");
  return context;
}
