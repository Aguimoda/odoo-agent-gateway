import { CircleAlert, CircleCheck, Clock, KeyRound, Pencil, Plug, Plus, ShieldAlert, Star, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { ApiError, del, get, patch, post } from "../api/client";
import type { Provider, ProviderModel, TestResult } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { useToast } from "../ui/Toast";
import { useWorkspace } from "../workspace";
import { PRESETS, presetBaseUrl } from "./presets";

const TIER_TONE: Record<string, string> = { free: "badge-success", trial: "badge-warning", paid: "", local: "badge-accent" };

const HEALTH_TONE: Record<string, string> = {
  ok: "badge-success",
  disabled: "",
  no_key: "badge-warning",
  auth_failed: "badge-danger",
  exhausted: "badge-warning",
  circuit_open: "badge-warning",
  unavailable: "badge-danger",
};

export function HealthBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const known = status in HEALTH_TONE;
  return (
    <span className={`badge badge-dot ${HEALTH_TONE[status] ?? ""}`}>
      {known ? t(`health.${status}` as MessageKey) : status}
    </span>
  );
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

interface ProviderForm {
  name: string;
  base_url: string;
  api_key: string;
  requests_per_minute: string;
  requests_per_day: string;
  enabled: boolean;
}

const emptyForm: ProviderForm = {
  name: "",
  base_url: "",
  api_key: "",
  requests_per_minute: "",
  requests_per_day: "",
  enabled: true,
};

function limit(value: string): number | null {
  const n = Number(value);
  return value.trim() && Number.isInteger(n) && n > 0 ? n : null;
}

function ProviderEditor({
  provider,
  onSaved,
  onCancel,
}: {
  provider: Provider | null;
  onSaved: (provider: Provider, suggestedModel?: string) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState<ProviderForm>(() =>
    provider
      ? {
          name: provider.name,
          base_url: provider.base_url,
          api_key: "",
          requests_per_minute: provider.requests_per_minute?.toString() ?? "",
          requests_per_day: provider.requests_per_day?.toString() ?? "",
          enabled: provider.enabled,
        }
      : emptyForm,
  );
  const [preset, setPreset] = useState<string | null>(null);
  const [accountId, setAccountId] = useState("");
  const chosen = PRESETS.find((p) => p.name === preset);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (field: keyof ProviderForm, value: string | boolean) => setForm((f) => ({ ...f, [field]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let saved: Provider;
      if (provider) {
        const body: Record<string, unknown> = {
          enabled: form.enabled,
          requests_per_minute: limit(form.requests_per_minute),
          requests_per_day: limit(form.requests_per_day),
        };
        if (form.base_url.trim() !== provider.base_url) body.base_url = form.base_url.trim();
        if (form.api_key) body.api_key = form.api_key;
        saved = await patch<Provider>(`/admin/providers/${provider.id}`, body);
      } else {
        saved = await post<Provider>("/admin/providers", {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          api_key: form.api_key || null,
          enabled: form.enabled,
          requests_per_minute: limit(form.requests_per_minute),
          requests_per_day: limit(form.requests_per_day),
        });
      }
      onSaved(saved, PRESETS.find((p) => p.name === preset)?.model);
    } catch (failure) {
      setError(errorText(failure, t("common.error")));
    } finally {
      setBusy(false);
      setForm((f) => ({ ...f, api_key: "" })); // never keep a typed key around
    }
  };

  return (
    <form className="panel" onSubmit={(event) => void submit(event)}>
      <div className="panel-header">
        <h2 style={{ fontSize: "var(--text-md)", fontWeight: 600 }}>
          {provider ? `${t("providers.edit")} · ${provider.name}` : t("providers.add")}
        </h2>
        <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onCancel} aria-label={t("nav.cancel")}>
          <X />
        </button>
      </div>
      <div className="panel-body stack">
        {!provider && (
          <div className="field">
            <span className="label">{t("providers.preset")}</span>
            <div className="presets">
              {PRESETS.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  className="chip"
                  aria-pressed={preset === p.name}
                  style={preset === p.name ? { borderColor: "var(--accent)", color: "var(--accent-text)" } : undefined}
                  onClick={() => {
                    setPreset(p.name);
                    setForm((f) => ({ ...f, name: p.name, base_url: presetBaseUrl(p, { account_id: accountId }) ?? "" }));
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {chosen && (
              <p className="help preset-facts">
                <span className={`badge ${TIER_TONE[chosen.tier]}`}>{t(`providers.tier.${chosen.tier}` as MessageKey)}</span>
                {chosen.checked && <span>{t("providers.tierChecked", { date: chosen.checked })}</span>}
                {chosen.limitsUrl && (
                  <a href={chosen.limitsUrl} target="_blank" rel="noopener noreferrer">
                    {t("providers.limitsLink")}
                  </a>
                )}
              </p>
            )}
          </div>
        )}
        {chosen?.needsAccountId && (
          <div className="field">
            <label className="label" htmlFor="provider-account">
              {t("providers.accountId")}
            </label>
            <input
              id="provider-account"
              className="input mono"
              value={accountId}
              maxLength={32}
              spellCheck={false}
              onChange={(e) => {
                setAccountId(e.target.value);
                setForm((f) => ({ ...f, base_url: presetBaseUrl(chosen, { account_id: e.target.value }) ?? "" }));
              }}
              aria-describedby="provider-account-help"
              required
            />
            <p id="provider-account-help" className="help">
              {t("providers.accountIdHelp")}
            </p>
          </div>
        )}
        <div className="form-grid">
          <div className="field">
            <label className="label" htmlFor="provider-name">
              {t("providers.name")}
            </label>
            <input
              id="provider-name"
              className="input"
              value={form.name}
              maxLength={40}
              disabled={!!provider}
              onChange={(e) => set("name", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="provider-url">
              {t("providers.baseUrl")}
            </label>
            <input
              id="provider-url"
              className="input mono"
              value={form.base_url}
              maxLength={300}
              inputMode="url"
              spellCheck={false}
              onChange={(e) => set("base_url", e.target.value)}
              aria-describedby="provider-url-help"
              required
            />
            <p id="provider-url-help" className="help">
              {t("providers.baseUrlHelp")}
            </p>
          </div>
          <div className="field span-2">
            <label className="label" htmlFor="provider-key">
              {provider ? t("providers.keyReplace") : t("providers.key")}
            </label>
            <input
              id="provider-key"
              className="input"
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              value={form.api_key}
              maxLength={500}
              onChange={(e) => set("api_key", e.target.value)}
              aria-describedby="provider-key-help"
            />
            <p id="provider-key-help" className="help">
              {provider ? t("providers.keyReplaceHelp") : t("providers.keyHelp")}
            </p>
          </div>
          <div className="field">
            <label className="label" htmlFor="provider-rpm">
              {t("providers.perMinute")} <span className="optional">· {t("common.optional")}</span>
            </label>
            <input id="provider-rpm" className="input tabular" inputMode="numeric" value={form.requests_per_minute} onChange={(e) => set("requests_per_minute", e.target.value)} />
          </div>
          <div className="field">
            <label className="label" htmlFor="provider-rpd">
              {t("providers.perDay")} <span className="optional">· {t("common.optional")}</span>
            </label>
            <input id="provider-rpd" className="input tabular" inputMode="numeric" value={form.requests_per_day} onChange={(e) => set("requests_per_day", e.target.value)} />
          </div>
          <label className="check span-2">
            <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            {t("providers.enabled")}
          </label>
        </div>
        <div className="alert alert-info">
          <ShieldAlert aria-hidden />
          <span>{t("providers.dataWarning")}</span>
        </div>
        {error && (
          <div className="alert alert-danger" role="alert">
            <CircleAlert aria-hidden />
            <span>{error}</span>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onCancel}>
            {t("nav.cancel")}
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim() || !form.base_url.trim()}>
            {busy && <span className="spinner" aria-hidden />}
            {provider ? t("providers.save") : t("providers.create")}
          </button>
        </div>
      </div>
    </form>
  );
}

function ModelsSection({
  provider,
  offered,
  onChange,
}: {
  provider: Provider;
  offered: string[] | null;
  onChange: (provider: Provider) => void;
}) {
  const { t } = useI18n();
  const notify = useToast();
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const act = async (work: () => Promise<Provider>) => {
    setBusy(true);
    try {
      onChange(await work());
    } catch (failure) {
      notify(errorText(failure, t("common.error")), "error");
    } finally {
      setBusy(false);
    }
  };

  const add = (modelName: string, modelLabel?: string) =>
    act(() =>
      post<Provider>(`/admin/providers/${provider.id}/models`, {
        name: modelName,
        label: modelLabel || null,
        is_default: !provider.models.some((m) => m.is_default),
      }),
    ).then(() => {
      setName("");
      setLabel("");
    });

  const existing = new Set(provider.models.map((m) => m.name));
  const shown = (offered ?? []).filter((m) => !existing.has(m) && m.toLowerCase().includes(filter.toLowerCase())).slice(0, 60);

  return (
    <div>
      <div className="models-head">
        <h3>{t("providers.models")}</h3>
      </div>
      {provider.models.length === 0 ? (
        <p className="help">{t("providers.noModels")}</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {provider.models.map((model: ProviderModel) => (
                <tr key={model.id}>
                  <td>
                    <span className="model-row-name">{model.name}</span>
                    {model.label && <span className="model-row-label">{model.label}</span>}
                  </td>
                  <td>
                    <HealthBadge status={model.status} />
                  </td>
                  <td>
                    {model.is_default && (
                      <span className="badge badge-accent">
                        <Star size={12} aria-hidden /> {t("providers.default")}
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="row-actions">
                      {!model.is_default && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() => void act(() => patch<Provider>(`/admin/models/${model.id}`, { is_default: true }))}
                        >
                          {t("providers.makeDefault")}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        disabled={busy}
                        aria-label={`${t("providers.removeModel")}: ${model.name}`}
                        title={t("providers.removeModel")}
                        onClick={() => void act(() => del<Provider>(`/admin/models/${model.id}`))}
                      >
                        <Trash2 />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) void add(name.trim(), label.trim());
        }}
      >
        <div className="field">
          <label className="label" htmlFor={`model-name-${provider.id}`}>
            {t("providers.modelName")}
          </label>
          <input id={`model-name-${provider.id}`} className="input mono" value={name} maxLength={200} spellCheck={false} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label className="label" htmlFor={`model-label-${provider.id}`}>
            {t("providers.modelLabel")}
          </label>
          <input id={`model-label-${provider.id}`} className="input" value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} />
        </div>
        <button type="submit" className="btn" disabled={busy || !name.trim()}>
          <Plus aria-hidden />
          {t("providers.addModel")}
        </button>
      </form>

      {offered && offered.length > 0 && (
        <div className="offered">
          <div className="models-head">
            <h3>{t("providers.offered")}</h3>
            <input
              className="input"
              style={{ maxWidth: "14rem", minHeight: "1.875rem", padding: "0.25rem 0.6rem" }}
              placeholder={t("providers.filterOffered")}
              aria-label={t("providers.filterOffered")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <div className="offered-list">
            {shown.map((modelName) => (
              <button key={modelName} type="button" className="chip" disabled={busy} onClick={() => void add(modelName)}>
                <Plus aria-hidden />
                {modelName}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderPanel({
  provider,
  onChange,
  onEdit,
  onDelete,
}: {
  provider: Provider;
  onChange: (provider: Provider) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t, formatDate } = useI18n();
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await post<TestResult>(`/admin/providers/${provider.id}/test`));
    } catch (failure) {
      setTest({ ok: false, message: errorText(failure, t("common.error")) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <article className="panel" aria-labelledby={`provider-${provider.id}`}>
      <header className="panel-header">
        <div className="provider-head">
          <span className="provider-logo" aria-hidden>
            {provider.name.slice(0, 2)}
          </span>
          <div style={{ minWidth: 0 }}>
            <div className="provider-title">
              <h2 id={`provider-${provider.id}`}>{provider.name}</h2>
              <HealthBadge status={provider.status} />
              {provider.status_until && <span className="help">{t("providers.until", { when: formatDate(provider.status_until) })}</span>}
            </div>
            <span className="provider-url">{provider.base_url}</span>
            <div className="provider-facts">
              <span>
                <KeyRound aria-hidden />
                {provider.key_set ? t("providers.keySet", { when: formatDate(provider.key_updated_at) }) : t("providers.keyMissing")}
              </span>
              {provider.last_ok_at && (
                <span>
                  <CircleCheck aria-hidden />
                  {t("providers.lastOk", { when: formatDate(provider.last_ok_at) })}
                </span>
              )}
              {provider.last_error && (
                <span>
                  <Clock aria-hidden />
                  {t("providers.lastError", { kind: provider.last_error, when: formatDate(provider.last_error_at) })}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="provider-actions">
          <button type="button" className="btn btn-sm" onClick={() => void runTest()} disabled={testing || !provider.key_set}>
            {testing ? <span className="spinner" aria-hidden /> : <Plug aria-hidden />}
            {testing ? t("providers.testing") : t("providers.test")}
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onEdit}>
            <Pencil aria-hidden />
            {t("providers.edit")}
          </button>
          <button type="button" className="btn btn-sm btn-ghost btn-icon" onClick={onDelete} aria-label={`${t("providers.delete")}: ${provider.name}`} title={t("providers.delete")}>
            <Trash2 />
          </button>
        </div>
      </header>
      {test && (
        <div style={{ padding: "0 var(--space-5) var(--space-3)" }}>
          <div className={`alert ${test.ok ? "alert-success" : "alert-danger"}`} role="status">
            {test.ok ? <CircleCheck aria-hidden /> : <CircleAlert aria-hidden />}
            <span>
              {test.ok
                ? t("providers.testOk", { count: test.models?.length ?? 0 })
                : t("providers.testFailed", { reason: test.message ?? test.error ?? "" })}
            </span>
          </div>
        </div>
      )}
      <div className="panel-divider" />
      <div className="panel-body">
        <ModelsSection provider={provider} offered={test?.ok ? (test.models ?? []) : null} onChange={onChange} />
      </div>
    </article>
  );
}

export function ProvidersTab() {
  const { t } = useI18n();
  const notify = useToast();
  const { refreshModels } = useWorkspace();
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  const [deleting, setDeleting] = useState<Provider | null>(null);

  useEffect(() => {
    let active = true;
    get<{ providers: Provider[] }>("/admin/providers")
      .then((result) => active && setProviders(result.providers))
      .catch((failure: unknown) => {
        if (!active) return;
        setProviders([]);
        setError(errorText(failure, t("common.error")));
      });
    return () => {
      active = false;
    };
  }, [t]);

  const replace = useCallback(
    (updated: Provider) => {
      setProviders((current) => {
        const list = current ?? [];
        return list.some((p) => p.id === updated.id) ? list.map((p) => (p.id === updated.id ? updated : p)) : [...list, updated];
      });
      void refreshModels();
    },
    [refreshModels],
  );

  const saved = async (provider: Provider, suggestedModel?: string) => {
    setEditing(null);
    replace(provider);
    if (suggestedModel && provider.models.length === 0) {
      try {
        replace(await post<Provider>(`/admin/providers/${provider.id}/models`, { name: suggestedModel, is_default: true }));
      } catch {
        // the admin can add a model by hand
      }
    }
    notify(t("settings.saved"));
  };

  const confirmDelete = async () => {
    const target = deleting;
    setDeleting(null);
    if (!target) return;
    try {
      await del(`/admin/providers/${target.id}`);
      setProviders((current) => (current ?? []).filter((p) => p.id !== target.id));
      void refreshModels();
    } catch (failure) {
      notify(errorText(failure, t("common.error")), "error");
    }
  };

  const sorted = useMemo(() => (providers ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)), [providers]);

  return (
    <div className="stack">
      <div className="page-toolbar" style={{ marginBottom: 0 }}>
        <span className="summary-line">{providers ? t("providers.count", { count: providers.length }) : ""}</span>
        {editing === null && (
          <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            {t("providers.add")}
          </button>
        )}
      </div>
      {error && (
        <div className="alert alert-danger" role="alert">
          <CircleAlert aria-hidden />
          <span>{error}</span>
        </div>
      )}
      {editing === "new" && <ProviderEditor provider={null} onSaved={(p, m) => void saved(p, m)} onCancel={() => setEditing(null)} />}
      {providers === null ? (
        [0, 1].map((i) => <div key={i} className="skeleton" style={{ height: 160, borderRadius: 12 }} />)
      ) : sorted.length === 0 && editing === null && !error ? (
        <div className="panel empty">
          <span className="empty-icon">
            <Plug aria-hidden />
          </span>
          <h3>{t("providers.emptyTitle")}</h3>
          <p>{t("providers.emptyHint")}</p>
          <button type="button" className="btn btn-primary" style={{ marginTop: "var(--space-3)" }} onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            {t("providers.add")}
          </button>
        </div>
      ) : (
        sorted.map((provider) =>
          editing !== null && editing !== "new" && editing.id === provider.id ? (
            <ProviderEditor key={provider.id} provider={provider} onSaved={(p) => void saved(p)} onCancel={() => setEditing(null)} />
          ) : (
            <ProviderPanel
              key={provider.id}
              provider={provider}
              onChange={replace}
              onEdit={() => setEditing(provider)}
              onDelete={() => setDeleting(provider)}
            />
          ),
        )
      )}
      <ConfirmDialog
        open={deleting !== null}
        title={t("providers.delete")}
        body={deleting ? t("providers.deleteConfirm", { name: deleting.name }) : ""}
        confirmLabel={t("providers.delete")}
        cancelLabel={t("nav.cancel")}
        danger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
