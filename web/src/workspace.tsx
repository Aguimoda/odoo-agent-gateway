// What the shell and the pages share once signed in: conversations, models, pending count.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { del, get } from "./api/client";
import type { Conversation, ModelChoice, ModelsResponse, Proposal } from "./api/types";
import { readPreference, writePreference } from "./preferences";

interface Workspace {
  conversations: Conversation[] | null; // null while loading
  refreshConversations: () => Promise<void>;
  removeConversation: (id: string) => Promise<void>;
  models: ModelChoice[] | null;
  defaultModel: number | null;
  selectedModel: number | null;
  selectModel: (id: number | null) => void;
  refreshModels: () => Promise<void>;
  pendingCount: number;
  refreshPending: () => Promise<void>;
}

const WorkspaceContext = createContext<Workspace | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [models, setModels] = useState<ModelChoice[] | null>(null);
  const [defaultModel, setDefaultModel] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(() => {
    const saved = Number(readPreference("model"));
    return Number.isInteger(saved) && saved > 0 ? saved : null;
  });
  const [pendingCount, setPendingCount] = useState(0);

  const refreshConversations = useCallback(async () => {
    try {
      const result = await get<{ conversations: Conversation[] }>("/agent/conversations");
      setConversations(result.conversations);
    } catch {
      setConversations((current) => current ?? []);
    }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const result = await get<ModelsResponse>("/agent/models");
      setModels(result.models);
      setDefaultModel(result.default);
    } catch {
      setModels([]);
    }
  }, []);

  const refreshPending = useCallback(async () => {
    try {
      const result = await get<{ proposals: Proposal[] }>("/approvals/pending");
      setPendingCount(result.proposals.length);
    } catch {
      setPendingCount(0);
    }
  }, []);

  const removeConversation = useCallback(async (id: string) => {
    await del(`/agent/conversations/${encodeURIComponent(id)}`);
    setConversations((current) => (current ?? []).filter((c) => c.id !== id));
  }, []);

  useEffect(() => {
    let active = true;
    get<{ conversations: Conversation[] }>("/agent/conversations")
      .then((result) => active && setConversations(result.conversations))
      .catch(() => active && setConversations([]));
    get<ModelsResponse>("/agent/models")
      .then((result) => {
        if (!active) return;
        setModels(result.models);
        setDefaultModel(result.default);
      })
      .catch(() => active && setModels([]));
    const pending = () =>
      get<{ proposals: Proposal[] }>("/approvals/pending")
        .then((result) => active && setPendingCount(result.proposals.length))
        .catch(() => undefined);
    void pending();
    const timer = window.setInterval(() => void pending(), 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  // A saved choice that is no longer available falls back to the default.
  const selectedModel = models && selected !== null && !models.some((m) => m.id === selected) ? null : selected;

  const value = useMemo<Workspace>(
    () => ({
      conversations,
      refreshConversations,
      removeConversation,
      models,
      defaultModel,
      selectedModel,
      selectModel: (id) => {
        setSelected(id);
        writePreference("model", id === null ? "" : String(id));
      },
      refreshModels,
      pendingCount,
      refreshPending,
    }),
    [conversations, refreshConversations, removeConversation, models, defaultModel, selectedModel, refreshModels, pendingCount, refreshPending],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("useWorkspace outside WorkspaceProvider");
  return context;
}
