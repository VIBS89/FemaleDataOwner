"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Clock, Database, FlaskConical, MessageSquare, ThumbsUp, Timer, UserRoundSearch, Users, Zap } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { useSession } from "@/components/session-provider";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { number, pct } from "@/lib/format";
import type { Metrics } from "@/lib/types";

// Scorecard de F25 calculado desde la auditoría (sin leer SQL ni datos). Solo data_admin.
export default function MetricsPage() {
  const { isAdmin, status } = useSession();
  const router = useRouter();
  const [days, setDays] = useState("30");
  const [m, setM] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) router.replace("/");
  }, [isAdmin, router]);

  useEffect(() => {
    if (!isAdmin) return;
    setM(null);
    setError(null);
    api.metrics(Number(days)).then(setM).catch((e: Error) => setError(e.message));
  }, [days, isAdmin]);

  if (!isAdmin) return null;

  return (
    <div className="flex min-h-svh flex-col">
      <PageHeader title="Métricas">
        <Tabs value={days} onValueChange={setDays}>
          <TabsList>
            <TabsTrigger value="7">7 días</TabsTrigger>
            <TabsTrigger value="30">30 días</TabsTrigger>
            <TabsTrigger value="90">90 días</TabsTrigger>
          </TabsList>
        </Tabs>
      </PageHeader>
      <div className="mx-auto w-full max-w-6xl space-y-6 p-4 sm:p-6">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">El valor del agente, medido</h2>
          <p className="text-muted-foreground text-sm">
            Adopción, calidad percibida y conocimiento capturado, calculados desde la auditoría para comparar contra la línea base del piloto.
          </p>
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
        {status?.demo && (
          <p className="bg-conf-mid-bg text-conf-mid flex items-center gap-2 rounded-lg px-3 py-2 text-xs">
            <FlaskConical className="size-3.5 shrink-0" /> Modo demo: las cifras pueden incluir actividad simulada para ilustrar el tablero; no son
            resultados de un piloto.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Kpi icon={MessageSquare} label="Preguntas respondidas" value={m && number(m.questions)} />
          <Kpi icon={Users} label="Usuarios activos" value={m && number(m.active_users)} />
          <Kpi
            icon={ThumbsUp}
            label="Confirmadas con “Es este”"
            value={m && pct(m.confirmed_rate)}
            hint="Respuestas en las que la persona confirmó el dato correcto"
          />
          <Kpi
            icon={Zap}
            label="Resueltas sin escalar"
            value={m && pct(m.resolved_without_escalation)}
            hint="Preguntas que no necesitaron a un experto (meta: −30 % de consultas a expertos)"
          />
          <Kpi
            icon={Timer}
            label="Tiempo hasta encontrar el dato"
            value={m && seconds(m.time_to_confirm_s.p50)}
            hint="Mediana desde la pregunta hasta “Es este” (meta: −50 % del tiempo de localización)"
          />
          <Kpi icon={Clock} label="Latencia del agente (p95)" value={m && ms(m.latency_ms.p95)} hint={m ? `p50 ${ms(m.latency_ms.p50)}` : undefined} />
          <Kpi icon={UserRoundSearch} label="Dudas escaladas" value={m && number(m.escalations)} hint={m ? `${m.requests_open} pendientes` : undefined} />
          <Kpi
            icon={Database}
            label="Brechas de conocimiento"
            value={m && pct(m.gap_rate)}
            hint="Respuestas con confianza < 60 %: dónde documentar primero"
          />
        </div>

        <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
          <Card>
            <CardHeader>
              <CardTitle>Preguntas por día</CardTitle>
              <CardDescription>Pasa el cursor sobre una barra para ver usuarios y confirmaciones.</CardDescription>
            </CardHeader>
            <CardContent>{m ? <DailyBars data={m.per_day} days={m.days} /> : <Skeleton className="h-48 w-full" />}</CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Bases más consultadas</CardTitle>
              <CardDescription>Dónde vive el conocimiento que más se busca.</CardDescription>
            </CardHeader>
            <CardContent>
              {!m ? (
                <Skeleton className="h-48 w-full" />
              ) : m.top_databases.length === 0 ? (
                <p className="text-muted-foreground text-sm">Aún sin datos.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Base de datos</TableHead>
                      <TableHead className="text-right">Preguntas</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {m.top_databases.map(([db, n]) => (
                      <TableRow key={db}>
                        <TableCell className="font-mono text-xs">{db}</TableCell>
                        <TableCell className="text-right tabular-nums">{n}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function seconds(v: number | null) {
  if (v == null) return "—";
  return v < 90 ? `${Math.round(v)} s` : `${(v / 60).toFixed(1)} min`;
}

function ms(v: number | null) {
  if (v == null) return "—";
  return v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`;
}

function Kpi({ icon: Icon, label, value, hint }: { icon: React.ElementType; label: string; value: string | null; hint?: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="space-y-1.5 px-4">
        <div className="text-muted-foreground flex items-center gap-2 text-xs">
          <Icon className="size-3.5" /> {label}
        </div>
        {value === null ? <Skeleton className="h-8 w-20" /> : <p className="text-2xl font-semibold tracking-tight tabular-nums">{value}</p>}
        {hint && <p className="text-muted-foreground text-[11px] leading-snug">{hint}</p>}
      </CardContent>
    </Card>
  );
}

// Una sola serie (preguntas/día): un color, sin leyenda; barras finas con 2 px de separación y extremo redondeado.
function DailyBars({ data: raw, days }: { data: Metrics["per_day"]; days: number }) {
  if (raw.length === 0) return <p className="text-muted-foreground py-16 text-center text-sm">Aún no hay preguntas en este periodo.</p>;
  // Todos los días del periodo, con cero donde no hubo preguntas: se lee como serie de tiempo.
  const byDay = new Map(raw.map((d) => [d.day, d]));
  const data = Array.from({ length: days }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (days - 1 - i));
    const day = date.toLocaleDateString("en-CA");
    return byDay.get(day) ?? { day, questions: 0, users: 0, confirmed: 0 };
  });
  const max = Math.max(1, ...data.map((d) => d.questions));
  return (
    <div>
      <div className="flex h-48 items-end gap-[2px] border-b">
        {data.map((d) => (
          <Tooltip key={d.day}>
            <TooltipTrigger asChild>
              <div className="group flex h-full min-w-1 flex-1 cursor-default items-end">
                <div
                  className="bg-primary group-hover:bg-primary/80 w-full rounded-t-[4px] transition-colors"
                  style={{ height: d.questions ? `${Math.max(2, (d.questions / max) * 100)}%` : 0 }}
                />
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p className="font-medium">{new Date(`${d.day}T12:00:00`).toLocaleDateString("es-SV", { weekday: "short", day: "numeric", month: "short" })}</p>
              <p>
                {d.questions} preguntas · {d.users} usuarios · {d.confirmed} confirmadas
              </p>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
      <div className="text-muted-foreground mt-1.5 flex justify-between text-[11px]">
        <span>{data[0].day}</span>
        <span>máx. {max}</span>
        <span>{data[data.length - 1].day}</span>
      </div>
    </div>
  );
}
