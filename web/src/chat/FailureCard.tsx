import { Clock, KeyRound, RotateCw, ServerCrash, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import type { ModelChoice } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import type { Failure } from "./state";

const KNOWN = new Set([
  "rate_limited",
  "quota_exhausted",
  "auth_failed",
  "model_unavailable",
  "context_too_long",
  "provider_unavailable",
  "bad_request",
  "internal_error",
]);

export function secondsLeft(failure: Failure, now: number): number {
  if (failure.retryAfter === null) return 0;
  return Math.max(0, Math.ceil(failure.retryAfter - (now - failure.receivedAt) / 1000));
}

/** A provider failure, explained, with the choice that stays with the person (ADR 0017). */
export function FailureCard({
  failure,
  provider,
  canRetry,
  onRetry,
}: {
  failure: Failure;
  provider: string | null;
  canRetry: boolean;
  onRetry: (model: ModelChoice | null) => void;
}) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());
  const wait = secondsLeft(failure, now);

  useEffect(() => {
    if (secondsLeft(failure, Date.now()) <= 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [failure]);

  const known = KNOWN.has(failure.kind);
  const title = known
    ? t(`failure.${failure.kind}` as MessageKey, { provider: provider ?? t("failure.theProvider") })
    : failure.message || t("failure.generic");
  const tone = failure.kind === "auth_failed" || failure.kind === "internal_error" ? "danger" : "warning";
  const Icon =
    failure.kind === "auth_failed"
      ? KeyRound
      : failure.kind === "rate_limited" || failure.kind === "quota_exhausted"
        ? Clock
        : failure.kind === "provider_unavailable"
          ? ServerCrash
          : TriangleAlert;

  return (
    <div className="failure" data-tone={tone} role="alert">
      <div className="failure-head">
        <span className="failure-icon" aria-hidden>
          <Icon />
        </span>
        <div>
          <strong>{title}</strong>
          {failure.retryAfter !== null && canRetry && (
            <p aria-live="off">{wait > 0 ? t("failure.retryIn", { seconds: wait }) : t("failure.retryNow")}</p>
          )}
        </div>
      </div>
      {canRetry && (
        <>
          <div className="failure-actions">
            <button type="button" className="btn btn-sm" disabled={wait > 0} onClick={() => onRetry(null)}>
              <RotateCw aria-hidden />
              {t("failure.retry")}
            </button>
            {failure.alternatives.length > 0 && <span className="label-inline">{t("failure.switchTo")}</span>}
            {failure.alternatives.map((model) => (
              <button key={model.id} type="button" className="btn btn-sm btn-primary" onClick={() => onRetry(model)}>
                {model.label}
                <span style={{ opacity: 0.75, fontWeight: 400 }}>· {model.provider}</span>
              </button>
            ))}
          </div>
          <p className="failure-foot">{t("failure.nothingSwitches")}</p>
        </>
      )}
    </div>
  );
}
