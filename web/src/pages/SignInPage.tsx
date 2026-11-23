import { CircleAlert, Languages, LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { useSession } from "../session";
import { BrandMark } from "../ui/BrandMark";

export function SignInPage({ expired }: { expired?: boolean }) {
  const { t, language, setLanguage } = useI18n();
  const { signIn } = useSession();
  const [login, setLogin] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!login.trim() || !apiKey) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(login.trim(), apiKey);
    } catch (failure) {
      setApiKey("");
      if (failure instanceof ApiError && failure.code === "unauthenticated") setError(t("signin.failed"));
      else if (failure instanceof ApiError && failure.code === "sessions_unavailable") setError(t("signin.unavailable"));
      else if (failure instanceof ApiError && failure.code === "network") setError(t("common.network"));
      else setError(failure instanceof ApiError ? failure.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="signin">
      <div className="signin-card">
        <div className="signin-head">
          <BrandMark />
          <h1>{t("signin.title")}</h1>
          <p>{t("signin.lead")}</p>
        </div>

        <form className="signin-form" onSubmit={(event) => void submit(event)} noValidate>
          {error ? (
            <div className="alert alert-danger" role="alert">
              <CircleAlert aria-hidden />
              <span>{error}</span>
            </div>
          ) : (
            expired && (
              <div className="alert alert-info" role="status">
                <CircleAlert aria-hidden />
                <span>{t("signin.expired")}</span>
              </div>
            )
          )}
          <div className="field">
            <label className="label" htmlFor="login">
              {t("signin.login")}
            </label>
            <input
              id="login"
              className="input"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={login}
              onChange={(event) => setLogin(event.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="api-key">
              {t("signin.key")}
            </label>
            <input
              id="api-key"
              className="input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              aria-describedby="api-key-help"
              aria-invalid={!!error}
              required
            />
            <p id="api-key-help" className="help">
              <LockKeyhole aria-hidden style={{ width: 12, height: 12, verticalAlign: -1, marginRight: 4 }} />
              {t("signin.keyHelp")}
            </p>
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={busy || !login.trim() || !apiKey}>
            {busy && <span className="spinner" aria-hidden />}
            {busy ? t("signin.submitting") : t("signin.submit")}
          </button>
        </form>

        <div className="signin-foot">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setLanguage(language === "es" ? "en" : "es")}
            lang={language === "es" ? "en" : "es"}
          >
            <Languages aria-hidden />
            {language === "es" ? "English" : "Español"}
          </button>
        </div>
      </div>
    </main>
  );
}
