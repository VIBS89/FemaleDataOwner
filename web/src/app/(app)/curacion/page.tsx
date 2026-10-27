"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Clock, Flame, Inbox, Loader2, PenLine, Plus, Scale, Trash2, Search, SearchX, Sparkles, User } from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { useSession } from "@/components/session-provider";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { CurationRequest, ManagedRule, ObjectRow, ReviewItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function CurationPage() {
  const { isSteward, user } = useSession();
  const router = useRouter();
  const [openCount, setOpenCount] = useState<number | null>(null);
  useEffect(() => {
    if (!isSteward) router.replace("/");
  }, [isSteward, router]);
  if (!isSteward) return null;

  const scope = user?.domains?.includes("*") ? "todos los dominios" : user?.domains?.join(", ");

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Curación" />
      <div className="mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Responde una vez, queda para todos</h2>
          <p className="text-muted-foreground text-sm">
            Dudas escaladas y descripciones por revisar en {scope}. Cada respuesta se vuelve conocimiento revisado del agente.
          </p>
        </div>
        <Tabs defaultValue="requests">
          <TabsList>
            <TabsTrigger value="requests">
              <Inbox /> Dudas escaladas
              {!!openCount && <Badge className="ml-1 h-5 px-1.5">{openCount}</Badge>}
            </TabsTrigger>
            <TabsTrigger value="review">
              <PenLine /> Documentar activos
            </TabsTrigger>
            <TabsTrigger value="rules">
              <Scale /> Reglas de negocio
            </TabsTrigger>
          </TabsList>
          <TabsContent value="requests" className="mt-5">
            <RequestsPanel onCount={setOpenCount} />
          </TabsContent>
          <TabsContent value="review" className="mt-5">
            <ReviewPanel />
          </TabsContent>
          <TabsContent value="rules" className="mt-5">
            <RulesPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// --- Dudas escaladas (F24, HU-30) ---------------------------------------------------------------------
function RequestsPanel({ onCount }: { onCount: (n: number) => void }) {
  const [status, setStatus] = useState<"open" | "all">("open");
  const [items, setItems] = useState<CurationRequest[] | null>(null);
  const [answering, setAnswering] = useState<CurationRequest | null>(null);

  const load = useCallback(() => {
    setItems(null);
    api
      .curationRequests(status)
      .then((d) => {
        setItems(d.items);
        if (status === "open") onCount(d.items.length);
      })
      .catch((e: Error) => {
        setItems([]);
        toast.error(e.message);
      });
  }, [status, onCount]);
  useEffect(load, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button size="sm" variant={status === "open" ? "default" : "outline"} onClick={() => setStatus("open")}>
          Pendientes
        </Button>
        <Button size="sm" variant={status === "all" ? "default" : "outline"} onClick={() => setStatus("all")}>
          Todas
        </Button>
      </div>
      {items === null ? (
        <Skeleton className="h-32 rounded-xl" />
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <CheckCircle2 className="text-conf-high size-8" />
            <p className="font-medium">Sin dudas pendientes</p>
            <p className="text-muted-foreground text-sm">Cuando alguien pulse “Preguntar al responsable” aparecerá aquí.</p>
          </CardContent>
        </Card>
      ) : (
        items.map((r) => (
          <Card key={r.id} className="animate-in-up gap-3 py-4">
            <CardContent className="space-y-3 px-4">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {r.status === "open" ? (
                  <span className="bg-conf-mid-bg text-conf-mid inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium">
                    <Clock className="size-3" /> Pendiente · {relativeTime(new Date(r.created_at).getTime())}
                  </span>
                ) : (
                  <span className="bg-conf-high-bg text-conf-high inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium">
                    <CheckCircle2 className="size-3" /> {r.status === "answered" ? "Respondida" : "Sin fuente"}
                  </span>
                )}
                <Badge variant="outline" className="font-normal">
                  {r.domain}
                </Badge>
                <span className="text-muted-foreground flex items-center gap-1">
                  <User className="size-3" /> {r.user_id}
                </span>
              </div>
              <p className="text-[15px] font-medium">“{r.question}”</p>
              {r.note && <p className="text-muted-foreground text-sm">Nota: {r.note}</p>}
              {r.shown.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">El agente mostró:</span>
                  {r.shown.slice(0, 5).map((k) => (
                    <code key={k} className="bg-muted rounded px-1.5 py-0.5">
                      {k}
                    </code>
                  ))}
                </div>
              )}
              {r.answer ? (
                <p className="text-sm">
                  <span className="text-muted-foreground">Respuesta de {r.answer.by}: </span>
                  {r.answer.asset_key ? <code className="font-medium">{r.answer.asset_key}</code> : "no existe en las fuentes catalogadas"}
                  {r.answer.note ? ` — ${r.answer.note}` : ""}
                </p>
              ) : (
                <Button size="sm" onClick={() => setAnswering(r)}>
                  Responder
                </Button>
              )}
            </CardContent>
          </Card>
        ))
      )}
      <AnswerDialog
        request={answering}
        onClose={() => setAnswering(null)}
        onDone={() => {
          setAnswering(null);
          load();
        }}
      />
    </div>
  );
}

