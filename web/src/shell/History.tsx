import { Trash2 } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router";

import type { Conversation } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { useToast } from "../ui/Toast";
import { useWorkspace } from "../workspace";

const DAY = 24 * 60 * 60 * 1000;

export function groupByAge(conversations: Conversation[], now = new Date()): [MessageKey, Conversation[]][] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: Record<"nav.today" | "nav.week" | "nav.older", Conversation[]> = {
    "nav.today": [],
    "nav.week": [],
    "nav.older": [],
  };
  for (const conversation of conversations) {
    const at = new Date(conversation.updated_at).getTime();
    const key = at >= startOfToday ? "nav.today" : at >= startOfToday - 6 * DAY ? "nav.week" : "nav.older";
    groups[key].push(conversation);
  }
  return (Object.entries(groups) as [MessageKey, Conversation[]][]).filter(([, list]) => list.length);
}

export function History() {
  const { t } = useI18n();
  const notify = useToast();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const { conversations, removeConversation } = useWorkspace();
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  const confirmDelete = async () => {
    const target = deleting;
    setDeleting(null);
    if (!target) return;
    try {
      await removeConversation(target.id);
      if (target.id === conversationId) navigate("/chat");
    } catch {
      notify(t("common.error"), "error");
    }
  };

  return (
    <div className="history" aria-label={t("nav.history")}>
      {conversations === null ? (
        <div className="history-group" aria-hidden>
          {[70, 55, 80, 45].map((width, i) => (
            <div key={i} className="skeleton" style={{ height: 14, width: `${width}%`, margin: "10px 12px" }} />
          ))}
        </div>
      ) : conversations.length === 0 ? (
        <p className="history-empty">{t("nav.noHistory")}</p>
      ) : (
        groupByAge(conversations).map(([label, list]) => (
          <section key={label} className="history-group">
            <h2 className="history-label">{t(label)}</h2>
            {list.map((conversation) => (
              <div key={conversation.id} className="history-item">
                <NavLink to={`/chat/${conversation.id}`} title={conversation.title}>
                  {conversation.title}
                </NavLink>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon"
                  aria-label={`${t("nav.deleteChat")}: ${conversation.title}`}
                  onClick={() => setDeleting(conversation)}
                >
                  <Trash2 />
                </button>
              </div>
            ))}
          </section>
        ))
      )}
      <ConfirmDialog
        open={deleting !== null}
        title={t("nav.deleteChat")}
        body={deleting ? t("nav.deleteConfirm", { title: deleting.title }) : ""}
        confirmLabel={t("nav.delete")}
        cancelLabel={t("nav.cancel")}
        danger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
