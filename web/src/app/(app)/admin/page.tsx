"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  DatabaseZap,
  Loader2,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { useSession } from "@/components/session-provider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { dateTime, ENV_LABEL, number, pct } from "@/lib/format";
import type { AuditRow, BuildJob, ServerConfig } from "@/lib/types";

export default function AdminPage() {
  const { isAdmin } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (!isAdmin) router.replace("/");
  }, [isAdmin, router]);
  if (!isAdmin) return null;

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Administración" />
      <div className="mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6">
        <Tabs defaultValue="build">
          <TabsList>
            <TabsTrigger value="build">
              <DatabaseZap /> Descubrir esquemas
            </TabsTrigger>
            <TabsTrigger value="servers">
              <Server /> Servidores
            </TabsTrigger>
            <TabsTrigger value="audit">
              <Network /> Auditoría
            </TabsTrigger>
          </TabsList>
          <TabsContent value="build" className="mt-5">
            <BuildPanel />
          </TabsContent>
          <TabsContent value="servers" className="mt-5">
            <ServersPanel />
          </TabsContent>
          <TabsContent value="audit" className="mt-5">
            <AuditPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// --- CatalogBuildFlow ------------------------------------------------------------------------------
const BUILD_STEPS = [
  { key: "extract", label: "Leer metadatos", hint: "Objetos, columnas, llaves, descripciones y dependencias de sys.*" },
  { key: "enrich", label: "Enriquecer", hint: "Descripciones y sinónimos sugeridos por IA (opcional)" },
  { key: "relate", label: "Relacionar", hint: "Entidades entre BDs y linaje de vistas" },
  { key: "write", label: "Escribir catálogo", hint: "Formato F1, listo para el agente" },
];