function AnswerDialog({ request, onClose, onDone }: { request: CurationRequest | null; onClose: () => void; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<ObjectRow[]>([]);
  const [chosenTable, setChosenTable] = useState<string | null>(null);
  const [column, setColumn] = useState("");
  const [description, setDescription] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!request) return;
    setQ("");
    setResults([]);
    setChosenTable(request.shown[0] ? request.shown[0].split(".").slice(0, 3).join(".") : null);
    setColumn(request.shown[0]?.split(".").slice(3).join(".") ?? "");
    setDescription("");
    setNote("");
  }, [request]);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => api.objects({ q, limit: 8 }).then((d) => setResults(d.items)).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);

  const assetKey = chosenTable ? (column.trim() ? `${chosenTable}.${column.trim()}` : chosenTable) : null;

  async function submit(kind: "asset" | "no_source") {
    if (!request) return;
    setSaving(true);
    try {
      await api.answerRequest(request.id, {
        kind,
        asset_key: kind === "asset" ? assetKey ?? undefined : undefined,
        description: kind === "asset" && description.trim() ? description.trim() : undefined,
        note: note.trim() || undefined,
      });
      toast.success(kind === "asset" ? "Respuesta guardada: el agente la usará desde ya" : "Registrado como brecha de conocimiento");
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={!!request} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Responder la duda</DialogTitle>
          <DialogDescription>“{request?.question}”</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>¿Dónde está el dato?</Label>
            <div className="relative">
              <Search className="text-muted-foreground absolute top-2.5 left-3 size-4" />
              <Input className="pl-9" placeholder="Busca la tabla…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {results.length > 0 && (
              <div className="max-h-44 divide-y overflow-y-auto rounded-md border">
                {results.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setChosenTable(r.asset_key);
                      setQ("");
                    }}
                    className="hover:bg-accent flex w-full flex-col items-start px-3 py-2 text-left"
                  >
                    <span className="font-mono text-sm">{r.asset_key}</span>
                    {r.description && <span className="text-muted-foreground line-clamp-1 text-xs">{r.description}</span>}
                  </button>
                ))}
              </div>
            )}
            {chosenTable && (
              <div className="grid grid-cols-[1fr_auto_10rem] items-center gap-2">
                <code className="bg-accent text-accent-foreground truncate rounded-md px-2 py-1.5 text-sm">{chosenTable}</code>
                <span className="text-muted-foreground">.</span>
                <Input placeholder="columna (opcional)" value={column} onChange={(e) => setColumn(e.target.value)} />
              </div>
            )}
          </div>
          <div className="space-y-2">
            <Label>Descripción para todos (opcional)</Label>
            <Textarea
              rows={3}
              placeholder="Qué significa este dato, en palabras del negocio"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <p className="text-muted-foreground text-xs">Queda como “Revisada por un responsable” y un refresco del catálogo no la sobrescribe.</p>
          </div>
          <div className="space-y-2">
            <Label>Nota para quien preguntó (opcional)</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" onClick={() => submit("no_source")} disabled={saving}>
            <SearchX /> No está en las fuentes
          </Button>
          <Button onClick={() => submit("asset")} disabled={saving || !assetKey}>
            {saving && <Loader2 className="animate-spin" />} Guardar respuesta
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- Cola de documentación por demanda (F24 §Revisión del catálogo) ------------------------------------
function ReviewPanel() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("");

  const load = useCallback(() => {
    api
      .reviewQueue()
      .then((d) => setItems(d.items))
      .catch((e: Error) => {
        setItems([]);
        toast.error(e.message);
      });
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(
    () => (items ?? []).filter((i) => !filter || i.asset_key.toLowerCase().includes(filter.toLowerCase())),
    [items, filter],
  );
  const maxDemand = Math.max(1, ...(items ?? []).map((i) => i.demand));

  async function save(item: ReviewItem) {
    setSaving(true);
    try {
      await api.setDescription(item.asset_key, draft.trim());
      toast.success("Descripción guardada", { description: "Ya aparece como revisada en las respuestas." });
      setItems((prev) => (prev ?? []).filter((i) => i.asset_key !== item.asset_key));
      setEditing(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle>Lo más buscado sin documentar</CardTitle>
          <CardDescription>Ordenado por cuántas preguntas tocaron cada activo. Empieza por arriba: es donde más se ahorra.</CardDescription>
        </div>
        <Input className="w-56" placeholder="Filtrar…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </CardHeader>
      <CardContent className="space-y-2">
        {items === null ? (
          <Skeleton className="h-40 w-full" />
        ) : shown.length === 0 ? (
          <p className="text-muted-foreground py-8 text-center text-sm">Nada pendiente por documentar.</p>
        ) : (
          shown.map((item) => (
            <div key={item.asset_key} className={cn("rounded-lg border p-3", editing === item.asset_key && "border-primary/40 bg-accent/30")}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-medium">
                  {item.table}
                  {item.column && <span className="text-primary">.{item.column}</span>}
                </span>
                <span className="text-muted-foreground text-xs">
                  {item.database}
                  {item.data_type ? ` · ${item.data_type}` : ""}
                </span>
                <span className="text-muted-foreground ml-auto flex items-center gap-1.5 text-xs" title="Preguntas que lo mostraron">
                  <Flame className="text-conf-low size-3.5" />
                  <span className="bg-muted inline-block h-1.5 w-16 overflow-hidden rounded-full">
                    <span className="bg-conf-low block h-full rounded-full" style={{ width: `${(item.demand / maxDemand) * 100}%` }} />
                  </span>
                  {item.demand}
                </span>
              </div>
              {editing === item.asset_key ? (
                <div className="mt-2 space-y-2">
                  <Textarea rows={2} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                      Cancelar
                    </Button>
                    <Button size="sm" disabled={saving || draft.trim().length < 3} onClick={() => save(item)}>
                      {saving && <Loader2 className="animate-spin" />} Guardar como revisada
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <p className="text-muted-foreground flex-1 text-sm">{item.description ?? "Sin descripción."}</p>
                  <SourceBadge source={item.description_source} />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditing(item.asset_key);
                      setDraft(item.description ?? "");
                    }}
                  >
                    {item.description ? <Sparkles /> : <PenLine />} {item.description ? "Revisar" : "Documentar"}
                  </Button>
                </div>
              )}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}



// --- Reglas de negocio vinculadas a activos (HU-28, F23 CA4) --------------------------------------------
function RulesPanel() {
  const [rules, setRules] = useState<ManagedRule[] | null>(null);
  const [id, setId] = useState("");
  const [text, setText] = useState("");
  const [asset, setAsset] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api
      .rules()
      .then((d) => setRules(d.items))
      .catch((e: Error) => {
        setRules([]);
        toast.error(e.message);
      });
  }, []);
  useEffect(load, [load]);

  async function save() {
    setSaving(true);
    try {
      await api.saveRule({ id: id.trim(), text: text.trim(), applies_to: [asset.trim()] });
      toast.success("Regla guardada", { description: "Aparece como revisada junto al dato en las respuestas." });
      setId("");
      setText("");
      setAsset("");
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  async function remove(rule: ManagedRule) {
    try {
      await api.deleteRule(rule.id);
      toast.success(`Regla ${rule.id} eliminada`);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo eliminar");
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader>
          <CardTitle>Reglas vinculadas a activos</CardTitle>
          <CardDescription>Cada regla se muestra junto al dato correcto, con su fuente, solo a quien puede ver ese activo.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {rules === null && <Skeleton className="h-16 w-full" />}
          {rules?.length === 0 && <p className="text-muted-foreground py-6 text-center text-sm">Aún no hay reglas registradas.</p>}
          {rules?.map((r) => (
            <div key={r.id} className="flex items-start justify-between gap-3 rounded-lg border p-3">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{r.id}</Badge>
                  {r.reviewed && <Badge variant="outline">Revisada</Badge>}
                  {r.source && <span className="text-muted-foreground text-xs">{r.source}</span>}
                </div>
                <p className="text-sm">{r.text}</p>
                <p className="text-muted-foreground truncate font-mono text-xs">{r.applies_to.join(" · ")}</p>
              </div>
              <Button variant="ghost" size="icon" aria-label={`Eliminar ${r.id}`} onClick={() => remove(r)}>
                <Trash2 />
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Nueva regla</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="rule-id">Identificador</Label>
            <Input id="rule-id" value={id} onChange={(e) => setId(e.target.value)} placeholder="BR-PRE-001" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-asset">Activo (BD.esquema.tabla[.columna])</Label>
            <Input id="rule-asset" value={asset} onChange={(e) => setAsset(e.target.value)} placeholder="BancaPrestamos.dbo.Prestamos.CategoriaRiesgo" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-text">Regla</Label>
            <Textarea id="rule-text" value={text} onChange={(e) => setText(e.target.value)} rows={4} placeholder="Qué regla aplica a este dato, en palabras del negocio" />
          </div>
          <Button className="w-full" disabled={saving || !id.trim() || !asset.trim() || text.trim().length < 5} onClick={save}>
            {saving ? <Loader2 className="animate-spin" /> : <Plus />} Guardar regla
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
