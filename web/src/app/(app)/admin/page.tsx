"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  BookOpen,
  Bot,
  CheckCircle2,
  Info,
  Database,
  DatabaseZap,
  Loader2,
  Network,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
  Trash2,
  UserCheck,
} from "lucide-react";
import { toast } from "sonner";

import { BuildSteps, useBuildJob } from "@/components/build-progress";
import { ConnectDatabaseWizard } from "@/components/connect-database-wizard";
import { DocsViewer } from "@/components/docs-viewer";
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
import type { AuditRow, LlmRole, LlmSettings, ServerConfig, Steward } from "@/lib/types";

const TABS = ["build", "servers", "stewards", "models", "audit", "docs"];

/** Pestaña de la URL (`?tab=docs&doc=…` abre la documentación en esa página). Solo en el navegador. */
function tabFromUrl(): string {
  if (typeof window === "undefined") return "build";
  const tab = new URLSearchParams(window.location.search).get("tab") ?? "";
  return TABS.includes(tab) ? tab : "build";
}

export default function AdminPage() {
  const { isAdmin } = useSession();
  const router = useRouter();
  const [tab, setTab] = useState(tabFromUrl);
  useEffect(() => {
    if (!isAdmin) router.replace("/");
  }, [isAdmin, router]);
  useEffect(() => {
    const onPop = () => setTab(tabFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  if (!isAdmin) return null;

  const changeTab = (value: string) => {
    setTab(value);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", value);
    if (value !== "docs") {
      url.searchParams.delete("doc");
      url.hash = "";
    }
    window.history.replaceState(null, "", url);
  };

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Administración" />
      <div className={`mx-auto w-full space-y-6 p-4 sm:p-6 ${tab === "docs" ? "max-w-7xl" : "max-w-5xl"}`}>
        <Tabs value={tab} onValueChange={changeTab}>
          <TabsList>
            <TabsTrigger value="build">
              <DatabaseZap /> Descubrir esquemas
            </TabsTrigger>
            <TabsTrigger value="servers">
              <Server /> Servidores
            </TabsTrigger>
            <TabsTrigger value="stewards">
              <UserCheck /> Responsables
            </TabsTrigger>
            <TabsTrigger value="models">
              <Bot /> Modelos de IA
            </TabsTrigger>
            <TabsTrigger value="audit">
              <Network /> Auditoría
            </TabsTrigger>
            <TabsTrigger value="docs">
              <BookOpen /> Documentación
            </TabsTrigger>
          </TabsList>
          <TabsContent value="build" className="mt-5">
            <BuildPanel />
          </TabsContent>
          <TabsContent value="servers" className="mt-5">
            <ServersPanel />
          </TabsContent>
          <TabsContent value="stewards" className="mt-5">
            <StewardsPanel />
          </TabsContent>
          <TabsContent value="models" className="mt-5">
            <ModelsPanel />
          </TabsContent>
          <TabsContent value="audit" className="mt-5">
            <AuditPanel />
          </TabsContent>
          <TabsContent value="docs" className="mt-5">
            <DocsViewer />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// --- CatalogBuildFlow ------------------------------------------------------------------------------
function BuildPanel() {
  const { status, refreshStatus } = useSession();
  // Con un modelo configurado, lo nuevo se describe con IA salvo que el administrador lo apague.
  const [enrichChoice, setEnrich] = useState<boolean | null>(null);
  const enrich = enrichChoice ?? Boolean(status?.llm);
  const { job, tick, poll, follow } = useBuildJob(async (j) => {
    await refreshStatus();
    if (j.status === "ok") toast.success("Catálogo listo", { description: "Ya puedes preguntar al agente." });
    else if (j.status === "error") toast.error("La construcción terminó con errores");
  });

  useEffect(() => {
    poll()
      .then((j) => {
        if (j.status === "running") follow(j);
      })
      .catch(() => undefined);
  }, [poll, follow]);

  async function start() {
    try {
      follow(await api.startBuild(enrich));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo iniciar");
    }
  }

  const running = job?.status === "running";
  const r = job?.report;

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseZap className="text-primary size-5" />
            {status?.has_catalog ? "Actualizar el catálogo" : "Descubrir los esquemas por primera vez"}
          </CardTitle>
          <CardDescription>
            El agente se conecta con tu login a los servidores del inventario, lee solo la estructura (nunca valores de datos) y
            escribe el catálogo. Al actualizar, respeta las descripciones editadas por personas y no reprocesa lo que no cambió.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <BuildSteps job={job} tick={tick} enrich={enrich} />
          {running && <Progress value={Math.min(15 + tick * 6, 92)} className="h-1.5" />}
          <label className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
            <span className="grid">
              <span className="flex items-center gap-1.5 font-medium">
                <Sparkles className="size-3.5" /> Enriquecer con IA
              </span>
              <span className="text-muted-foreground text-xs">
                {status?.llm
                  ? "Sugiere descripciones y sinónimos (marcadas “sin revisar”)."
                  : "Requiere configurar el gateway de LLM (CONVERDATA_MODELS)."}
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
                    {r.kept_from_failed > 0 && (
                      <div>Se conservaron {number(r.kept_from_failed)} objetos de su último catálogo.</div>
                    )}
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
  // Asistente "Conectar base de datos": `server` null = uno nuevo; si no, añade bases a ese servidor.
  const [wizard, setWizard] = useState<{ server: ServerConfig | null } | null>(null);

  const load = useCallback(() => api.inventory().then((d) => setServers(d.servers)), []);
  const reloadAfterWizard = useCallback(async () => {
    try {
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo recargar el inventario");
    }
  }, [load]);
  useEffect(() => {
    load().catch((e: Error) => toast.error(e.message));
  }, [load]);

  async function save(next: ServerConfig[]) {
    setSaving(true);
    try {
      const res = await api.saveInventory(next.map((s) => ({ ...s, connected: undefined })));
      const issues = Object.entries(res.connections).filter(([, v]) => v !== "conectado");
      if (issues.length)
        toast.warning(`Guardado. Sin conexión con tu credencial en: ${issues.map(([k, v]) => `${k} (${v})`).join(", ")}`);
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
    const value = {
      ...v,
      id:
        v.id ||
        v.alias
          .toUpperCase()
          .replace(/[^A-Z0-9]+/g, "_")
          .replace(/^_|_$/g, ""),
    };
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
            Dónde busca el agente. “Todas” descubre todas las BDs que el login puede ver. Los servidores nuevos se prueban con tu
            misma credencial.
          </CardDescription>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditing({ index: null, value: { ...EMPTY } })} disabled={saving}>
            <Plus /> Agregar a mano
          </Button>
          <Button size="sm" onClick={() => setWizard({ server: null })} disabled={saving}>
            <PlugZap /> Conectar base de datos
          </Button>
        </div>
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
                <TableHead className="w-28" />
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
                    <TableCell className="text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Añadir bases a ${s.alias}`}
                        title="Añadir bases"
                        disabled={saving}
                        onClick={() => setWizard({ server: s })}
                      >
                        <DatabaseZap />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Editar"
                        onClick={() => setEditing({ index: i, value: { ...s } })}
                      >
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
                <Input
                  required
                  value={editing.value.alias}
                  onChange={(e) => setEditing({ ...editing, value: { ...editing.value, alias: e.target.value } })}
                />
              </Field>
              <Field label="Host (servidor,puerto o servidor\instancia)">
                <Input
                  required
                  value={editing.value.host}
                  onChange={(e) => setEditing({ ...editing, value: { ...editing.value, host: e.target.value } })}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Ambiente">
                  <Select
                    value={editing.value.environment}
                    onValueChange={(v) => setEditing({ ...editing, value: { ...editing.value, environment: v } })}
                  >
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
                        value: {
                          ...editing.value,
                          databases: e.target.value
                            .split(",")
                            .map((d) => d.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                  />
                </Field>
              </div>
              <label className="flex items-center justify-between text-sm">
                Copia de referencia del ambiente
                <Switch
                  checked={editing.value.is_reference}
                  onCheckedChange={(v) => setEditing({ ...editing, value: { ...editing.value, is_reference: v } })}
                />
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

      {wizard && <ConnectDatabaseWizard server={wizard.server} onClose={() => setWizard(null)} onConnected={reloadAfterWizard} />}
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

// --- Responsables de datos (F24) ---------------------------------------------------------------------
function StewardsPanel() {
  const [stewards, setStewards] = useState<Steward[] | null>(null);
  const [domains, setDomains] = useState<string[]>([]);
  const [login, setLogin] = useState("");
  const [scope, setScope] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    () =>
      api.stewards().then((d) => {
        setStewards(d.stewards);
        setDomains(d.domains);
      }),
    [],
  );
  const [failed, setFailed] = useState(false);
  const reload = useCallback(() => {
    setFailed(false);
    // Si la lista no se pudo leer se queda sin cargar: guardar la reemplaza entera y borraría a los demás.
    load().catch((e: Error) => {
      setFailed(true);
      toast.error(e.message);
    });
  }, [load]);
  useEffect(reload, [reload]);

  async function save(next: Steward[], message: string) {
    setSaving(true);
    try {
      const res = await api.saveStewards(next);
      setStewards(res.stewards);
      toast.success(message);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  function add() {
    if (!stewards) return;
    const name = login.trim().toLowerCase();
    const wanted = scope
      .split(",")
      .map((d) => d.trim())
      .filter(Boolean);
    const next = [...stewards.filter((s) => s.login !== name), { login: name, domains: wanted.length ? wanted : ["*"] }];
    setLogin("");
    setScope("");
    save(next, `${name} es responsable de ${wanted.length ? wanted.join(", ") : "todos los dominios"}`);
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader>
          <CardTitle>Responsables de datos</CardTitle>
          <CardDescription>
            Quién puede revisar descripciones, reglas y dudas escaladas de cada dominio. Se asignan por usuario de base de datos;
            cada cambio queda en la auditoría.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>Usuario</TableHead>
                  <TableHead>Dominios</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {stewards === null ? (
                  <TableRow>
                    <TableCell colSpan={3}>
                      {failed ? (
                        <div className="text-muted-foreground flex items-center justify-between gap-3 py-2 text-sm">
                          No se pudo leer la lista de responsables.
                          <Button size="sm" variant="outline" onClick={reload}>
                            <RefreshCw /> Reintentar
                          </Button>
                        </div>
                      ) : (
                        <Skeleton className="h-8 w-full" />
                      )}
                    </TableCell>
                  </TableRow>
                ) : stewards.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-muted-foreground py-8 text-center">
                      Aún no hay responsables: solo los administradores de datos pueden curar.
                    </TableCell>
                  </TableRow>
                ) : (
                  stewards.map((s) => (
                    <TableRow key={s.login}>
                      <TableCell className="font-mono text-sm">{s.login}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5">
                          {s.domains.map((d) => (
                            <Badge key={d} variant={d === "*" ? "default" : "outline"} className="font-normal">
                              {d === "*" ? "Todos" : d}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Quitar a ${s.login}`}
                          disabled={saving}
                          onClick={() =>
                            save(
                              stewards.filter((x) => x.login !== s.login),
                              `${s.login} ya no es responsable`,
                            )
                          }
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
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Asignar responsable</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <Field label="Usuario de base de datos">
              <Input required value={login} onChange={(e) => setLogin(e.target.value)} placeholder="jperez" />
            </Field>
            <Field label="Dominios (coma; vacío = todos)">
              <Input
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                placeholder={domains.slice(0, 2).join(", ") || "prestamos"}
              />
            </Field>
            {domains.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {domains.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className="hover:bg-accent rounded-md border px-2 py-0.5 text-xs"
                    onClick={() => setScope((prev) => (prev.trim() ? `${prev.replace(/,\s*$/, "")}, ${d}` : d))}
                  >
                    {d}
                  </button>
                ))}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={saving || stewards === null || !login.trim()}>
              {saving ? <Loader2 className="animate-spin" /> : <Plus />} Asignar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// --- Modelos de IA -----------------------------------------------------------------------------------
const ROLE_LABEL: Record<string, string> = {
  fast: "Redactar y orientar",
  enrich: "Describir tablas nuevas",
  planner: "Interpretar y ordenar",
  judge: "Revisar",
};

const NO_MODEL = "none";

function RoleList({ roles }: { roles: Record<string, LlmRole> }) {
  const entries = Object.entries(roles);
  if (entries.length === 0) return null;
  return (
    <dl className="text-muted-foreground mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
      {entries.map(([role, r]) => (
        <div key={role} className="contents">
          <dt>{ROLE_LABEL[role] ?? role}</dt>
          <dd className="text-foreground font-mono break-all">{r.model}</dd>
        </div>
      ))}
    </dl>
  );
}

function ModelsPanel() {
  const { refreshStatus } = useSession();
  const [data, setData] = useState<LlmSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setFailed(false);
    api
      .llmProfiles()
      .then((d) => {
        setData(d);
        setSelected(d.active);
      })
      .catch((e: Error) => {
        setFailed(true);
        toast.error(e.message);
      });
  }, []);
  useEffect(load, [load]);

  async function apply() {
    if (!data || !selected) return;
    const noneId = data.none_id ?? NO_MODEL;
    setSaving(true);
    setError(null);
    try {
      const res = await api.setLlmProfile(selected);
      setData(res);
      setSelected(res.active);
      const name =
        selected === noneId ? "responder sin modelo de IA" : (res.profiles.find((p) => p.id === selected)?.label ?? selected);
      toast.success(selected === noneId ? `El asistente ahora va a ${name}` : `El asistente ahora usa ${name}`);
      await refreshStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo aplicar el cambio");
    } finally {
      setSaving(false);
    }
  }

  if (failed) {
    return (
      <Card>
        <CardContent className="text-muted-foreground flex items-center justify-between gap-3 py-6 text-sm">
          No se pudo leer la configuración de modelos.
          <Button size="sm" variant="outline" onClick={load}>
            <RefreshCw /> Reintentar
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (data === null) {
    return (
      <Card>
        <CardContent className="space-y-3 py-6">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }

  const noneId = data.none_id ?? NO_MODEL;
  const header = (
    <CardHeader>
      <CardTitle>Modelos de IA</CardTitle>
      <CardDescription>
        Qué proveedor de IA usa el asistente para redactar respuestas. El cambio aplica de inmediato a todos los usuarios.
      </CardDescription>
    </CardHeader>
  );

  if (!data.configured) {
    return (
      <Card>
        {header}
        <CardContent>
          <div className="text-muted-foreground rounded-lg border border-dashed py-8 text-center text-sm">
            No hay un modelo de IA configurado en el servidor: el asistente responde con reglas fijas. Para activar uno, el
            administrador del servidor debe instalar el archivo de modelos.
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data.selectable) {
    return (
      <Card>
        {header}
        <CardContent className="space-y-4">
          <Alert>
            <Info />
            <AlertTitle>Solo lectura</AlertTitle>
            <AlertDescription>
              Para poder elegir el proveedor desde esta pantalla, el archivo de modelos del servidor debe definir perfiles.
            </AlertDescription>
          </Alert>
          <div className="rounded-lg border p-4">
            <p className="text-sm font-medium">Modelos en uso</p>
            <RoleList roles={data.roles ?? {}} />
          </div>
        </CardContent>
      </Card>
    );
  }

  const options = [
    ...data.profiles.map((p) => ({
      id: p.id,
      label: p.label,
      description: p.description,
      roles: p.roles,
      disabled: !p.usable,
      reason: p.usable ? null : p.reason,
    })),
    {
      id: noneId,
      label: "Sin modelo de IA",
      description:
        "El asistente busca y responde con reglas fijas: más rápido y sin enviar nada a un proveedor, pero con respuestas menos naturales y sin aclaraciones redactadas.",
      roles: {} as Record<string, LlmRole>,
      disabled: false,
      reason: null,
    },
  ];

  return (
    <Card>
      {header}
      <CardContent className="space-y-4">
        <Alert>
          <Info />
          <AlertDescription>
            {data.data_mode === "test"
              ? "Modo de datos de prueba: estos proveedores solo pueden recibir datos ficticios."
              : data.data_mode === "real"
                ? "Modo de datos reales: solo se pueden usar proveedores autorizados para datos del banco."
                : "El modo de datos no está definido en el servidor."}{" "}
            Las claves de los proveedores no se configuran aquí: las instala el administrador del servidor.
          </AlertDescription>
        </Alert>

        <div role="radiogroup" aria-label="Proveedor de IA del asistente" className="space-y-3">
          {options.map((o) => {
            const checked = selected === o.id;
            return (
              <label
                key={o.id}
                className={`flex gap-3 rounded-lg border p-4 transition-colors has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 ${
                  o.disabled ? "cursor-not-allowed opacity-60" : "hover:bg-muted/50 cursor-pointer"
                } ${checked ? "border-primary bg-primary/5" : ""}`}
              >
                <input
                  type="radio"
                  name="llm-profile"
                  className="accent-primary mt-1 size-4 shrink-0"
                  checked={checked}
                  disabled={o.disabled || saving}
                  onChange={() => {
                    setSelected(o.id);
                    setError(null);
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{o.label}</span>
                    {data.active === o.id && (
                      <Badge>
                        <CheckCircle2 /> En uso
                      </Badge>
                    )}
                  </div>
                  {o.description && <p className="text-muted-foreground mt-1 text-sm">{o.description}</p>}
                  {o.reason && (
                    <p className="text-destructive mt-1 flex items-start gap-1.5 text-sm">
                      <AlertCircle className="mt-0.5 size-4 shrink-0" /> {o.reason}
                    </p>
                  )}
                  <RoleList roles={o.roles} />
                </div>
              </label>
            );
          })}
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertTitle>No se pudo aplicar</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
      <CardFooter className="justify-end">
        <Button onClick={apply} disabled={saving || selected === null || selected === data.active}>
          {saving ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Aplicar
        </Button>
      </CardFooter>
    </Card>
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
  inventory_updated_failed: "Inventario sin aplicar",
  inventory_probe: "Prueba de servidor",
  stewards_updated: "Responsables",
  curation_description: "Descripción editada",
  curation_rule: "Regla guardada",
  curation_rule_deleted: "Regla eliminada",
  curation_request: "Duda escalada",
  curation_answer: "Duda respondida",
  curation_dictionary: "Diccionario cargado",
  access_denied: "Acceso denegado",
  login_locked: "Login bloqueado",
  sessions_revoked: "Sesiones cerradas",
  audit_read: "Consulta de auditoría",
  manual_read: "Lectura del manual",
  doc_read: "Lectura de documentación",
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
          <CardDescription>
            Cada pregunta con sus pasos y candidatos, inicios de sesión y cambios. Nunca contiene contraseñas.
          </CardDescription>
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
    case "inventory_updated_failed":
      return `Servidores: ${((r.servers as { id: string }[] | undefined) ?? []).map((s) => s.id).join(", ") || "—"}${r.via === "connect" ? " · asistente" : ""}`;
    case "inventory_probe":
      return `Host: ${String(r.host ?? "—")}`;
    case "stewards_updated":
      return `Responsables: ${((r.stewards as Steward[] | undefined) ?? []).map((s) => s.login).join(", ") || "ninguno"}`;
    case "curation_description":
      return String(r.asset_key ?? "");
    case "curation_rule":
    case "curation_rule_deleted":
      return String(r.rule_id ?? "");
    case "curation_request":
    case "curation_answer":
      return `Dominio: ${String(r.domain ?? "—")}`;
    case "curation_dictionary":
      return `${String(r.applied ?? 0)} descripciones aplicadas`;
    case "access_denied":
      return `${String(r.method ?? "")} ${String(r.route ?? "")}`;
    case "doc_read":
      return `docs/${String(r.path ?? "")}${r.doc === "diagram" ? " · diagrama" : ""}`;
    default:
      return "";
  }
}
