import type { DescriptionSource } from "@/lib/types";

export const ENV_LABEL: Record<string, string> = {
  produccion: "Producción",
  qa: "QA",
  desarrollo: "Desarrollo",
  dr: "DR",
};

export const SOURCE_LABEL: Record<DescriptionSource, string> = {
  human: "Revisada por un responsable",
  data_dictionary: "Diccionario de datos",
  ms_description: "MS_Description",
  document: "Documento",
  generated: "Sugerida por IA, sin revisar",
};

export const KIND_LABEL: Record<string, string> = {
  column: "Columna",
  table: "Tabla",
  view: "Vista",
  procedure: "Procedimiento",
};

export const RELATION_LABEL: Record<string, string> = {
  fk: "Llave foránea",
  etl: "ETL",
  same_entity: "Misma entidad",
};

// Los pasos del DiscoverFlow (STEP_LABELS en flows/discover.py), mostrados mientras se espera la respuesta.
export const FLOW_STEPS = [
  "Interpretando la pregunta",
  "Buscando en catálogo, diccionarios, documentos y ETL",
  "Calificando lo encontrado",
  "Priorizando candidatos",
  "Agregando ubicaciones, reglas, relaciones y responsables",
  "Revisando el resultado",
  "Redactando la respuesta",
];

export type ConfidenceLevel = "high" | "mid" | "low";

export function confidenceLevel(value: number): ConfidenceLevel {
  if (value >= 0.8) return "high";
  if (value >= 0.6) return "mid";
  return "low";
}

export const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  high: "Confianza alta",
  mid: "Confianza media",
  low: "Confianza baja",
};

export function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)} %`;
}

export function shortName(assetKey: string): string {
  const parts = assetKey.split(".");
  return parts.length > 3 ? parts.slice(3).join(".") : parts[parts.length - 1];
}

export function tableOf(assetKey: string): string {
  return assetKey.split(".").slice(0, 3).join(".");
}

export function number(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("es-SV");
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-SV", { dateStyle: "medium", timeStyle: "short" });
}

export function relativeTime(ts: number): string {
  const diff = (Date.now() - ts) / 1000;
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return new Date(ts).toLocaleDateString("es-SV", { day: "numeric", month: "short" });
}
