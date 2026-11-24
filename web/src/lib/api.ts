import type {
  AnswerEnvelope,
  AuditRow,
  BuildJob,
  ConnectBody,
  ConnectResult,
  CurationRequest,
  DictionaryReport,
  DatabaseSummary,
  Metrics,
  ManagedRule,
  MyRequest,
  ReviewItem,
  ObjectDetail,
  ObjectRow,
  ProbeResult,
  ServerConfig,
  SetupStatus,
  User,
  DescriptionHistory,
  DocsDiagram,
  DocsIndex,
  DocsPage,
  Steward,
  LlmSettings,
} from "@/lib/types";

/** Texto del error de la API: `detail` como cadena, o los mensajes de validación (422) sin el prefijo de Pydantic. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join("; ");
    }
  } catch {}
  return `Error ${res.status}`;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`/api${path}`, {
    ...rest,
    headers: json !== undefined ? { "content-type": "application/json", ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) {
    const message = await errorMessage(res);
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("converdata:unauthorized"));
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export interface LoginBody {
  login?: string;
  password?: string;
  auth: "sql" | "windows";
  servers?: string[] | null;
  host?: string;
  alias?: string;
  environment?: string;
  trust_server_certificate?: boolean;
  setup_token?: string;
}

export const api = {
  status: () => request<SetupStatus>("/setup/status"),
  me: () => request<User>("/auth/me"),
  login: (body: LoginBody) =>
    request<{
      user: User;
      warnings: Record<string, string>;
      servers: { alias: string; ok: boolean }[];
      databases: string[];
    }>("/login", { method: "POST", json: body }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  discover: (question: string, history: string[]) =>
    request<AnswerEnvelope>("/discover", { method: "POST", json: { question, history } }),
  feedback: (trace_id: string, asset_key: string, verdict: "confirm" | "reject") =>
    request<{ golden_id: string; confirmations: number; rejections: number; learned: boolean }>("/discover/feedback", {
      method: "POST",
      json: { trace_id, asset_key, verdict },
    }),
  history: () =>
    request<{ items: { ts: string; trace_id: string; question: string; status: string; confidence: number | null }[] }>(
      "/me/history",
    ),

  databases: () => request<DatabaseSummary[]>("/catalog/databases"),
  objects: (params: { database?: string; q?: string; kind?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<{ total: number; items: ObjectRow[] }>(`/catalog/objects?${qs}`);
  },
  object: (id: string) => request<ObjectDetail>(`/catalog/object?id=${encodeURIComponent(id)}`),
  asset: (assetKey: string) => request<ObjectDetail>(`/assets/${assetKey.split(".").map(encodeURIComponent).join(".")}`),

  // Respuesta por SSE: un evento `step` por nodo del DiscoverFlow y al final `answer` (F12, OP-04 CA8).
  discoverStream: async (
    question: string,
    history: string[],
    onStep: (step: { node: string; label: string }) => void,
  ): Promise<AnswerEnvelope> => {
    const res = await fetch("/api/discover/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, history }),
      credentials: "same-origin",
    });
    if (!res.ok || !res.body) {
      const message = await errorMessage(res);
      if (res.status === 401) window.dispatchEvent(new Event("converdata:unauthorized"));
      throw new ApiError(res.status, message);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer: AnswerEnvelope | null = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const event = /^event: (.*)$/m.exec(block)?.[1];
        const data = /^data: (.*)$/m.exec(block)?.[1];
        if (!event || !data) continue;
        if (event === "step") onStep(JSON.parse(data));
        else if (event === "answer") answer = JSON.parse(data);
      }
    }
    if (!answer) throw new ApiError(502, "La respuesta se interrumpió; inténtalo de nuevo");
    return answer;
  },
  escalate: (trace_id: string, note?: string) =>
    request<{ id: string; domain: string; status: string }>("/curation/requests", { method: "POST", json: { trace_id, note } }),
  myRequests: () => request<{ items: MyRequest[] }>("/me/requests"),

  curationRequests: (status: "open" | "answered" | "all" = "open") =>
    request<{ items: CurationRequest[] }>(`/curation/requests?status=${status}`),
  answerRequest: (id: string, body: { kind: "asset" | "no_source"; asset_key?: string; description?: string; note?: string }) =>
    request<{ ok: boolean; request: CurationRequest }>(`/curation/requests/${id}/answer`, { method: "POST", json: body }),
  reviewQueue: (domain?: string) =>
    request<{ items: ReviewItem[] }>(`/curation/review?limit=100${domain ? `&domain=${encodeURIComponent(domain)}` : ""}`),
  setDescription: (asset_key: string, description: string, synonyms?: string[]) =>
    request<{ ok: boolean; copies: number }>("/curation/description", {
      method: "PUT",
      json: { asset_key, description, synonyms },
    }),
  descriptionHistory: (asset_key: string) =>
    request<DescriptionHistory>(`/curation/history?asset_key=${encodeURIComponent(asset_key)}`),
  uploadDictionary: (csv: string) => request<DictionaryReport>("/curation/dictionary", { method: "POST", json: { csv } }),
  rules: () => request<{ items: ManagedRule[] }>("/curation/rules"),
  saveRule: (rule: { id: string; text: string; applies_to: string[]; domain?: string }) =>
    request<{ ok: boolean; rule: ManagedRule }>("/curation/rules", { method: "PUT", json: rule }),
  deleteRule: (id: string) => request<{ ok: boolean }>(`/curation/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  metrics: (days: number) => request<Metrics>(`/admin/metrics?days=${days}`),

  inventory: () => request<{ servers: ServerConfig[] }>("/admin/inventory"),
  saveInventory: (servers: ServerConfig[]) =>
    request<{ ok: boolean; connections: Record<string, string> }>("/admin/inventory", {
      method: "PUT",
      json: { servers },
    }),
  probeServer: (body: { host: string; trust_server_certificate: boolean } | { server_id: string }) =>
    request<ProbeResult>("/admin/inventory/probe", { method: "POST", json: body }),
  connectServer: (body: ConnectBody) => request<ConnectResult>("/admin/inventory/connect", { method: "POST", json: body }),
  stewards: () => request<{ stewards: Steward[]; domains: string[] }>("/admin/stewards"),
  saveStewards: (stewards: Steward[]) =>
    request<{ ok: boolean; stewards: Steward[] }>("/admin/stewards", { method: "PUT", json: { stewards } }),
  llmProfiles: () => request<LlmSettings>("/admin/llm"),
  setLlmProfile: (profile: string) => request<LlmSettings>("/admin/llm", { method: "PUT", json: { profile } }),
  startBuild: (enrich: boolean) => request<BuildJob>("/admin/catalog/build", { method: "POST", json: { enrich } }),
  buildStatus: () => request<BuildJob>("/admin/catalog/build"),
  audit: (kind?: string) => request<{ items: AuditRow[] }>(`/admin/audit?limit=200${kind ? `&kind=${kind}` : ""}`),
  // Documentación interna (solo data_admin): cada página o diagrama que se abre queda en la auditoría.
  docsIndex: () => request<DocsIndex>("/admin/docs"),
  docsPage: (path: string) => request<DocsPage>(`/admin/docs/page?path=${encodeURIComponent(path)}`),
  // El HTML del diagrama llega como texto en JSON; la web lo pinta en un iframe con `sandbox` (docs-viewer.tsx).
  docsDiagram: (path: string) => request<DocsDiagram>(`/admin/docs/diagram?path=${encodeURIComponent(path)}`),
};
