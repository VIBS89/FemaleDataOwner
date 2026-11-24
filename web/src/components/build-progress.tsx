"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import type { BuildJob } from "@/lib/types";

// Pasos del CatalogBuildFlow que se muestran mientras corre (la API solo informa "running"; el avance es orientativo).
export const BUILD_STEPS = [
  { key: "extract", label: "Leer metadatos", hint: "Objetos, columnas, llaves, descripciones y dependencias de sys.*" },
  { key: "enrich", label: "Enriquecer", hint: "Descripciones y sinónimos sugeridos por IA (opcional)" },
  { key: "relate", label: "Relacionar", hint: "Entidades entre BDs y linaje de vistas" },
  { key: "write", label: "Escribir catálogo", hint: "Formato F1, listo para el agente" },
];

/** Sigue el estado de `GET /admin/catalog/build` cada 1,2 s mientras corre y avisa una vez al terminar. */
export function useBuildJob(onFinish?: (job: BuildJob) => void | Promise<void>) {
  const [job, setJob] = useState<BuildJob | null>(null);
  const [tick, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const finish = useRef(onFinish);
  useEffect(() => {
    finish.current = onFinish;
  });

  const poll = useCallback(async () => {
    const j = await api.buildStatus();
    setJob(j);
    if (j.status !== "running" && timer.current) {
      clearInterval(timer.current);
      timer.current = null;
      await finish.current?.(j);
    }
    return j;
  }, []);

  /** Empieza a seguir un trabajo recién lanzado (o lo da por terminado si ya acabó). */
  const follow = useCallback(
    (j: BuildJob) => {
      setJob(j);
      if (j.status !== "running") {
        void finish.current?.(j);
        return;
      }
      setTick(0);
      if (!timer.current) timer.current = setInterval(() => void poll().catch(() => undefined), 1200);
    },
    [poll],
  );

  useEffect(
    () => () => {
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );

  useEffect(() => {
    if (job?.status !== "running") return;
    const t = setInterval(() => setTick((x) => x + 1), 900);
    return () => clearInterval(t);
  }, [job?.status]);

  return { job, tick, poll, follow };
}

/** Lista de pasos con el actual animado; `enrich` indica si el paso de IA corre (o correría). */
export function BuildSteps({ job, tick, enrich }: { job: BuildJob | null; tick: number; enrich: boolean }) {
  const running = job?.status === "running";
  const activeStep = Math.min(Math.floor(tick / 2), BUILD_STEPS.length - 1);
  return (
    <ol className="space-y-3">
      {BUILD_STEPS.map((s, i) => {
        const done = job?.status === "ok" || (running && i < activeStep);
        const now = running && i === activeStep;
        const skipped = s.key === "enrich" && (running ? !job?.enrich : !enrich);
        return (
          <li key={s.key} className="flex items-start gap-3" aria-current={now ? "step" : undefined}>
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
  );
}
