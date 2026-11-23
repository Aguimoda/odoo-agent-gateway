import { Check, CircleAlert, Inbox, RefreshCw, Send, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError, get, post } from "../api/client";
import type { Proposal, ProposalStatus } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { Shell } from "../shell/Shell";
import { useToast } from "../ui/Toast";
import { useWorkspace } from "../workspace";

type Tab = "pending" | "mine";

const STATUS_TONE: Record<ProposalStatus, string> = {
  pending: "badge-warning",
  applied: "badge-success",
  rejected: "badge-danger",
  conflict: "badge-danger",
  expired: "badge-danger",
  failed: "badge-danger",
};

export function StatusBadge({ status }: { status: ProposalStatus }) {
  const { t } = useI18n();
  return <span className={`badge badge-dot ${STATUS_TONE[status] ?? ""}`}>{t(`status.${status}` as MessageKey)}</span>;
}

export function display(value: unknown): string | null {
  if (value === null || value === undefined || value === false || value === "") return null;
  if (Array.isArray(value) && value.length === 2 && typeof value[1] === "string") return value[1]; // many2one
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Value({ value, kind }: { value: unknown; kind: "old" | "new" }) {
  const { t } = useI18n();
  const text = display(value);
  return text === null ? <span className="none">{t("approvals.empty")}</span> : <span className={kind}>{text}</span>;
}

function ProposalItem({
  proposal,
  mine,
  onDecided,
}: {
  proposal: Proposal;
  mine: boolean;
  onDecided: (updated: Proposal) => void;
}) {
  const { t, formatDate } = useI18n();
  const notify = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = proposal.status === "pending";

  const decide = async (action: "approve" | "reject") => {
    setBusy(action);
    setError(null);
    try {
      const updated = await post<Proposal>(`/approvals/${proposal.proposal_id}/${action}`, { note: note.trim() || null });
      onDecided({ ...proposal, ...updated });
      notify(t(`decision.${updated.status}` as MessageKey), updated.status === "applied" || updated.status === "rejected" ? "ok" : "error");
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : "";
      setError(
        code === "four_eyes" || code === "forbidden"
          ? t(`decision.${code}` as MessageKey)
          : failure instanceof ApiError
            ? failure.message
            : t("common.error"),
      );
    } finally {
      setBusy(null);
    }
  };

  const fields = Object.keys(proposal.changes).sort();
  const heading = mine
    ? t("approvals.yourProposal", { model: proposal.model, id: proposal.record_id })
    : t("approvals.proposedBy", { login: proposal.proposer, model: proposal.model, id: proposal.record_id });

  return (
    <article className="panel proposal-item" aria-labelledby={`proposal-${proposal.proposal_id}`}>
      <header className="panel-header">
        <div>
          <h2 id={`proposal-${proposal.proposal_id}`}>{heading}</h2>
          <p>
            <span className="record-ref">#{proposal.proposal_id}</span> · {formatDate(proposal.created_at)}
          </p>
        </div>
        <StatusBadge status={proposal.status} />
      </header>
      <div className="panel-body">
        <div className="reason">
          <span>{t("approvals.reason")}</span>
          <p>{proposal.reason}</p>
        </div>
        <div className="table-wrap">
          <table className="table diff">
            <thead>
              <tr>
                <th scope="col">{t("approvals.field")}</th>
                {proposal.current && <th scope="col">{t(pending ? "approvals.current" : "approvals.before")}</th>}
                <th scope="col">{t("approvals.proposed")}</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field}>
                  <td>{field}</td>
                  {proposal.current && (
                    <td>
                      <Value value={proposal.current[field]} kind="old" />
                    </td>
                  )}
                  <td>
                    <Value value={proposal.changes[field]} kind="new" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {pending ? (
          <div className="decision">
            {error && (
              <div className="alert alert-danger" role="alert">
                <CircleAlert aria-hidden />
                <span>{error}</span>
              </div>
            )}
            <div className="decision-row">
              {!mine && (
                <div className="field">
                  <label className="label" htmlFor={`note-${proposal.proposal_id}`}>
                    {t("approvals.note")}
                  </label>
                  <input
                    id={`note-${proposal.proposal_id}`}
                    className="input"
                    value={note}
                    maxLength={500}
                    onChange={(event) => setNote(event.target.value)}
                  />
                </div>
              )}
              <button type="button" className="btn" disabled={busy !== null} onClick={() => void decide("reject")}>
                {busy === "reject" ? <span className="spinner" aria-hidden /> : <X aria-hidden />}
                {mine ? t("approvals.withdraw") : t("approvals.reject")}
              </button>
              {!mine && (
                <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void decide("approve")}>
                  {busy === "approve" ? <span className="spinner" aria-hidden /> : <Check aria-hidden />}
                  {t("approvals.approve")}
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="decision">
            <p className="decided">
              {t(`decision.${proposal.status}` as MessageKey)}{" "}
              {proposal.decided_by && t("approvals.decidedBy", { login: proposal.decided_by, when: formatDate(proposal.decided_at) })}
              {proposal.decision_note && ` · “${proposal.decision_note}”`}
            </p>
          </div>
        )}
      </div>
    </article>
  );
}

export function ApprovalsPage() {
  const { t } = useI18n();
  const { refreshPending } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "mine" ? "mine" : "pending";
  const [version, setVersion] = useState(0);
  const [data, setData] = useState<{ key: string; proposals: Proposal[]; error: string | null } | null>(null);
  const key = `${tab}:${version}`;
  const proposals = data?.key === key ? data.proposals : null;
  const error = data?.key === key ? data.error : null;

  useEffect(() => {
    let active = true;
    const path = tab === "mine" ? "/approvals/mine?limit=50" : "/approvals/pending?limit=50";
    get<{ proposals: Proposal[] }>(path)
      .then((result) => {
        if (!active) return;
        setData({ key: `${tab}:${version}`, proposals: result.proposals, error: null });
        if (tab === "pending") void refreshPending();
      })
      .catch((failure: unknown) => {
        if (!active) return;
        const message = failure instanceof ApiError ? failure.message : t("approvals.loadFailed");
        setData({ key: `${tab}:${version}`, proposals: [], error: message });
      });
    return () => {
      active = false;
    };
  }, [tab, version, refreshPending, t]);

  const replace = (updated: Proposal) => {
    setData((current) =>
      current && {
        ...current,
        proposals: current.proposals.map((p) => (p.proposal_id === updated.proposal_id ? updated : p)),
      },
    );
    void refreshPending();
  };

  return (
    <Shell title={t("approvals.title")}>
      <div className="page">
        <div className="page-inner">
          <div className="page-head">
            <h1>{t("approvals.title")}</h1>
            <p>{t("approvals.lead")}</p>
          </div>
          <div className="page-toolbar">
            <div className="tabs" role="tablist" aria-label={t("approvals.title")}>
              {(["pending", "mine"] as Tab[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  className="tab"
                  aria-selected={tab === name}
                  onClick={() => setParams(name === "mine" ? { tab: "mine" } : {})}
                >
                  {name === "pending" ? <Inbox size={16} aria-hidden /> : <Send size={16} aria-hidden />}
                  {t(name === "pending" ? "approvals.pending" : "approvals.mine")}
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-sm" onClick={() => setVersion((n) => n + 1)}>
              <RefreshCw aria-hidden />
              {t("approvals.refresh")}
            </button>
          </div>

          <div role="tabpanel" className="stack">
            {error && (
              <div className="alert alert-danger" role="alert">
                <CircleAlert aria-hidden />
                <span>{error}</span>
              </div>
            )}
            {proposals === null ? (
              [0, 1].map((i) => <div key={i} className="skeleton" style={{ height: 180, borderRadius: 12 }} />)
            ) : proposals.length === 0 && !error ? (
              <div className="panel empty">
                <span className="empty-icon">{tab === "pending" ? <Inbox aria-hidden /> : <Send aria-hidden />}</span>
                <h3>{t(tab === "pending" ? "approvals.emptyPending" : "approvals.emptyMine")}</h3>
                <p>{t(tab === "pending" ? "approvals.emptyPendingHint" : "approvals.emptyMineHint")}</p>
              </div>
            ) : (
              proposals.map((proposal) => (
                <ProposalItem key={proposal.proposal_id} proposal={proposal} mine={tab === "mine"} onDecided={replace} />
              ))
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}
