import { Check, CircleAlert, Plus, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, get, post } from "../api/client";
import type { CatalogModel, CatalogResult, Provider } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { useToast } from "../ui/Toast";
import { filterCatalog, formatTokens } from "./catalog";

const TOOLS_TONE = { yes: "badge-success", no: "", unknown: "" } as const;

function ToolsBadge({ tools }: { tools: boolean | null }) {
  const { t } = useI18n();
  const key = tools === true ? "yes" : tools === false ? "no" : "unknown";
  return <span className={`badge ${TOOLS_TONE[key]}`}>{t(`catalog.tools.${key}` as MessageKey)}</span>;
}

/** Everything the provider offers, to add models with one click (ADR 0020). */
export function CatalogView({
  provider,
  onChange,
  onClose,
}: {
  provider: Provider;
  onChange: (provider: Provider) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const notify = useToast();
  const [result, setResult] = useState<CatalogResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [toolsOnly, setToolsOnly] = useState(false);
  const [allKinds, setAllKinds] = useState(false);

  const fetchCatalog = useCallback(
    (refresh: boolean): Promise<CatalogResult> =>
      get<CatalogResult>(`/admin/providers/${provider.id}/catalog${refresh ? "?refresh=true" : ""}`).catch(
        (failure: unknown) => ({ ok: false, message: failure instanceof ApiError ? failure.message : t("common.error") }),
      ),
    [provider.id, t],
  );

  useEffect(() => {
    let live = true;
    void fetchCatalog(false).then((loaded) => {
      if (!live) return;
      setResult(loaded);
      setLoading(false);
    });
    return () => {
      live = false;
    };
  }, [fetchCatalog]);

  const load = async (refresh: boolean) => {
    setLoading(true);
    setResult(await fetchCatalog(refresh));
    setLoading(false);
  };

  const added = useMemo(() => new Set(provider.models.map((m) => m.name)), [provider.models]);
  const models = result?.models ?? [];
  const shown = filterCatalog(models, { query, toolsOnly, allKinds });

  const add = async (model: CatalogModel) => {
    setBusy(model.id);
    try {
      onChange(
        await post<Provider>(`/admin/providers/${provider.id}/models`, {
          name: model.id,
          is_default: !provider.models.some((m) => m.is_default),
        }),
      );
    } catch (failure) {
      notify(failure instanceof ApiError ? failure.message : t("common.error"), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="catalog" aria-labelledby={`catalog-${provider.id}`}>
      <div className="models-head">
        <h3 id={`catalog-${provider.id}`}>{t("catalog.title")}</h3>
        <div className="row-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load(true)} disabled={loading}>
            {loading ? <span className="spinner" aria-hidden /> : <RefreshCw aria-hidden />}
            {t("catalog.refresh")}
          </button>
          <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label={t("nav.cancel")} title={t("nav.cancel")}>
            <X />
          </button>
        </div>
      </div>

      {result && !result.ok ? (
        <div className="alert alert-danger" role="alert">
          <CircleAlert aria-hidden />
          <span>{t("catalog.failed", { reason: result.message ?? result.error ?? "" })}</span>
        </div>
      ) : (
        <>
          <p className="help">{t("catalog.hint")}</p>
          <div className="catalog-filters">
            <input
              className="input"
              type="search"
              placeholder={t("catalog.search")}
              aria-label={t("catalog.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <label className="check">
              <input type="checkbox" checked={toolsOnly} onChange={(e) => setToolsOnly(e.target.checked)} />
              {t("catalog.toolsOnly")}
            </label>
            <label className="check">
              <input type="checkbox" checked={allKinds} onChange={(e) => setAllKinds(e.target.checked)} />
              {t("catalog.allKinds")}
            </label>
            <span className="help tabular" aria-live="polite">
              {t("catalog.count", { shown: shown.length, total: models.length })}
            </span>
          </div>
          {loading && !result ? (
            <p className="help">{t("catalog.loading")}</p>
          ) : shown.length === 0 ? (
            <p className="help">{t("catalog.empty")}</p>
          ) : (
            <div className="table-wrap catalog-table">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t("catalog.model")}</th>
                    <th scope="col">{t("catalog.context")}</th>
                    <th scope="col">{t("catalog.toolsHeader")}</th>
                    <th scope="col">
                      <span className="sr-only">{t("catalog.add")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((model) => {
                    const isAdded = added.has(model.id) || model.added;
                    return (
                      <tr key={model.id}>
                        <td>
                          <span className="model-row-name">{model.id}</span>
                          {model.kind !== "chat" && <span className="badge">{t(`catalog.kind.${model.kind}` as MessageKey)}</span>}
                        </td>
                        <td className="tabular">{formatTokens(model.context_window)}</td>
                        <td>
                          <ToolsBadge tools={model.tools} />
                        </td>
                        <td>
                          {isAdded ? (
                            <span className="help catalog-added">
                              <Check aria-hidden /> {t("catalog.added")}
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-sm"
                              disabled={busy !== null}
                              onClick={() => void add(model)}
                              aria-label={`${t("catalog.add")}: ${model.id}`}
                            >
                              {busy === model.id ? <span className="spinner" aria-hidden /> : <Plus aria-hidden />}
                              {t("catalog.add")}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
