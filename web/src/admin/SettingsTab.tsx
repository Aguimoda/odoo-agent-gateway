import { CircleAlert } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError, get, patch } from "../api/client";
import type { AgentSettings } from "../api/types";
import { useI18n } from "../i18n";
import { useToast } from "../ui/Toast";

export function SettingsTab() {
  const { t, formatDate } = useI18n();
  const notify = useToast();
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [instructions, setInstructions] = useState("");
  const [retention, setRetention] = useState("30");
  const [maxSteps, setMaxSteps] = useState("6");
  const [disabled, setDisabled] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fill = (value: AgentSettings) => {
    setSettings(value);
    setInstructions(value.instructions);
    setRetention(String(value.retention_days));
    setMaxSteps(String(value.max_steps));
    setDisabled(new Set(value.disabled_tools));
  };

  useEffect(() => {
    get<AgentSettings>("/admin/settings")
      .then(fill)
      .catch((failure: unknown) => setError(failure instanceof ApiError ? failure.message : t("common.error")));
  }, [t]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      fill(
        await patch<AgentSettings>("/admin/settings", {
          instructions,
          retention_days: Number(retention),
          max_steps: Number(maxSteps),
          disabled_tools: [...disabled],
        }),
      );
      notify(t("settings.saved"));
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return error ? (
      <div className="alert alert-danger" role="alert">
        <CircleAlert aria-hidden />
        <span>{error}</span>
      </div>
    ) : (
      <div className="skeleton" style={{ height: 320, borderRadius: 12 }} />
    );
  }

  const tools = settings.tools.length ? settings.tools : settings.disabled_tools;

  return (
    <form className="panel" onSubmit={(event) => void submit(event)}>
      <div className="panel-body stack" style={{ paddingTop: "var(--space-5)" }}>
        <div className="field">
          <label className="label" htmlFor="instructions">
            {t("settings.instructions")}
          </label>
          <textarea
            id="instructions"
            className="textarea"
            rows={6}
            maxLength={4000}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            aria-describedby="instructions-help"
          />
          <p id="instructions-help" className="help">
            {t("settings.instructionsHelp")}
          </p>
        </div>
        <div className="form-grid">
          <div className="field">
            <label className="label" htmlFor="retention">
              {t("settings.retention")}
            </label>
            <input id="retention" className="input tabular" type="number" min={1} max={3650} value={retention} onChange={(e) => setRetention(e.target.value)} />
          </div>
          <div className="field">
            <label className="label" htmlFor="max-steps">
              {t("settings.maxSteps")}
            </label>
            <input
              id="max-steps"
              className="input tabular"
              type="number"
              min={1}
              max={20}
              value={maxSteps}
              onChange={(e) => setMaxSteps(e.target.value)}
              aria-describedby="max-steps-help"
            />
            <p id="max-steps-help" className="help">
              {t("settings.maxStepsHelp")}
            </p>
          </div>
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ marginBottom: "var(--space-2)" }}>
            {t("settings.tools")}
          </legend>
          <p className="help">{t("settings.toolsHelp")}</p>
          <div className="tools-grid">
            {tools.map((tool) => (
              <label key={tool} className="check">
                <input
                  type="checkbox"
                  checked={!disabled.has(tool)}
                  onChange={(e) =>
                    setDisabled((current) => {
                      const next = new Set(current);
                      if (e.target.checked) next.delete(tool);
                      else next.add(tool);
                      return next;
                    })
                  }
                />
                {tool}
              </label>
            ))}
          </div>
        </fieldset>
        {error && (
          <div className="alert alert-danger" role="alert">
            <CircleAlert aria-hidden />
            <span>{error}</span>
          </div>
        )}
        <div className="form-actions" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span className="help">
            {settings.updated_by ? t("settings.updated", { login: settings.updated_by, when: formatDate(settings.updated_at) }) : ""}
          </span>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy && <span className="spinner" aria-hidden />}
            {busy ? t("common.saving") : t("settings.save")}
          </button>
        </div>
      </div>
    </form>
  );
}
