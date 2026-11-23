import { RefreshCw, ServerOff } from "lucide-react";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ChatPage } from "./chat/ChatPage";
import { askOdooToReopen, isEmbedded } from "./embed";
import { I18nProvider, useI18n } from "./i18n";
import { SignInPage } from "./pages/SignInPage";
import { SessionProvider, useSession } from "./session";
import { ThemeProvider } from "./theme";
import { ToastProvider } from "./ui/Toast";
import { WorkspaceProvider } from "./workspace";

const AdminPage = lazy(() => import("./admin/AdminPage").then((m) => ({ default: m.AdminPage })));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage })));

function Gate() {
  const { t } = useI18n();
  const { state, reload } = useSession();

  if (state.status === "loading") {
    return (
      <div className="center-state" aria-busy>
        <span className="spinner" aria-label={t("common.loading")} />
      </div>
    );
  }
  if (state.status === "unreachable") {
    return (
      <div className="center-state">
        <div>
          <ServerOff aria-hidden />
          <p>{t("common.network")}</p>
          <button type="button" className="btn" onClick={reload}>
            <RefreshCw aria-hidden />
            {t("common.retry")}
          </button>
        </div>
      </div>
    );
  }
  if (state.status === "signed-out" && isEmbedded()) {
    // Inside Odoo nobody types a key: Odoo opens a new session for us.
    return (
      <div className="center-state">
        <div>
          <h1 className="center-title">{t("embed.signedOutTitle")}</h1>
          <p>{t("embed.signedOutBody")}</p>
          <button type="button" className="btn btn-primary" onClick={askOdooToReopen}>
            <RefreshCw aria-hidden />
            {t("embed.reopen")}
          </button>
        </div>
      </div>
    );
  }
  if (state.status === "signed-out") return <SignInPage expired={state.reason === "expired"} />;

  return (
    <WorkspaceProvider key={state.me.uid}>
      <Suspense fallback={<div className="center-state" aria-busy><span className="spinner" /></div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:conversationId" element={<ChatPage />} />
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/admin/:section" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
      </Suspense>
    </WorkspaceProvider>
  );
}

export function App() {
  return (
    <BrowserRouter basename={isEmbedded() ? "/app/embed" : "/app"}>
      <ThemeProvider>
        <I18nProvider>
          <ToastProvider>
            <SessionProvider>
              <Gate />
            </SessionProvider>
          </ToastProvider>
        </I18nProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
