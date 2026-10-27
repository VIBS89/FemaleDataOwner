"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Database, DatabaseZap, Fingerprint, GitMerge, Loader2, Receipt, ScanSearch, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { AssetSheet, type AssetRef } from "@/components/asset-sheet";
import { AssistantMessage } from "@/components/chat/assistant-message";
import { Composer } from "@/components/chat/composer";
import { uid, useConversations, type Verdict } from "@/components/chat/conversations";
import { Thinking, type FlowStep } from "@/components/chat/thinking";
import { PageHeader } from "@/components/page-header";
import { useSession } from "@/components/session-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { number } from "@/lib/format";

const STEP_MS = 260;

const EXAMPLES = [
  { icon: Fingerprint, text: "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital." },
  { icon: ScanSearch, text: "¿Qué proceso llena la dimensión de clientes del DWH?" },
  { icon: GitMerge, text: "¿Cómo relaciono los clientes con sus tarjetas de crédito?" },
  { icon: Receipt, text: "¿Qué tabla tiene los pagos de las cuotas de préstamos?" },
];

export default function ChatPage() {
  const { user, status, isAdmin } = useSession();
  const { active, create, append, update } = useConversations();
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<string | null>(null); // id de la conversación que espera respuesta
  const [asset, setAsset] = useState<AssetRef | null>(null);
  const [steps, setSteps] = useState<FlowStep[]>([]);
  const scroller = useRef<HTMLDivElement>(null);
  const lastQuestion = useRef<HTMLDivElement>(null);

  const messages = useMemo(() => active?.messages ?? [], [active]);
  const busy = pending !== null && pending === active?.id;
  const lastUserId = [...messages].reverse().find((m) => m.role === "user")?.id;
  const noCatalog = status && !status.has_catalog;

  useEffect(() => {
    // Mientras piensa, al fondo; al llegar la respuesta, la pregunta arriba para leer la tarjeta principal completa.
    const el = scroller.current;
    if (!el) return;
    const frame = requestAnimationFrame(() => {
      const last = messages[messages.length - 1];
      if (!busy && last?.role === "assistant" && lastQuestion.current) {
        el.scrollTo({ top: lastQuestion.current.offsetTop - 16, behavior: "smooth" });
      } else {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, busy, steps.length]);

  async function ask(text: string) {
    const question = text.trim();
    if (question.length < 2 || pending) return;
    const conv = active ?? create(question);
    const history = (active?.messages ?? []).filter((m) => m.role === "user").map((m) => m.text).slice(-5);
    append(conv.id, { id: uid(), role: "user", text: question, createdAt: Date.now() });
    setInput("");
    setSteps([]);
    setPending(conv.id);
    // Cada paso real del grafo se ve al menos STEP_MS: en modo determinista el flujo entero tarda ~30 ms.
    const queue: FlowStep[] = [];
    let shown = 0;
    let lastShown = 0;
    const reveal = async () => {
      while (shown < queue.length) {
        const wait = lastShown + STEP_MS - Date.now();
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        const step = queue[shown++];
        lastShown = Date.now();
        setSteps((prev) => [...prev, step]);
      }
    };
    let revealing = Promise.resolve();
    try {
      const envelope = await api.discoverStream(question, history, (step) => {
        queue.push(step);
        revealing = revealing.then(reveal);
      });
      await revealing;
      await new Promise((r) => setTimeout(r, STEP_MS));
      append(conv.id, { id: uid(), role: "assistant", text: envelope.answer_text, envelope, createdAt: Date.now() });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        toast.warning(e.message);
        setInput(question);
      }
      append(conv.id, {
        id: uid(),
        role: "assistant",
        text: "",
        error: e instanceof Error ? e.message : "Error desconocido",
        createdAt: Date.now(),
      });
    } finally {
      setPending(null);
    }
  }

  async function verdict(messageId: string, traceId: string, assetKey: string, v: Verdict, current?: Record<string, Verdict>) {
    if (!active) return;
    try {
      await api.feedback(traceId, assetKey, v);
      update(active.id, messageId, { feedback: { ...current, [assetKey]: v } });
      toast.success(v === "confirm" ? "¡Gracias! Lo tendré en cuenta en preguntas parecidas." : "Gracias, queda registrado.", {
        description: v === "confirm" ? "Con dos confirmaciones de distintas personas, la recomendación gana confianza." : undefined,
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo registrar");
    }
  }

  async function escalate(messageId: string, traceId: string) {
    if (!active) return;
    try {
      const req = await api.escalate(traceId);
      update(active.id, messageId, { escalated: req.id });
      toast.success("Le pregunté al responsable del dominio", {
        description: "Verás la respuesta en Mis solicitudes; el agente la usará para todos.",
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo escalar");
    }
  }

  return (
    <div className="flex h-svh flex-col">
      <PageHeader title={active?.title ?? "Nueva pregunta"}>
        {status?.has_catalog && isAdmin && (
          <Badge variant="outline" className="text-muted-foreground hidden gap-1.5 font-normal sm:flex">
            <Database className="size-3" />
            {status.catalog.databases} BDs · {number(status.catalog.objects)} objetos
          </Badge>
        )}
      </PageHeader>

      <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
          {messages.length === 0 ? (
            noCatalog ? (
              <SetupNeeded isAdmin={isAdmin} building={status.build.status === "running"} />
            ) : (
              <Welcome name={user?.user_id ?? ""} onPick={(q) => ask(q)} />
            )
          ) : (
            <div className="space-y-8">
              {messages.map((m) =>
                m.role === "user" ? (
                  <div
                    key={m.id}
                    ref={m.id === lastUserId ? lastQuestion : undefined}
                    className="animate-in-up flex justify-end"
                  >
                    <div className="bg-primary text-primary-foreground max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-[15px] whitespace-pre-line shadow-sm">
                      {m.text}
                    </div>
                  </div>
                ) : (
                  <AssistantMessage
                    key={m.id}
                    message={m}
                    onAsk={ask}
                    onOpenAsset={(assetKey, tab) => setAsset({ assetKey, tab })}
                    onEscalate={() => escalate(m.id, m.envelope!.trace_id)}
                    onVerdict={(assetKey, v) => verdict(m.id, m.envelope!.trace_id, assetKey, v, m.feedback)}
                  />
                ),
              )}
              {busy && <Thinking steps={steps} />}
            </div>
          )}
          <div className="h-2" />
        </div>
      </div>

      <div className="bg-gradient-to-t from-background via-background to-transparent pt-2">
        <div className="mx-auto w-full max-w-3xl px-4 pb-4 sm:px-6">
          <Composer
            value={input}
            onChange={setInput}
            onSubmit={() => ask(input)}
            busy={busy}
            disabled={!!noCatalog}
            autoFocus
            placeholder={noCatalog ? "Disponible cuando el catálogo esté listo" : undefined}
          />
          <p className="text-muted-foreground mt-2 text-center text-[11px]">
            ConverData solo usa metadatos y lo que tu login puede leer. Verifica la recomendación antes de usarla en un proceso.
          </p>
        </div>
      </div>

      <AssetSheet target={asset} onClose={() => setAsset(null)} />
    </div>
  );
}

function Welcome({ name, onPick }: { name: string; onPick: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center pt-8 text-center sm:pt-16">
      <div className="bg-primary/10 text-primary mb-5 flex size-14 items-center justify-center rounded-2xl">
        <Sparkles className="size-6" />
      </div>
      <h2 className="text-2xl font-semibold tracking-tight">Hola, {name.replace(/^.*\\/, "")}. ¿Qué dato buscas?</h2>
      <p className="text-muted-foreground mt-2 max-w-lg text-sm">
        Te digo en qué base, tabla y columna está, qué significa, qué reglas aplican, con qué se relaciona y cuánta confianza merece.
      </p>
      <div className="mt-8 grid w-full gap-3 sm:grid-cols-2">
        {EXAMPLES.map((e) => (
          <button
            key={e.text}
            onClick={() => onPick(e.text)}
            className="group bg-card hover:border-primary/40 hover:bg-accent/40 flex items-start gap-3 rounded-xl border p-4 text-left text-sm shadow-xs transition"
          >
            <e.icon className="text-muted-foreground group-hover:text-primary mt-0.5 size-4 shrink-0" />
            {e.text}
          </button>
        ))}
      </div>
    </div>
  );
}

function SetupNeeded({ isAdmin, building }: { isAdmin: boolean; building: boolean }) {
  return (
    <Card className="mx-auto mt-10 max-w-lg text-center">
      <CardContent className="flex flex-col items-center gap-4 py-10">
        <div className="bg-primary/10 text-primary flex size-14 items-center justify-center rounded-2xl">
          {building ? <Loader2 className="size-6 animate-spin" /> : <DatabaseZap className="size-6" />}
        </div>
        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold">
            {building ? "El agente está descubriendo los esquemas" : "Todavía no hay catálogo"}
          </h2>
          <p className="text-muted-foreground text-sm">
            {building
              ? "Está leyendo la estructura de las bases de datos (sin leer datos). Podrás preguntar en cuanto termine."
              : isAdmin
                ? "Es la primera vez: el agente debe leer los esquemas de tus bases de datos con tu acceso para poder responder."
                : "Un administrador de datos debe descubrir los esquemas antes de que puedas preguntar."}
          </p>
        </div>
        {isAdmin && (
          <Button asChild size="lg">
            <Link href="/admin">{building ? "Ver progreso" : "Descubrir esquemas"}</Link>
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
