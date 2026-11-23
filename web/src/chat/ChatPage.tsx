import { ArrowDown, MessageSquareText } from "lucide-react";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError, get, post, request } from "../api/client";
import { agentEvents } from "../api/sse";
import type { Conversation, ConversationDetail, ModelChoice } from "../api/types";
import { useI18n, type MessageKey } from "../i18n";
import { useSession } from "../session";
import { Shell } from "../shell/Shell";
import { useWorkspace } from "../workspace";
import { Composer } from "./Composer";
import { MessageView } from "./MessageView";
import { chatReducer, emptyChat } from "./state";

const SUGGESTIONS: MessageKey[] = ["chat.suggest1", "chat.suggest2", "chat.suggest3"];

export function ChatPage() {
  const { t } = useI18n();
  const { me } = useSession();
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const workspace = useWorkspace();
  const [state, dispatch] = useReducer(chatReducer, emptyChat);
  const [draft, setDraft] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!conversationId);
  const [announcement, setAnnouncement] = useState("");
  const [pinned, setPinned] = useState(true);
  // The conversation this page created for its first message: its answer is streaming.
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [shownId, setShownId] = useState(conversationId);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // Another conversation in the address: reset what is shown, during render (no effect).
  if (shownId !== conversationId) {
    setShownId(conversationId);
    if (!conversationId || conversationId !== createdId) {
      if (createdId) setCreatedId(null);
      dispatch({ type: "load", messages: [] });
      setLoadError(null);
      setLoading(!!conversationId);
    }
  }

  // Load it from the gateway, unless it is the one being written right now.
  useEffect(() => {
    if (conversationId && conversationId === createdId) return;
    abort.current?.abort();
    if (!conversationId) return;
    let active = true;
    get<ConversationDetail>(`/agent/conversations/${encodeURIComponent(conversationId)}`)
      .then((detail) => {
        if (active) dispatch({ type: "load", messages: detail.messages });
      })
      .catch((error: unknown) => {
        if (active) {
          setLoadError(error instanceof ApiError && error.status === 404 ? t("chat.notFound") : t("chat.loadFailed"));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load only when the address changes
  }, [conversationId]);

  // Keep the newest text in view while the person has not scrolled up.
  useEffect(() => {
    const element = scroller.current;
    if (element && pinned) element.scrollTop = element.scrollHeight;
  }, [state.messages, pinned]);

  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    setPinned(element.scrollHeight - element.scrollTop - element.clientHeight < 80);
  };

  /** Stream one answer. `typed` goes back in the box if the gateway refuses it. */
  const run = useCallback(
    async (path: string, body: unknown, typed?: string) => {
      const controller = new AbortController();
      abort.current = controller;
      setPinned(true);
      let finished = false;
      let text = "";
      try {
        const response = await request("POST", path, body, controller.signal);
        for await (const event of agentEvents(response)) {
          dispatch({ type: "event", event, now: Date.now() });
          if (event.type === "token") text += event.data.text;
          if (event.type === "done") setAnnouncement(text.slice(0, 600)); // for screen readers
          if (event.type === "done" || event.type === "error") finished = true;
        }
        if (!finished) dispatch({ type: "stopped" });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          dispatch({ type: "stopped" });
        } else {
          const known: Record<string, MessageKey> = {
            rate_limited: "failure.rate_limited.api",
            not_found: "chat.notFound",
            network: "common.network",
          };
          const code = error instanceof ApiError ? error.code : "internal_error";
          const key = known[code];
          const message = key ? t(key) : error instanceof ApiError ? error.message : t("common.error");
          dispatch({ type: "refused", now: Date.now(), kind: code, message });
          if (typed) setDraft((current) => current || typed); // nothing typed is lost
        }
      } finally {
        if (abort.current === controller) abort.current = null;
        void workspace.refreshConversations();
      }
    },
    [t, workspace],
  );

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || state.streaming) return;
      setDraft("");
      dispatch({ type: "sent", text: content, now: Date.now() });
      let id = conversationId;
      if (!id) {
        try {
          const created = await post<Conversation>("/agent/conversations", { title: content.slice(0, 200) });
          id = created.id;
          setCreatedId(id);
          navigate(`/chat/${id}`, { replace: true });
        } catch (error) {
          const message = error instanceof ApiError ? error.message : t("common.error");
          dispatch({ type: "refused", now: Date.now(), kind: "internal_error", message });
          setDraft(content);
          return;
        }
      }
      await run(
        `/agent/conversations/${encodeURIComponent(id)}/messages`,
        { content, model_id: workspace.selectedModel },
        content,
      );
    },
    [conversationId, navigate, run, state.streaming, t, workspace.selectedModel],
  );

  const retry = useCallback(
    (model: ModelChoice | null) => {
      if (!conversationId || state.streaming) return;
      if (model) workspace.selectModel(model.id);
      dispatch({ type: "retrying", now: Date.now() });
      void run(`/agent/conversations/${encodeURIComponent(conversationId)}/retry`, {
        model_id: model ? model.id : workspace.selectedModel,
      });
    },
    [conversationId, run, state.streaming, workspace],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && abort.current) {
        event.preventDefault();
        stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stop]);

  const title = workspace.conversations?.find((c) => c.id === conversationId)?.title;
  const empty = !conversationId && state.messages.length === 0;
  const noModels = workspace.models !== null && workspace.models.length === 0;
  const firstName = (me?.name ?? "").split(" ")[0] ?? "";

  return (
    <Shell title={title}>
      <div className="chat">
        <div className="chat-scroll" ref={scroller} onScroll={onScroll}>
          <div className="chat-column">
            {empty ? (
              <div className="welcome">
                <h1>{t("chat.greeting", { name: firstName })}</h1>
                <p>{t("chat.lead")}</p>
                {noModels ? (
                  <div className="alert alert-warning" role="status">
                    {me?.is_admin ? t("chat.noModelsAdmin") : t("chat.noModels")}
                  </div>
                ) : (
                  <div className="suggestions">
                    {SUGGESTIONS.map((key) => (
                      <button key={key} type="button" className="suggestion" onClick={() => void send(t(key))}>
                        <MessageSquareText aria-hidden />
                        {t(key)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : loading ? (
              <div className="messages" aria-busy>
                {[60, 90, 75].map((width, i) => (
                  <div key={i} className="skeleton" style={{ height: 16, width: `${width}%`, marginLeft: i === 0 ? "auto" : 0 }} />
                ))}
              </div>
            ) : loadError ? (
              <div className="alert alert-danger" role="alert">
                {loadError}
              </div>
            ) : (
              <div className="messages">
                {state.messages.map((message, index) => (
                  <MessageView
                    key={message.key}
                    message={message}
                    login={me?.login ?? ""}
                    isLast={index === state.messages.length - 1}
                    onRetry={retry}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="composer-wrap">
          <div className="composer-anchor">
            {!pinned && state.messages.length > 0 && (
              <button type="button" className="btn btn-sm jump" onClick={() => setPinned(true)}>
                <ArrowDown aria-hidden />
                {t("chat.jumpToLatest")}
              </button>
            )}
            <Composer
              value={draft}
              onChange={setDraft}
              onSend={() => void send(draft)}
              onStop={stop}
              streaming={state.streaming}
              models={workspace.models}
              defaultModel={workspace.defaultModel}
              selectedModel={workspace.selectedModel}
              onSelectModel={workspace.selectModel}
              disabled={!!loadError}
            />
          </div>
          <p className="composer-hint">
            {t("chat.hint")} · {t("chat.disclaimer")}
          </p>
        </div>
        <div className="sr-only" aria-live="polite">
          {announcement}
        </div>
      </div>
    </Shell>
  );
}
