// Contrato de ConverData-API. AnswerEnvelope y Discovery reflejan src/converdata/models/discovery.py (PRD §8.3, F22).

export type DescriptionSource = "human" | "data_dictionary" | "ms_description" | "document" | "generated";

export interface Location {
  environment: string;
  server: string;
}

export interface RuleRef {
  id: string;
  text: string;
  reviewed: boolean;
}

export interface Candidate {
  rank: number;
  kind: "column" | "table" | "view" | "procedure";
  asset_key: string;
  database: string;
  schema: string;
  table: string;
  column: string | null;
  data_type: string | null;
  locations: Location[];
  drift_warning: string | null;
  description: string | null;
  description_source: DescriptionSource;
  business_rules: RuleRef[];
  owners: { business: string | null; technical: string | null };
  lineage: { upstream: string[]; downstream: string[] };
  evidence: { kind: string; source: string; reviewed: boolean | null }[];
  why: string;
  confidence: number;
  copies: string[];
}

export interface Alternative {
  asset_key: string;
  why: string;
  confidence: number;
}

export interface Related {
  from: string;
  to: string;
  relation: "fk" | "etl" | "same_entity";
  on: string | null;
  via: string | null;
}

export interface JoinPath {
  purpose: string;
  tables: string[];
  steps: string[];
}

export interface Discovery {
  candidates: Candidate[];
  alternatives: Alternative[];
  related: Related[];
  join_paths: JoinPath[];
  knowledge_gap: boolean;
  suggested_questions: string[];
}

export interface AnswerEnvelope {
  trace_id: string;
  flow: "discover" | "ask";
  status: "ok" | "needs_clarification" | "rejected" | "error";
  answer_text: string;
  clarification: { question: string; options: string[] } | null;
  databases: string[];
  tables_used: string[];
  assumptions: string[];
  validation: { checks: { name: string; status: string; detail: string }[]; attempts: number } | null;
  confidence: number | null;
  discovery: Discovery | null;
  timings_ms: Record<string, number>;
}

export interface SetupStatus {
  has_inventory: boolean;
  servers: { id: string; alias: string; environment: string }[];
  has_catalog: boolean;
  load_error: string | null;
  catalog: { objects: number; columns: number; databases: number };
  build: { status: BuildStatus; finished_at: string | null };
  llm: boolean;
  demo: boolean;
  windows_auth: boolean;
}

export interface User {
  user_id: string;
  roles: string[]; // consumer | steward | data_admin (F24)
  domains: string[] | null; // dominios que puede curar; ["*"] = todos
  servers: { id: string; alias: string }[];
}

export type BuildStatus = "idle" | "running" | "ok" | "error";

export interface BuildJob {
  status: BuildStatus;
  started_at: string | null;
  finished_at: string | null;
  triggered_by: string | null;
  enrich: boolean;
  report: {
    servers_ok: string[];
    servers_failed: Record<string, string>;
    databases: string[];
    objects: number;
    columns: number;
    reused: number;
    enriched: number;
    entities: string[];
    lineage_edges: number;
    files_written: number;
    seconds: number;
  } | null;
  summary: string | null;
  error: string | null;
}

export interface DatabaseSummary {
  database: string;
  server: string;
  server_alias: string;
  environment: string;
  domain: string | null;
  tables: number;
  views: number;
  procedures: number;
  columns: number;
}

export interface ObjectRow {
  id: string;
  asset_key: string;
  kind: "table" | "view" | "procedure";
  database: string;
  schema: string;
  name: string;
  environment: string;
  server_alias: string;
  description: string | null;
  description_source: DescriptionSource;
  row_count: number | null;
  columns: number;
  pii_columns: number;
}

export interface CatalogColumn {
  name: string;
  type: string;
  nullable?: boolean;
  description?: string | null;
  description_source?: DescriptionSource;
  synonyms?: string[];
  pii?: boolean;
}

export interface ObjectDetail {
  id: string;
  asset_key: string;
  environment: string;
  server: string;
  server_alias: string;
  kind: "table" | "view" | "procedure";
  database: string;
  schema: string;
  name: string;
  description: string | null;
  description_source: DescriptionSource;
  domain: string | null;
  synonyms: string[];
  row_count: number | null;
  primary_key: string[];
  columns: CatalogColumn[];
  foreign_keys: { columns: string[]; ref: string; ref_columns: string[] }[];
  parameters: { name: string; type: string; direction: string }[];
  business_rules: RuleRef[];
  owners: { business: string | null; technical: string | null };
  referenced_by: string[];
  copies: { id: string; environment: string; server_alias: string }[];
}

export interface ServerConfig {
  id: string;
  host: string;
  alias: string;
  environment: string;
  is_reference: boolean;
  databases: string[];
  trust_server_certificate: boolean;
  connected?: boolean;
}

export interface AuditRow {
  ts: string;
  type: string;
  user_id: string | null;
  trace_id?: string;
  question?: string;
  status?: string;
  confidence?: number | null;
  duration_ms?: number;
  [key: string]: unknown;
}

// --- Curación (F24) y métricas (F25) -----------------------------------------------------------------
export type RequestStatus = "open" | "answered" | "no_source";

export interface MyRequest {
  id: string;
  created_at: string;
  status: RequestStatus;
  question: string;
  domain: string;
  answer: { kind: "asset" | "no_source"; at: string; note: string | null; asset_key: string | null; needs_access: boolean } | null;
}

export interface CurationRequest {
  id: string;
  created_at: string;
  status: RequestStatus;
  user_id: string;
  question: string;
  domain: string;
  shown: string[];
  note: string | null;
  answer: { by: string; at: string; kind: "asset" | "no_source"; asset_key: string | null; note: string | null } | null;
}

export interface ReviewItem {
  asset_key: string;
  kind: "table" | "column";
  database: string;
  table: string;
  column: string | null;
  data_type: string | null;
  description: string | null;
  description_source: DescriptionSource;
  domain: string | null;
  demand: number;
}

export interface Metrics {
  days: number;
  questions: number;
  active_users: number;
  confirmed_rate: number | null;
  rejections: number;
  escalations: number;
  resolved_without_escalation: number | null;
  gap_rate: number | null;
  time_to_confirm_s: { p50: number | null; p95: number | null };
  latency_ms: { p50: number | null; p95: number | null };
  status: Record<string, number>;
  per_day: { day: string; questions: number; users: number; confirmed: number }[];
  top_databases: [string, number][];
  requests_open: number;
}

export interface ManagedRule {
  id: string;
  text: string;
  domain?: string | null;
  applies_to: string[];
  source?: string | null;
  owner?: string | null;
  reviewed: boolean;
}
