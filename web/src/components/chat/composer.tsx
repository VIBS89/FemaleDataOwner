"use client";

import { useEffect, useRef } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}

export function Composer({ value, onChange, onSubmit, busy, disabled, placeholder, autoFocus }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const canSend = value.trim().length >= 2 && !busy && !disabled;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className={cn(
        "bg-card focus-within:ring-ring/30 focus-within:border-ring relative flex items-end gap-2 rounded-2xl border p-2 shadow-sm transition",
        disabled && "opacity-60",
      )}
    >
      <textarea
        ref={ref}
        rows={1}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        placeholder={placeholder ?? "Pregunta dónde está un dato, qué significa o cómo se relaciona…"}
        aria-label="Pregunta"
        maxLength={2000}
        className="placeholder:text-muted-foreground max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none"
      />
      <Button type="submit" size="icon" className="size-9 shrink-0 rounded-xl" disabled={!canSend} aria-label="Enviar pregunta">
        {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
      </Button>
    </form>
  );
}
