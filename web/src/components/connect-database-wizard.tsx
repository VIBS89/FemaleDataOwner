"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, CheckCircle2, Database, DatabaseZap, Loader2, Lock, MessageSquare, PlugZap, RefreshCw } from "lucide-react";

import { BuildSteps, useBuildJob } from "@/components/build-progress";
import { useSession } from "@/components/session-provider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { ENV_LABEL, number } from "@/lib/format";
import type { BuildJob, DatabaseProbe, ServerConfig } from "@/lib/types";

type Step = "server" | "databases" | "running" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "server", label: "Servidor" },
  { key: "databases", label: "Bases" },
  { key: "running", label: "Descubrir" },
  { key: "done", label: "Listo" },
];

interface Summary {
  databases: number;
  objects: number;
  columns: number;
}

/**
 * Asistente "Conectar base de datos": prueba un servidor con la credencial de la sesión, deja elegir sus bases con
 * casillas (sin escribir nombres) y lo conecta y descubre en un paso. Con `server`, añade bases a uno del inventario.
 * Se monta al abrirlo y se desmonta al cerrarlo: cada apertura empieza de cero.
 */
export function ConnectDatabaseWizard({
  server,
  onClose,
  onConnected,
}: {
  server: ServerConfig | null;
  onClose: () => void;
  onConnected: () => void | Promise<void>;
}) {
  const { status, refreshStatus } = useSession();
  const ids = useId();
  const [step, setStep] = useState<Step>(server ? "databases" : "server");
  const [form, setForm] = useState({ alias: "", host: "", environment: "desarrollo", trust: false });
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [databases, setDatabases] = useState<DatabaseProbe[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [future, setFuture] = useState(false);
  const [enrich, setEnrich] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connected, setConnected] = useState<{ id: string; alias: string } | null>(null);
  const [summary, setSummary] = useState<Summary | "loading" | null>(null);

  const accessible = useMemo(() => (databases ?? []).filter((d) => d.accessible), [databases]);
  const missing = useMemo(() => {
    // Bases que el inventario pide y el servidor ya no ofrece a este login: al guardar dejarían de descubrirse.
    if (!server || !databases || server.databases.includes("*")) return [];
    const offered = new Set(accessible.map((d) => d.name.toLowerCase()));
    return server.databases.filter((d) => !offered.has(d.toLowerCase()));
  }, [server, databases, accessible]);

  const probe = useCallback(
    async (body: { host: string; trust_server_certificate: boolean } | { server_id: string }) => {
      setProbing(true);
      setProbeError(null);
      try {
        const res = await api.probeServer(body);
        if (!res.connected) {
          setProbeError(res.error ?? "No se pudo conectar al servidor");
          return;
        }
        const open = res.databases.filter((d) => d.accessible).map((d) => d.name);
        const all = !server || server.databases.includes("*");
        const wanted = new Set((server?.databases ?? []).map((d) => d.toLowerCase()));
        setDatabases(res.databases);
        setSelected(new Set(all ? open : open.filter((d) => wanted.has(d.toLowerCase()))));
        setFuture(!!server && server.databases.includes("*"));
        setStep("databases");
      } catch (e) {
        setProbeError(e instanceof Error ? e.message : "No se pudo probar la conexión");
      } finally {
        setProbing(false);
      }
    },
    [server],
  );

  useEffect(() => {
    if (server) void probe({ server_id: server.id });
  }, [server, probe]);

  // Un descubrimiento muy corto termina antes de que se vuelva a pintar: el id se lee de aquí, no del estado.
  const connectedId = useRef<string | null>(null);
  const finished = useCallback(
    async (j: BuildJob) => {
      setSummary(j.status === "ok" ? "loading" : null);
      setStep("done");
      await refreshStatus();
      await onConnected();
      const serverId = connectedId.current;
      if (j.status !== "ok" || !serverId) {
        setSummary(null);
        return;
      }
      try {
        const groups = (await api.databases()).filter((g) => g.server === serverId);
        setSummary({
          databases: groups.length,
          objects: groups.reduce((n, g) => n + g.tables + g.views + g.procedures, 0),
          columns: groups.reduce((n, g) => n + g.columns, 0),
        });
      } catch {
        setSummary(null); // el catálogo se publicó; solo falta el resumen
      }
    },
    [onConnected, refreshStatus],
  );
  const { job, tick, follow } = useBuildJob(finished);

  async function connect() {
    setConnecting(true);
    setConnectError(null);
    try {
      const res = await api.connectServer({
        ...(server
          ? { server_id: server.id }
          : {
              host: form.host.trim(),
              alias: form.alias.trim(),
              environment: form.environment,
              trust_server_certificate: form.trust,
            }),
        databases: future ? ["*"] : [...selected],
        enrich,
      });
      connectedId.current = res.server.id;
      setConnected(res.server);
      setStep("running");
      await onConnected(); // el inventario ya cambió aunque el descubrimiento siga
      follow(res.job);
    } catch (e) {
      setConnectError(e instanceof Error ? e.message : "No se pudo conectar el servidor");
    } finally {
      setConnecting(false);
    }
  }

  function toggle(name: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  }

  const allChecked = accessible.length > 0 && accessible.every((d) => selected.has(d.name));
  const someChecked = accessible.some((d) => selected.has(d.name));
  const canConnect = future || selected.size > 0;
  const stepIndex = STEPS.findIndex((s) => s.key === step);
  const title = server ? `Añadir bases a ${server.alias}` : "Conectar base de datos";

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PlugZap className="text-primary size-5" /> {title}
          </DialogTitle>
          <DialogDescription>
            Se prueba con tu login de SQL Server. El agente lee solo la estructura (nunca valores) y los usuarios ven solo el nombre visible, nunca el host.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-label="Pasos">
          {STEPS.filter((s) => !(server && s.key === "server")).map((s) => {
            const i = STEPS.findIndex((x) => x.key === s.key);
            const state = i < stepIndex ? "done" : i === stepIndex ? "now" : "next";
            return (
              <li
                key={s.key}
                aria-current={state === "now" ? "step" : undefined}
                className={`flex items-center gap-1.5 ${state === "now" ? "text-foreground font-medium" : "text-muted-foreground"}`}
              >
                <span
                  className={`flex size-5 items-center justify-center rounded-full border ${
                    state === "done" ? "border-conf-high bg-conf-high-bg text-conf-high" : state === "now" ? "border-primary text-primary" : ""
                  }`}
                >
                  {state === "done" ? <CheckCircle2 className="size-3" /> : i + (server ? 0 : 1)}
                </span>
                {s.label}
              </li>
            );
          })}
        </ol>

        <div aria-live="polite" className="min-h-0">
          {/* (a) Servidor */}
          {step === "server" && (
            <form
              id={`${ids}-server`}
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                void probe({ host: form.host.trim(), trust_server_certificate: form.trust });
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={`${ids}-host`}>Host (servidor,puerto o servidor\instancia)</Label>
                  <Input
                    id={`${ids}-host`}
                    required
                    autoFocus
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="sql01.banco.local"
                    value={form.host}
                    onChange={(e) => setForm({ ...form, host: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`${ids}-alias`}>Nombre visible</Label>
                  <Input
                    id={`${ids}-alias`}
                    required
                    maxLength={80}
                    placeholder="SQL Producción Préstamos"
                    value={form.alias}
                    onChange={(e) => setForm({ ...form, alias: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`${ids}-env`}>Ambiente</Label>
                  <Select value={form.environment} onValueChange={(v) => setForm({ ...form, environment: v })}>
                    <SelectTrigger id={`${ids}-env`} className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(ENV_LABEL).map(([k, v]) => (
                        <SelectItem key={k} value={k}>
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <label className="flex w-full items-center justify-between gap-3 rounded-lg border p-2.5 text-sm">
                    <span className="grid">
                      <span>Confiar en certificado autofirmado</span>
                      <span className="text-muted-foreground text-xs">Solo desarrollo; en qa y producción se rechaza.</span>
                    </span>
                    <Switch checked={form.trust} onCheckedChange={(v) => setForm({ ...form, trust: v })} />
                  </label>
                </div>
              </div>
              {probeError && <ProblemAlert title="No se pudo conectar" message={probeError} />}
            </form>
          )}

          {/* (b) Bases */}
          {step === "databases" &&
            (probing || !databases ? (
              probeError ? (
                <ProblemAlert title="No se pudo leer el servidor" message={probeError} />
              ) : (
                <p className="text-muted-foreground flex items-center gap-2 py-8 text-sm" role="status">
                  <Loader2 className="size-4 animate-spin" /> Probando la conexión y leyendo las bases…
                </p>
              )
            ) : (
              <div className="space-y-3">
                {databases.length === 0 ? (
                  <p className="text-muted-foreground py-6 text-center text-sm">El servidor no tiene bases de usuario que tu login pueda ver.</p>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <label className="flex items-center gap-2 text-sm font-medium">
                        <input
                          type="checkbox"
                          className="accent-primary size-4"
                          checked={allChecked}
                          ref={(el) => {
                            if (el) el.indeterminate = someChecked && !allChecked;
                          }}
                          disabled={future || accessible.length === 0}
                          onChange={(e) => setSelected(new Set(e.target.checked ? accessible.map((d) => d.name) : []))}
                        />
                        Todas las accesibles ({accessible.length} de {databases.length})
                      </label>
                      <span className="text-muted-foreground text-xs">{future ? "Todas, también las futuras" : `${selected.size} elegidas`}</span>
                    </div>
                    <fieldset className="max-h-72 overflow-y-auto rounded-lg border" disabled={future}>
                      <legend className="sr-only">Bases de datos del servidor</legend>
                      <ul className="divide-y">
                        {databases.map((d) => {
                          const reasonId = `${ids}-why-${d.name}`;
                          return (
                            <li key={d.name}>
                              <label
                                className={`flex items-center gap-3 px-3 py-2 text-sm ${d.accessible ? "hover:bg-accent/50 cursor-pointer" : "opacity-60"}`}
                              >
                                <input
                                  type="checkbox"
                                  className="accent-primary size-4 shrink-0"
                                  checked={future ? d.accessible : selected.has(d.name)}
                                  disabled={!d.accessible}
                                  aria-describedby={d.reason ? reasonId : undefined}
                                  onChange={(e) => toggle(d.name, e.target.checked)}
                                />
                                {d.accessible ? <Database className="text-muted-foreground size-4 shrink-0" /> : <Lock className="size-4 shrink-0" />}
                                <span className="min-w-0 flex-1 truncate font-mono text-xs">{d.name}</span>
                                {d.accessible ? (
                                  <span className="text-muted-foreground text-xs tabular-nums">
                                    {d.tables === null ? "sin conteo" : `${number(d.tables)} tablas · ${number(d.views ?? 0)} vistas`}
                                  </span>
                                ) : (
                                  <span id={reasonId} className="text-muted-foreground text-xs">
                                    {d.reason ?? "No disponible"}
                                  </span>
                                )}
                              </label>
                            </li>
                          );
                        })}
                      </ul>
                    </fieldset>
                  </>
                )}
                <label className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
                  <span className="grid">
                    <span className="font-medium">Incluir también las bases que se creen después</span>
                    <span className="text-muted-foreground text-xs">Cada actualización del catálogo descubrirá todas las bases a las que entre el login.</span>
                  </span>
                  <Switch checked={future} onCheckedChange={setFuture} />
                </label>
                <label className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
                  <span className="grid">
                    <span className="font-medium">Enriquecer con IA</span>
                    <span className="text-muted-foreground text-xs">
                      {status?.llm ? "Sugiere descripciones y sinónimos (marcadas “sin revisar”)." : "Requiere configurar el gateway de LLM (CONVERDATA_MODELS)."}
                    </span>
                  </span>
                  <Switch checked={enrich} onCheckedChange={setEnrich} disabled={!status?.llm} />
                </label>
                {missing.length > 0 && !future && (
                  <Alert>
                    <AlertCircle />
                    <AlertTitle>Ya no aparecen en el servidor</AlertTitle>
                    <AlertDescription>
                      {missing.join(", ")}: al guardar dejarán de descubrirse. Puede que tu login ya no tenga acceso.
                    </AlertDescription>
                  </Alert>
                )}
                {connectError && <ProblemAlert title="No se pudo conectar el servidor" message={connectError} />}
              </div>
            ))}

          {/* (c) Descubrimiento */}
          {step === "running" && (
            <div className="space-y-4" role="status">
              <p className="text-sm">
                Descubriendo los esquemas de <span className="font-medium">{connected?.alias}</span>. Puedes cerrar esta ventana: seguirá en
                “Descubrir esquemas”.
              </p>
              <BuildSteps job={job} tick={tick} enrich={enrich} />
              <Progress value={Math.min(15 + tick * 6, 92)} className="h-1.5" aria-label="Avance del descubrimiento" />
            </div>
          )}

          {/* (d) Resumen */}
          {step === "done" &&
            (job?.status === "ok" ? (
              <div className="space-y-4">
                <p className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 className="text-conf-high size-4" /> {connected?.alias} quedó conectado y su catálogo está listo.
                </p>
                {summary === "loading" ? (
                  <p className="text-muted-foreground flex items-center gap-2 text-sm">
                    <Loader2 className="size-4 animate-spin" /> Contando lo descubierto…
                  </p>
                ) : summary ? (
                  <div className="grid grid-cols-3 gap-3">
                    <SummaryStat label="Bases de datos" value={summary.databases} />
                    <SummaryStat label="Objetos" value={summary.objects} />
                    <SummaryStat label="Columnas" value={summary.columns} />
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm">El catálogo se publicó; el resumen no está disponible ahora.</p>
                )}
                {job.report && Object.keys(job.report.servers_failed).length > 0 && (
                  <Alert>
                    <AlertCircle />
                    <AlertTitle>Otros servidores no respondieron</AlertTitle>
                    <AlertDescription>Se conservó su último catálogo. Revisa “Descubrir esquemas”.</AlertDescription>
                  </Alert>
                )}
              </div>
            ) : (
              <ProblemAlert
                title="El descubrimiento terminó con errores"
                message={job?.error ?? "Revisa “Descubrir esquemas” para ver el detalle."}
              />
            ))}
        </div>

        <DialogFooter>
          {step === "server" && (
            <>
              <Button variant="outline" onClick={onClose}>
                Cancelar
              </Button>
              <Button type="submit" form={`${ids}-server`} disabled={probing || !form.host.trim() || !form.alias.trim()}>
                {probing ? <Loader2 className="animate-spin" /> : <PlugZap />} {probing ? "Probando…" : "Probar conexión"}
              </Button>
            </>
          )}
          {step === "databases" && (
            <>
              {server ? (
                <Button variant="outline" onClick={onClose}>
                  Cancelar
                </Button>
              ) : (
                <Button variant="outline" onClick={() => setStep("server")} disabled={connecting}>
                  Atrás
                </Button>
              )}
              {server && probeError && (
                <Button variant="outline" onClick={() => void probe({ server_id: server.id })} disabled={probing}>
                  <RefreshCw /> Reintentar
                </Button>
              )}
              <Button onClick={() => void connect()} disabled={connecting || probing || !databases || !canConnect}>
                {connecting ? <Loader2 className="animate-spin" /> : <DatabaseZap />} {connecting ? "Conectando…" : "Conectar y descubrir"}
              </Button>
            </>
          )}
          {step === "running" && (
            <Button variant="outline" onClick={onClose}>
              Cerrar
            </Button>
          )}
          {step === "done" && (
            <>
              <Button variant="outline" onClick={onClose}>
                Cerrar
              </Button>
              {job?.status === "ok" && (
                <>
                  <Button variant="outline" asChild>
                    <Link href="/catalogo">
                      <Database /> Ver en el Catálogo
                    </Link>
                  </Button>
                  <Button asChild>
                    <Link href="/">
                      <MessageSquare /> Ir al chat
                    </Link>
                  </Button>
                </>
              )}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProblemAlert({ title, message }: { title: string; message: string }) {
  return (
    <Alert variant="destructive" role="alert">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <p className="text-lg font-semibold tabular-nums">{number(value)}</p>
      <p className="text-muted-foreground text-xs">{label}</p>
    </div>
  );
}
