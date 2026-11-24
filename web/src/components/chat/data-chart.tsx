"use client";

import { useState } from "react";

import type { ChartSpec, DataAnswer } from "@/lib/types";

/**
 * Gráficos de barras y de pastel para la respuesta con datos (fase 1b). SVG a mano, sin dependencias.
 *
 * Reglas (skill dataviz): una sola escala; color por categoría en orden fijo (`--viz-1…6`), nunca ciclado: a partir
 * de la 7.ª porción se agrupa en "Otros"; marcas finas con extremo redondeado de 4 px y 2 px de separación; rejilla
 * recesiva; textos en tinta de texto, nunca del color de la serie; tooltip al pasar el mouse; la tabla sigue
 * disponible con el mismo botón.
 */

const PIE_MAX_SLICES = 6;
const SERIES = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)", "var(--viz-5)", "var(--viz-6)"];

type Cell = string | number | boolean | null;

export interface Point {
  label: string;
  value: number;
}

function isNumber(v: Cell): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function formatNumber(value: number): string {
  return value.toLocaleString("es-SV", { maximumFractionDigits: Math.abs(value) < 100 ? 2 : 0 });
}

function labelOf(v: Cell): string {
  if (v == null) return "Sin dato";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return new Date(`${v.slice(0, 10)}T00:00:00`).toLocaleDateString("es-SV");
  return String(v);
}

/** Columna del alias, sin distinguir mayúsculas. */
function col(data: DataAnswer, name: string): number {
  return data.columns.findIndex((c) => c.toLowerCase() === name.toLowerCase());
}

export function pointsOf(data: DataAnswer, spec: Pick<ChartSpec, "label_column" | "value_column">): Point[] {
  const l = col(data, spec.label_column);
  const v = col(data, spec.value_column);
  if (l < 0 || v < 0) return [];
  return data.rows.filter((r) => isNumber(r[v])).map((r) => ({ label: labelOf(r[l]), value: r[v] as number }));
}

/**
 * Si la IA no sugirió gráfico, el botón igual ofrece barras cuando los datos lo permiten: una columna de categorías y
 * una medida numérica en todas las filas, entre 2 y 30 filas. El pastel nunca se infiere (lo decide la IA).
 */
export function inferChart(data: DataAnswer): { bar?: ChartSpec } {
  const rows = data.rows;
  if (rows.length < 2 || rows.length > 30 || data.truncated) return {};
  const numeric = data.columns.map((_, i) => rows.every((r) => isNumber(r[i])));
  const label = data.columns.findIndex((_, i) => !numeric[i]);
  const value = numeric.findIndex((n, i) => n && i !== label);
  if (value < 0) return {};
  // Sin columna de texto, la primera columna (un año, un mes) hace de categoría si hay otra numérica.
  const labelIdx = label >= 0 ? label : value === 0 && numeric.length > 1 ? 0 : -1;
  const valueIdx = label >= 0 ? value : numeric.findIndex((n, i) => n && i !== 0);
  if (labelIdx < 0 || valueIdx < 0) return {};
  return { bar: { kind: "bar", label_column: data.columns[labelIdx], value_column: data.columns[valueIdx], title: "" } };
}

function niceStep(max: number): number {
  const raw = max / 4;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const norm = raw / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
}

/** `left`/`top` en % del contenedor del SVG: el gráfico escala con el ancho y el tooltip lo sigue. */
function Tooltip({ point, extra, left, top }: { point: Point; extra?: string; left: number; top: number }) {
  return (
    <div
      role="tooltip"
      className="bg-popover text-popover-foreground pointer-events-none absolute z-10 rounded-md border px-2.5 py-1.5 text-xs shadow-md"
      style={{ left: `${left}%`, top: `${top}%`, transform: "translate(-50%, calc(-100% - 8px))" }}
    >
      <div className="font-medium">{point.label}</div>
      <div className="text-muted-foreground tabular-nums">
        {formatNumber(point.value)}
        {extra ? ` · ${extra}` : ""}
      </div>
    </div>
  );
}

