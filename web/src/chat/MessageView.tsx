import { Check, Copy, FilePen, Info, Square } from "lucide-react";
import { memo, useState } from "react";
import { Link } from "react-router";

import type { ModelChoice } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { Markdown } from "../ui/Markdown";
import { FailureCard } from "./FailureCard";
import type { ChatMessage } from "./state";
import { ToolTrail } from "./ToolTrail";

interface Props {
  message: ChatMessage;
  login: string;
  isLast: boolean;
  onRetry: (model: ModelChoice | null) => void;
}

export const MessageView = memo(function MessageView({ message, login, isLast, onRetry }: Props) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <h2 className="sr-only">{t("chat.you")}</h2>
        <div className="bubble">{message.content}</div>
      </div>
    );
  }

  const streaming = message.status === "streaming";
  const waiting = streaming && !message.content && !message.tools.length;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // clipboard refused: nothing to do
    }
  };

  return (
    <article className="msg msg-assistant" aria-busy={streaming}>
      <h2 className="sr-only">{t("chat.assistant")}</h2>
      <ToolTrail tools={message.tools} login={login} running={streaming} />

      {waiting && (
        <div className="thinking">
          <span className="thinking-dots" aria-hidden>
            <span />
            <span />
            <span />
          </span>
          {t("chat.thinking")}
        </div>
      )}

      {message.content && (
        <div className="answer">
          <Markdown text={message.content} />
          {streaming && <span className="caret" aria-hidden />}
        </div>
      )}

      {message.proposals.map((proposal) => (
        <div key={proposal.id} className="proposal">
          <FilePen aria-hidden />
          <strong>
            {t("proposal.title", { id: proposal.id })}
            <span className="badge badge-warning badge-dot">{t("status.pending")}</span>
          </strong>
          <p>{t("proposal.pending")}</p>
          <Link to="/approvals?tab=mine">{t("proposal.view")}</Link>
        </div>
      ))}

      {message.notices.map((kind, index) => (
        <p key={index} className="notice">
          <Info aria-hidden />
          {kind === "step_limit" || kind === "history_trimmed" ? t(`notice.${kind}` as MessageKey) : kind}
        </p>
      ))}

      {message.status === "stopped" && (
        <p className="msg-status">
          <Square aria-hidden />
          {t("chat.stopped")}
        </p>
      )}
      {message.status === "incomplete" && <p className="msg-status">{t("chat.incomplete")}</p>}

      {message.failure && (
        <FailureCard failure={message.failure} provider={message.provider} canRetry={isLast} onRetry={onRetry} />
      )}

      {!streaming && message.content && (
        <div className="msg-meta">
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            onClick={() => void copy()}
            aria-label={copied ? t("chat.copied") : t("chat.copy")}
            title={copied ? t("chat.copied") : t("chat.copy")}
          >
            {copied ? <Check /> : <Copy />}
          </button>
          {message.model && <span className="model-name">{message.model}</span>}
        </div>
      )}
    </article>
  );
});
