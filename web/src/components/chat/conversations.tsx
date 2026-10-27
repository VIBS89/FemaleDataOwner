"use client";

// Conversaciones del usuario en su propio navegador (localStorage). El servidor no guarda chats (F17); solo la
// auditoría registra cada pregunta.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useSession } from "@/components/session-provider";
import type { AnswerEnvelope } from "@/lib/types";

export type Verdict = "confirm" | "reject";

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: number;
  envelope?: AnswerEnvelope;
  error?: string;
  feedback?: Record<string, Verdict>;
  escalated?: string; // id de la solicitud al responsable (F24)
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
}

interface ConversationsValue {
  conversations: Conversation[];
  activeId: string | null;
  active: Conversation | null;
  select: (id: string | null) => void;
  create: (firstQuestion: string) => Conversation;
  append: (conversationId: string, message: Message) => void;
  update: (conversationId: string, messageId: string, patch: Partial<Message>) => void;
  remove: (id: string) => void;
  clear: () => void;
}

const Ctx = createContext<ConversationsValue | null>(null);
const MAX_CONVERSATIONS = 50;

export const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

function storageKey(userId: string) {
  return `converdata:conversations:${userId}`;
}

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useSession();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    try {
      const raw = localStorage.getItem(storageKey(user.user_id));
      setConversations(raw ? (JSON.parse(raw) as Conversation[]) : []);
    } catch {
      setConversations([]);
    }
    setActiveId(null);
    setLoadedFor(user.user_id);
  }, [user]);

  useEffect(() => {
    if (!user || loadedFor !== user.user_id) return;
    try {
      localStorage.setItem(storageKey(user.user_id), JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)));
    } catch {}
  }, [conversations, user, loadedFor]);

  const create = useCallback((firstQuestion: string) => {
    const now = Date.now();
    const conv: Conversation = {
      id: uid(),
      title: firstQuestion.length > 60 ? `${firstQuestion.slice(0, 57)}…` : firstQuestion,
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
    return conv;
  }, []);

  const append = useCallback((conversationId: string, message: Message) => {
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id === conversationId ? { ...c, updatedAt: Date.now(), messages: [...c.messages, message] } : c,
      );
      return next.sort((a, b) => b.updatedAt - a.updatedAt);
    });
  }, []);

  const update = useCallback((conversationId: string, messageId: string, patch: Partial<Message>) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conversationId
          ? { ...c, messages: c.messages.map((m) => (m.id === messageId ? { ...m, ...patch } : m)) }
          : c,
      ),
    );
  }, []);

  const remove = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    setActiveId((cur) => (cur === id ? null : cur));
  }, []);

  const clear = useCallback(() => {
    setConversations([]);
    setActiveId(null);
  }, []);

  const value = useMemo(
    () => ({
      conversations,
      activeId,
      active: conversations.find((c) => c.id === activeId) ?? null,
      select: setActiveId,
      create,
      append,
      update,
      remove,
      clear,
    }),
    [conversations, activeId, create, append, update, remove, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConversations() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useConversations fuera de ConversationsProvider");
  return ctx;
}