// --- barras horizontales: comparan una medida entre categorías y se leen con etiquetas largas -----------------
export function BarChart({ points, valueLabel }: { points: Point[]; valueLabel: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const labelW = 170;
  const barH = 18;
  const gap = 10;
  const top = 8;
  const axisH = 22;
  const plotW = width - labelW - 56;
  const max = Math.max(...points.map((p) => p.value), 0);
  const min = Math.min(...points.map((p) => p.value), 0);
  const step = niceStep(Math.max(max - min, 1));
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step || step;
  const x = (v: number) => labelW + ((v - lo) / (hi - lo)) * plotW;
  const height = top + points.length * (barH + gap) + axisH;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(t);
  const maxIdx = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={`Gráfico de barras: ${valueLabel}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top - 4} y2={height - axisH} className="stroke-border" strokeWidth={1} />
            <text x={x(t)} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[11px] tabular-nums">
              {formatNumber(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          const y = top + i * (barH + gap);
          const x0 = x(Math.min(0, p.value));
          const w = Math.max(Math.abs(x(p.value) - x(0)), 1);
          const r = Math.min(4, w / 2);
          // Extremo de datos redondeado; el lado del cero queda recto, anclado a la base.
          const d =
            p.value >= 0
              ? `M${x0},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${barH - 2 * r}a${r},${r} 0 0 1 -${r},${r}h-${w - r}z`
              : `M${x0 + w},${y}h-${w - r}a${r},${r} 0 0 0 -${r},${r}v${barH - 2 * r}a${r},${r} 0 0 0 ${r},${r}h${w - r}z`;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* Zona de hover más grande que la barra */}
              <rect x={0} y={y - gap / 2} width={width} height={barH + gap} fill="transparent" />
              <text x={labelW - 8} y={y + barH / 2} dominantBaseline="middle" textAnchor="end" className="fill-foreground text-[12px]">
                {p.label.length > 24 ? `${p.label.slice(0, 23)}…` : p.label}
                <title>{p.label}</title>
              </text>
              <path d={d} fill="var(--viz-1)" opacity={hover === null || hover === i ? 1 : 0.55} />
              {(i === maxIdx || hover === i) && (
                <text
                  x={x(p.value) + (p.value >= 0 ? 6 : -6)}
                  y={y + barH / 2}
                  dominantBaseline="middle"
                  textAnchor={p.value >= 0 ? "start" : "end"}
                  className="fill-foreground text-[11px] font-medium tabular-nums"
                >
                  {formatNumber(p.value)}
                </text>
              )}
            </g>
          );
        })}
        <line x1={x(0)} x2={x(0)} y1={top - 4} y2={height - axisH} className="stroke-muted-foreground" strokeWidth={1} />
      </svg>
      {hover !== null && (
        <Tooltip
          point={points[hover]}
          left={(x(points[hover].value) / width) * 100}
          top={((top + hover * (barH + gap)) / height) * 100}
        />
      )}
    </div>
  );
}

// --- pastel: reparto de un total, hasta 6 porciones y el resto en "Otros" --------------------------------------
export function foldSlices(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => b.value - a.value);
  if (sorted.length <= PIE_MAX_SLICES) return sorted;
  const head = sorted.slice(0, PIE_MAX_SLICES - 1);
  const rest = sorted.slice(PIE_MAX_SLICES - 1).reduce((s, p) => s + p.value, 0);
  return [...head, { label: "Otros", value: rest }];
}

export function PieChart({ points }: { points: Point[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const slices = foldSlices(points.filter((p) => p.value > 0));
  const total = slices.reduce((s, p) => s + p.value, 0);
  const size = 220;
  const c = size / 2;
  const r = c - 6;
  const pct = (v: number) => `${((v / total) * 100).toLocaleString("es-SV", { maximumFractionDigits: 1 })} %`;
  const color = (i: number) => (slices[i].label === "Otros" && i === PIE_MAX_SLICES - 1 ? "var(--viz-other)" : SERIES[i]);

  let angle = -Math.PI / 2;
  const arcs = slices.map((p, i) => {
    const a0 = angle;
    const a1 = angle + (p.value / total) * Math.PI * 2;
    angle = a1;
    const mid = (a0 + a1) / 2;
    if (slices.length === 1) return { d: "", mid, i };
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M${c},${c}L${c + r * Math.cos(a0)},${c + r * Math.sin(a0)}A${r},${r} 0 ${large} 1 ${c + r * Math.cos(a1)},${c + r * Math.sin(a1)}Z`;
    return { d, mid, i };
  });

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
      <div className="relative w-48 shrink-0 sm:w-52">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full" role="img" aria-label="Gráfico de pastel">
        {slices.length === 1 ? (
          <circle cx={c} cy={c} r={r} fill={color(0)} />
        ) : (
          arcs.map(({ d, i }) => (
            <path
              key={i}
              d={d}
              fill={color(i)}
              // 2 px del color de la tarjeta entre porciones: se distinguen sin depender solo del color.
              className="stroke-card"
              strokeWidth={2}
              strokeLinejoin="round"
              opacity={hover === null || hover === i ? 1 : 0.55}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          ))
        )}
      </svg>
      {hover !== null && slices.length > 1 && (
        <Tooltip
          point={slices[hover]}
          extra={pct(slices[hover].value)}
          left={((c + (r / 1.6) * Math.cos(arcs[hover].mid)) / size) * 100}
          top={((c + (r / 1.6) * Math.sin(arcs[hover].mid)) / size) * 100}
        />
      )}
      </div>
      <ul className="w-full min-w-0 space-y-1.5 text-sm">
        {slices.map((p, i) => (
          <li
            key={p.label}
            className={`flex items-center gap-2 rounded px-1.5 py-0.5 ${hover === i ? "bg-muted" : ""}`}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="size-3 shrink-0 rounded-sm" style={{ background: color(i) }} />
            <span className="min-w-0 flex-1 truncate" title={p.label}>
              {p.label}
            </span>
            <span className="text-muted-foreground tabular-nums">{formatNumber(p.value)}</span>
            <span className="w-14 text-right font-medium tabular-nums">{pct(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