function BuildPanel() {
  const { status, refreshStatus } = useSession();
  const [job, setJob] = useState<BuildJob | null>(null);
  const [enrich, setEnrich] = useState(false);
  const [tick, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    const j = await api.buildStatus();
    setJob(j);
    if (j.status !== "running" && timer.current) {
      clearInterval(timer.current);
      timer.current = null;
      await refreshStatus();
      if (j.status === "ok") toast.success("Catálogo listo", { description: "Ya puedes preguntar al agente." });
      else if (j.status === "error") toast.error("La construcción terminó con errores");
    }
    return j;
  }, [refreshStatus]);

  useEffect(() => {
    poll().then((j) => {
      if (j.status === "running") timer.current = setInterval(poll, 1200);
    });
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [poll]);

  useEffect(() => {
    if (job?.status !== "running") return;
    const t = setInterval(() => setTick((x) => x + 1), 900);
    return () => clearInterval(t);
  }, [job?.status]);

  async function start() {
    try {
      const j = await api.startBuild(enrich);
      setJob(j);
      setTick(0);
      if (!timer.current) timer.current = setInterval(poll, 1200);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo iniciar");
    }
  }

  const running = job?.status === "running";
  const r = job?.report;
  const activeStep = Math.min(Math.floor(tick / 2), BUILD_STEPS.length - 1);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseZap className="text-primary size-5" />
            {status?.has_catalog ? "Actualizar el catálogo" : "Descubrir los esquemas por primera vez"}
          </CardTitle>
          <CardDescription>
            El agente se conecta con tu login a los servidores del inventario, lee solo la estructura (nunca valores de datos) y escribe el
            catálogo. Al actualizar, respeta las descripciones editadas por personas y no reprocesa lo que no cambió.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="space-y-3">
            {BUILD_STEPS.map((s, i) => {
              const done = job?.status === "ok" || (running && i < activeStep);
              const now = running && i === activeStep;
              const skipped = s.key === "enrich" && (running ? !job?.enrich : !enrich);
              return (
                <li key={s.key} className="flex items-start gap-3">
                  <div
                    className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs ${
                      done ? "border-conf-high bg-conf-high-bg text-conf-high" : now ? "border-primary text-primary" : "text-muted-foreground"
                    }`}
                  >
                    {done ? <CheckCircle2 className="size-3.5" /> : now ? <Loader2 className="size-3.5 animate-spin" /> : i + 1}
                  </div>
                  <div className={skipped ? "opacity-50" : ""}>
                    <p className="text-sm font-medium">
                      {s.label}
                      {skipped && <span className="text-muted-foreground font-normal"> · omitido</span>}
                    </p>
                    <p className="text-muted-foreground text-xs">{s.hint}</p>
                  </div>
                </li>
              );
            })}
          </ol>
          {running && <Progress value={Math.min(15 + tick * 6, 92)} className="h-1.5" />}
          <label className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
            <span className="grid">
              <span className="flex items-center gap-1.5 font-medium">
                <Sparkles className="size-3.5" /> Enriquecer con IA
              </span>
              <span className="text-muted-foreground text-xs">
                {status?.llm ? "Sugiere descripciones y sinónimos (marcadas “sin revisar”)." : "Requiere configurar el gateway de LLM (CONVERDATA_MODELS)."}
              </span>
            </span>
            <Switch checked={enrich} onCheckedChange={setEnrich} disabled={!status?.llm || running} />
          </label>
        </CardContent>
        <CardFooter>
          <Button size="lg" className="w-full" onClick={start} disabled={running || !status?.has_inventory}>
            {running ? <Loader2 className="animate-spin" /> : status?.has_catalog ? <RefreshCw /> : <DatabaseZap />}
            {running ? "Descubriendo…" : status?.has_catalog ? "Actualizar catálogo" : "Descubrir esquemas"}
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Última ejecución</CardTitle>
          <CardDescription>
            {job?.finished_at
              ? `${dateTime(job.finished_at)} · por ${job.triggered_by}`
              : running
                ? `En curso desde ${dateTime(job?.started_at)}`
                : "Aún no se ha ejecutado en este proceso."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {job?.error && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>Con errores</AlertTitle>
              <AlertDescription>{job.error}</AlertDescription>
            </Alert>
          )}
          {r ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Bases de datos" value={r.databases.length} />
                <Stat label="Objetos" value={r.objects} />
                <Stat label="Columnas" value={r.columns} />
                <Stat label="Sin cambios" value={r.reused} />
                <Stat label="Enriquecidos" value={r.enriched} />
                <Stat label="Duración" value={`${r.seconds.toFixed(1)} s`} />
              </div>
              {r.entities.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-muted-foreground text-xs font-medium">Entidades encontradas en varias BDs</p>
                  <div className="flex flex-wrap gap-1.5">
                    {r.entities.map((e) => (
                      <Badge key={e} variant="secondary" className="font-normal">
                        {e}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              <div className="space-y-1.5">
                <p className="text-muted-foreground text-xs font-medium">Bases descubiertas</p>
                <div className="flex flex-wrap gap-1.5">
                  {r.databases.map((d) => (
                    <Badge key={d} variant="outline" className="gap-1 font-normal">
                      <Database className="size-3" /> {d.split("/")[1] ?? d}
                    </Badge>
                  ))}
                </div>
              </div>
              {Object.keys(r.servers_failed).length > 0 && (
                <Alert>
                  <AlertCircle />
                  <AlertTitle>Servidores no disponibles</AlertTitle>
                  <AlertDescription>
                    {Object.entries(r.servers_failed).map(([k, v]) => (
                      <div key={k}>
                        {k}: {v}
                      </div>
                    ))}
                  </AlertDescription>
                </Alert>
              )}
            </>
          ) : running ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">
              {status?.has_catalog
                ? `Catálogo cargado: ${status.catalog.databases} BDs, ${number(status.catalog.objects)} objetos y ${number(status.catalog.columns)} columnas.`
                : "Cuando lo ejecutes verás aquí qué encontró el agente."}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <p className="text-lg font-semibold tabular-nums">{typeof value === "number" ? number(value) : value}</p>
      <p className="text-muted-foreground text-xs">{label}</p>
    </div>
  );
}

// --- Inventario de servidores ------------------------------------------------------------------------
const EMPTY: ServerConfig = {
  id: "",
  host: "",
  alias: "",
  environment: "desarrollo",
  is_reference: false,
  databases: ["*"],
  trust_server_certificate: false,
};

function ServersPanel() {
  const { refreshStatus } = useSession();
  const [servers, setServers] = useState<ServerConfig[] | null>(null);
  const [editing, setEditing] = useState<{ index: number | null; value: ServerConfig } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => api.inventory().then((d) => setServers(d.servers)), []);
  useEffect(() => {
    load().catch((e: Error) => toast.error(e.message));
  }, [load]);

  async function save(next: ServerConfig[]) {
    setSaving(true);
    try {
      const res = await api.saveInventory(next.map((s) => ({ ...s, connected: undefined })));
      const issues = Object.entries(res.connections).filter(([, v]) => v !== "conectado");
      if (issues.length) toast.warning(`Guardado. Sin conexión con tu credencial en: ${issues.map(([k, v]) => `${k} (${v})`).join(", ")}`);
      else toast.success("Inventario guardado");
      await load();
      await refreshStatus();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  function submitEdit() {
    if (!editing || !servers) return;
    const v = editing.value;
    const value = { ...v, id: v.id || v.alias.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "") };
    const next = editing.index === null ? [...servers, value] : servers.map((s, i) => (i === editing.index ? value : s));
    setEditing(null);
    save(next);
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Servidores del inventario</CardTitle>
          <CardDescription>
            Dónde busca el agente. “Todas” descubre todas las BDs que el login puede ver. Los servidores nuevos se prueban con tu misma credencial.
          </CardDescription>
        </div>
        <Button size="sm" onClick={() => setEditing({ index: null, value: { ...EMPTY } })} disabled={saving}>
          <Plus /> Agregar
        </Button>
      </CardHeader>
      <CardContent>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead>Servidor</TableHead>
                <TableHead>Ambiente</TableHead>
                <TableHead>Bases</TableHead>
                <TableHead>Tu sesión</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {servers === null ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-8 w-full" />
                  </TableCell>
                </TableRow>
              ) : (
                servers.map((s, i) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      <div className="font-medium">{s.alias}</div>
                      <div className="text-muted-foreground font-mono text-xs">{s.host}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{ENV_LABEL[s.environment] ?? s.environment}</Badge>
                      {s.is_reference && <span className="text-muted-foreground ml-1.5 text-xs">referencia</span>}
                    </TableCell>
                    <TableCell className="text-xs">{s.databases.join(", ") === "*" ? "Todas" : s.databases.join(", ")}</TableCell>
                    <TableCell>
                      {s.connected ? (
                        <span className="text-conf-high flex items-center gap-1 text-xs">
                          <CheckCircle2 className="size-3.5" /> Conectado
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-xs">Sin credencial</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon-sm" aria-label="Editar" onClick={() => setEditing({ index: i, value: { ...s } })}>
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Quitar"
                        disabled={servers.length === 1 || saving}
                        onClick={() => save(servers.filter((_, j) => j !== i))}
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing?.index === null ? "Agregar servidor" : "Editar servidor"}</DialogTitle>
            <DialogDescription>El host nunca se muestra a los usuarios; ven solo el nombre visible.</DialogDescription>
          </DialogHeader>
          {editing && (
            <form
              id="server-form"
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                submitEdit();
              }}
            >
              <Field label="Nombre visible">
                <Input required value={editing.value.alias} onChange={(e) => setEditing({ ...editing, value: { ...editing.value, alias: e.target.value } })} />
              </Field>
              <Field label="Host (servidor,puerto o servidor\instancia)">
                <Input required value={editing.value.host} onChange={(e) => setEditing({ ...editing, value: { ...editing.value, host: e.target.value } })} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Ambiente">
                  <Select value={editing.value.environment} onValueChange={(v) => setEditing({ ...editing, value: { ...editing.value, environment: v } })}>
                    <SelectTrigger className="w-full">
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
                </Field>
                <Field label="Bases (coma; * = todas)">
                  <Input
                    value={editing.value.databases.join(", ")}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        value: { ...editing.value, databases: e.target.value.split(",").map((d) => d.trim()).filter(Boolean) },
                      })
                    }
                  />
                </Field>
              </div>
              <label className="flex items-center justify-between text-sm">
                Copia de referencia del ambiente
                <Switch checked={editing.value.is_reference} onCheckedChange={(v) => setEditing({ ...editing, value: { ...editing.value, is_reference: v } })} />
              </label>
              <label className="flex items-center justify-between text-sm">
                Confiar en certificado autofirmado
                <Switch
                  checked={editing.value.trust_server_certificate}
                  onCheckedChange={(v) => setEditing({ ...editing, value: { ...editing.value, trust_server_certificate: v } })}
                />
              </label>
            </form>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancelar
            </Button>
            <Button type="submit" form="server-form">
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

// --- Auditoría -------------------------------------------------------------------------------------
const AUDIT_KIND: Record<string, string> = {
  question: "Pregunta",
  feedback: "Retroalimentación",
  login: "Inicio de sesión",
  login_failed: "Login fallido",
  logout: "Cierre de sesión",
  catalog_build_started: "Construcción iniciada",
  catalog_build_finished: "Construcción terminada",
  inventory_updated: "Inventario",
};

function AuditPanel() {
  const [kind, setKind] = useState("all");
  const [rows, setRows] = useState<AuditRow[] | null>(null);

  const load = useCallback(() => {
    setRows(null);
    api
      .audit(kind === "all" ? undefined : kind)
      .then((d) => setRows(d.items))
      .catch((e: Error) => toast.error(e.message));
  }, [kind]);
  useEffect(load, [load]);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Registro de auditoría</CardTitle>
          <CardDescription>Cada pregunta con sus pasos y candidatos, inicios de sesión y cambios. Nunca contiene contraseñas.</CardDescription>
        </div>
        <div className="flex gap-2">
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos los eventos</SelectItem>
              {Object.entries(AUDIT_KIND).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={load} aria-label="Recargar">
            <RefreshCw />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="w-40">Fecha</TableHead>
                <TableHead className="w-36">Evento</TableHead>
                <TableHead className="w-32">Usuario</TableHead>
                <TableHead>Detalle</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows === null ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Skeleton className="h-8 w-full" />
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground py-8 text-center">
                    Sin eventos.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-muted-foreground align-top text-xs whitespace-nowrap">{dateTime(r.ts)}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={r.type === "login_failed" ? "destructive" : "secondary"} className="font-normal">
                        {AUDIT_KIND[r.type] ?? r.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="align-top font-mono text-xs">{r.user_id ?? "—"}</TableCell>
                    <TableCell className="align-top text-xs whitespace-normal">{describe(r)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

function describe(r: AuditRow): string {
  switch (r.type) {
    case "question":
      return `“${r.question}” → ${r.status}${r.confidence != null ? ` · ${pct(r.confidence)}` : ""}${r.duration_ms != null ? ` · ${r.duration_ms} ms` : ""}`;
    case "feedback":
      return `${r.verdict === "confirm" ? "Es este" : "No es"}: ${r.asset_key}`;
    case "catalog_build_finished":
      return `${r.status}${r.objects != null ? ` · ${r.objects} objetos` : ""}${r.error ? ` · ${r.error}` : ""}`;
    case "login":
      return `Servidores: ${(r.servers as string[] | undefined)?.join(", ") ?? "—"}`;
    case "inventory_updated":
      return `Servidores: ${(r.servers as string[] | undefined)?.join(", ") ?? "—"}`;
    default:
      return "";
  }
}
