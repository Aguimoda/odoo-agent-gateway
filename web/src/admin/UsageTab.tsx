import { BarChart3, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, get } from "../api/client";
import type { UsageRow } from "../api/types";
import { useI18n } from "../i18n";

const PERIODS = [7, 30, 90];

export function UsageTab() {
  const { t, formatNumber } = useI18n();
  const [days, setDays] = useState(7);
  const [result, setResult] = useState<{ days: number; rows: UsageRow[]; error: string | null } | null>(null);
  const rows = result?.days === days ? result.rows : null;
  const error = result?.days === days ? result.error : null;

  useEffect(() => {
    let active = true;
    get<{ usage: UsageRow[] }>(`/admin/usage?days=${days}`)
      .then((response) => active && setResult({ days, rows: response.usage, error: null }))
      .catch((failure: unknown) => {
        if (!active) return;
        const message = failure instanceof ApiError ? failure.message : t("common.error");
        setResult({ days, rows: [], error: message });
      });
    return () => {
      active = false;
    };
  }, [days, t]);

  const most = Math.max(1, ...(rows ?? []).map((r) => r.calls));
  const total = (rows ?? []).reduce((sum, r) => sum + r.calls, 0);

  return (
    <div className="stack">
      <div className="page-toolbar" style={{ marginBottom: 0 }}>
        <span className="summary-line tabular">{rows ? t("usage.total", { count: formatNumber(total), days }) : ""}</span>
        <div className="segmented" role="group" aria-label={t("usage.period")}>
          {PERIODS.map((period) => (
            <button key={period} type="button" aria-pressed={days === period} onClick={() => setDays(period)}>
              {t("usage.days", { count: period })}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <div className="alert alert-danger" role="alert">
          <CircleAlert aria-hidden />
          <span>{error}</span>
        </div>
      )}
      {rows === null ? (
        <div className="skeleton" style={{ height: 200, borderRadius: 12 }} />
      ) : rows.length === 0 && !error ? (
        <div className="panel empty">
          <span className="empty-icon">
            <BarChart3 aria-hidden />
          </span>
          <h3>{t("usage.empty")}</h3>
        </div>
      ) : (
        <div className="panel table-wrap">
          <table className="table usage-table">
            <thead>
              <tr>
                <th scope="col">{t("usage.provider")}</th>
                <th scope="col">{t("usage.model")}</th>
                <th scope="col" className="num">
                  {t("usage.calls")}
                </th>
                <th scope="col">{t("usage.errors")}</th>
                <th scope="col" className="num">
                  {t("usage.tokens")}
                </th>
                <th scope="col" className="num">
                  {t("usage.latency")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const failed = row.calls - row.ok;
                return (
                  <tr key={`${row.provider}/${row.model}`}>
                    <td>{row.provider}</td>
                    <td className="mono" style={{ fontSize: "0.8125rem" }}>
                      {row.model}
                    </td>
                    <td className="num">
                      <div className="usage-cell">
                        <span
                          className="usage-bar"
                          role="img"
                          aria-label={`${t("usage.success")}: ${row.ok} / ${row.calls}`}
                          style={{ width: `${Math.max(12, (row.calls / most) * 96)}px` }}
                        >
                          <span className="ok" style={{ width: `${(row.ok / row.calls) * 100}%` }} />
                          <span className="err" style={{ width: `${(failed / row.calls) * 100}%` }} />
                        </span>
                        {formatNumber(row.calls)}
                      </div>
                    </td>
                    <td>
                      <div className="error-kinds">
                        {Object.keys(row.errors).length === 0
                          ? "—"
                          : Object.entries(row.errors).map(([kind, count]) => (
                              <span key={kind} className="badge badge-danger">
                                {kind} · {count}
                              </span>
                            ))}
                      </div>
                    </td>
                    <td className="num">
                      {formatNumber(row.prompt_tokens)} / {formatNumber(row.completion_tokens)}
                    </td>
                    <td className="num">
                      {formatNumber(row.p50_ms)} / {formatNumber(row.p95_ms)} ms
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
