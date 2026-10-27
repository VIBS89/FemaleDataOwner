"use client";

import { Check, Loader2 } from "lucide-react";

import { AssistantAvatar } from "@/components/chat/assistant-message";
import { cn } from "@/lib/utils";

export interface FlowStep {
  node: string;
  label: string;
}

// Pasos reales del DiscoverFlow recibidos por SSE (`/discover/stream`); los reintentos (C, B) aparecen como pasos repetidos.
export function Thinking({ steps }: { steps: FlowStep[] }) {
  const items = steps.length ? steps : [{ node: "start", label: "Interpretando la pregunta" }];
  return (
    <div className="animate-in-up flex gap-3">
      <AssistantAvatar />
      <div className="bg-card rounded-xl border px-4 py-3 shadow-xs">
        <ul className="space-y-1.5">
          {items.map((s, i) => {
            const last = i === items.length - 1;
            const retry = items.slice(0, i).some((p) => p.node === s.node);
            return (
              <li
                key={`${s.node}-${i}`}
                className={cn("animate-in-up flex items-center gap-2 text-sm", last ? "text-foreground font-medium" : "text-muted-foreground")}
              >
                {last ? <Loader2 className="text-primary size-3.5 animate-spin" /> : <Check className="text-conf-high size-3.5" />}
                {s.label}
                {retry && <span className="text-conf-mid text-xs font-normal">· nuevo intento</span>}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
