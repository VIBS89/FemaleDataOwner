"use client";

import {
  AlertCircle,
  ArrowRight,
  Ban,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  HelpCircle,
  Info,
  Link2,
  Route,
  Search,
  Sparkles,
  Timer,
  UserRoundSearch,
} from "lucide-react";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import type { AssetTab } from "@/components/asset-sheet";
import { CandidateCard } from "@/components/chat/candidate-card";
import type { Message, Verdict } from "@/components/chat/conversations";
import { ConfidencePill } from "@/components/confidence";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { pct, RELATION_LABEL, shortName } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  message: Message;
  onAsk: (question: string) => void;
  onVerdict: (assetKey: string, verdict: Verdict) => Promise<void>;
  onOpenAsset: (assetKey: string, tab?: AssetTab) => void;
  onEscalate: () => Promise<void>;
}

export function AssistantAvatar() {
  return (
    <div className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full shadow-sm">
      <Sparkles className="size-3.5" />
    </div>
  );
}

export function AssistantMessage({ message, onAsk, onVerdict, onOpenAsset, onEscalate }: Props) {
  if (message.error) {
    return (
      <Row>
        <Alert variant="destructive" className="max-w-xl">
          <AlertCircle />
          <AlertTitle>No pude responder</AlertTitle>
          <AlertDescription>{message.error}</AlertDescription>
        </Alert>
      </Row>
    );
  }
  const env = message.envelope!;
  const disc = env.discovery;
  const top = disc?.candidates[0];

  return (
    <Row>
      <div className="min-w-0 flex-1 space-y-4">
        {env.status === "rejected" ? (
          <p className="text-muted-foreground flex items-start gap-2 text-sm">
            <Ban className="mt-0.5 size-4 shrink-0" /> {env.answer_text}
          </p>
        ) : env.status === "error" ? (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertDescription>{env.answer_text}</AlertDescription>
          </Alert>
        ) : (
          <p className="text-[15px] leading-relaxed whitespace-pre-line">{env.answer_text}</p>
        )}

        {env.assumptions.map((a) => (
          <p key={a} className="text-muted-foreground flex items-start gap-2 rounded-md bg-muted/60 px-3 py-2 text-xs">
            <Info className="mt-0.5 size-3.5 shrink-0" /> {a}
          </p>
        ))}

        {env.status === "needs_clarification" && env.clarification?.options?.length ? (
          <div className="flex flex-wrap gap-2">
            {env.clarification.options.map((o) => (
              <Button key={o} variant="outline" size="sm" className="h-auto py-1.5 whitespace-normal" onClick={() => onAsk(o)}>
                <HelpCircle /> {o}
              </Button>
            ))}
          </div>
        ) : null}

        {disc && disc.candidates.length > 0 && (
          <div className="space-y-3">
            {disc.candidates.map((c, i) => (
              <CandidateCard
                key={c.asset_key}
                candidate={c}
                best={i === 0}
                verdict={message.feedback?.[c.asset_key]}
                onVerdict={(v) => onVerdict(c.asset_key, v)}
                onOpen={() => onOpenAsset(c.asset_key)}
                onRelated={() => onOpenAsset(c.asset_key, "relations")}
              />
            ))}
          </div>
        )}

        {disc?.knowledge_gap && (
          <Alert className="border-conf-mid/30 bg-conf-mid-bg">
            <UserRoundSearch className="text-conf-mid!" />
            <AlertTitle className="line-clamp-none">
              {top ? "Evidencia insuficiente para recomendar con seguridad" : "No encontré nada que tu login pueda ver"}
            </AlertTitle>
            <AlertDescription>
              {top ? (
                <p>
                  Conviene confirmarlo con el responsable del dominio
                  {top.owners.business ? `: ${top.owners.business}` : top.owners.technical ? `: ${top.owners.technical}` : ""}. Si
                  alguno de los candidatos es el correcto, márcalo con “Es este” para que el agente aprenda.
                </p>
              ) : (
                <p className="mb-1">
                  Prueba con otras palabras (por ejemplo, el nombre del proceso o del sistema). Si el dato está en una base a la que no tienes
                  acceso, pídelo al responsable del dominio: el agente solo muestra lo que tu usuario de base de datos puede leer.
                </p>
              )}
              <EscalateButton escalated={message.escalated} onEscalate={onEscalate} />
            </AlertDescription>
          </Alert>
        )}

        {disc && disc.alternatives.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-muted-foreground text-xs font-medium">Alternativas</h4>
            <div className="flex flex-wrap gap-2">
              {disc.alternatives.map((a) => (
                <button
                  key={a.asset_key}
                  onClick={() => onOpenAsset(a.asset_key)}
                  title={a.why}
                  className="hover:bg-accent flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs transition"
                >
                  <span className="font-mono">
                    {a.asset_key.split(".")[2]}
                    {a.asset_key.split(".").length > 3 && <span className="font-semibold">.{shortName(a.asset_key)}</span>}
                  </span>
                  <span className="text-muted-foreground hidden sm:inline">{a.asset_key.split(".")[0]}</span>
                  <ConfidencePill value={a.confidence} />
                </button>
              ))}
            </div>
          </div>
        )}

        {disc && (disc.related.length > 0 || disc.join_paths.length > 0) && (
          <Collapsible defaultOpen={disc.join_paths.length > 0}>
            <CollapsibleTrigger className="text-muted-foreground hover:text-foreground group flex items-center gap-1.5 text-xs font-medium">
              <Link2 className="size-3.5" />
              Relaciones{disc.join_paths.length > 0 ? " y cómo unir las tablas" : ""} ({disc.related.length + disc.join_paths.length})
              <ChevronDown className="size-3.5 transition group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2 space-y-3">
              {disc.join_paths.map((p) => (
                <div key={p.purpose} className="rounded-lg border bg-card p-3">
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-medium">
                    <Route className="text-primary size-3.5" /> Para “{p.purpose}”
                  </p>
                  <ol className="space-y-1">
                    {p.steps.map((s) => (
                      <li key={s} className="text-muted-foreground font-mono text-xs">
                        {s}
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
              {disc.related.length > 0 && (
                <ul className="divide-y rounded-lg border bg-card text-xs">
                  {disc.related.map((r, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-1.5 px-3 py-2">
                      <span className="font-mono">{shortName(r.from)}</span>
                      <ArrowRight className="text-muted-foreground size-3" />
                      <button className="text-primary font-mono hover:underline" onClick={() => onOpenAsset(r.to)}>
                        {r.to}
                      </button>
                      <span className="text-muted-foreground">
                        · {RELATION_LABEL[r.relation]}
                        {r.on || r.via ? `: ${r.on ?? r.via}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}

        {disc && disc.suggested_questions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {disc.suggested_questions.map((q) => (
              <Button key={q} variant="secondary" size="sm" className="h-auto py-1.5 font-normal whitespace-normal" onClick={() => onAsk(q)}>
                <Search /> {q}
              </Button>
            ))}
          </div>
        )}

        {env.status === "ok" && !disc?.knowledge_gap && disc && disc.candidates.length > 0 && (
          <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
            ¿Ninguno es el dato que buscas?
            <EscalateButton escalated={message.escalated} onEscalate={onEscalate} variant="link" />
          </div>
        )}

        <Footer message={message} />
      </div>
    </Row>
  );
}

function EscalateButton({
  escalated,
  onEscalate,
  variant = "outline",
}: {
  escalated?: string;
  onEscalate: () => Promise<void>;
  variant?: "outline" | "link";
}) {
  const [sending, setSending] = useState(false);
  if (escalated) {
    return (
      <span className="text-conf-high inline-flex items-center gap-1.5 text-xs font-medium">
        <CheckCircle2 className="size-3.5" /> Enviado al responsable ·{" "}
        <Link href="/solicitudes" className="underline underline-offset-2">
          ver en Mis solicitudes
        </Link>
      </span>
    );
  }
  return (
    <Button
      size="sm"
      variant={variant}
      className={variant === "link" ? "h-auto p-0 text-xs" : "mt-2 bg-background"}
      disabled={sending}
      onClick={async () => {
        setSending(true);
        try {
          await onEscalate();
        } finally {
          setSending(false);
        }
      }}
    >
      {variant === "outline" && <UserRoundSearch />} Preguntar al responsable
    </Button>
  );
}

function Footer({ message }: { message: Message }) {
  const env = message.envelope!;
  const checks = env.validation?.checks ?? [];
  return (
    <Collapsible>
      <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        {env.confidence != null && env.status === "ok" && <span>Confianza {pct(env.confidence)}</span>}
        {env.timings_ms.total != null && (
          <span className="flex items-center gap-1">
            <Timer className="size-3" /> {(env.timings_ms.total / 1000).toFixed(1)} s
          </span>
        )}
        {env.databases.length > 0 && <span>{env.databases.join(" · ")}</span>}
        <CollapsibleTrigger className="hover:text-foreground group flex items-center gap-1">
          Cómo lo obtuve <ChevronDown className="size-3 transition group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <button
          className="hover:text-foreground flex items-center gap-1"
          onClick={() => {
            navigator.clipboard.writeText(env.trace_id);
            toast.success("Id de la traza copiado", { description: "Úsalo para buscar esta respuesta en la auditoría." });
          }}
        >
          <Copy className="size-3" /> Traza
        </button>
      </div>
      <CollapsibleContent className="mt-2 rounded-lg border bg-muted/30 p-3 text-xs">
        <p className="mb-2">
          Busqué en el catálogo, diccionarios, documentos y ETL lo que tu login puede leer, prioricé los candidatos y revisé el
          resultado ({env.validation?.attempts ?? 1} {env.validation?.attempts === 1 ? "revisión" : "revisiones"}).
        </p>
        {checks.length > 0 ? (
          <ul className="space-y-1">
            {checks.map((c, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <Check className={cn("mt-0.5 size-3", c.status === "fail" ? "text-conf-low" : c.status === "warn" ? "text-conf-mid" : "text-conf-high")} />
                <span>
                  <span className="font-mono">{c.name}</span> · {c.status}
                  {c.detail ? ` — ${c.detail}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">Sin observaciones del revisor.</p>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-in-up flex gap-3">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 pt-0.5">{children}</div>
    </div>
  );
}
