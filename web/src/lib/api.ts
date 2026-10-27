import type {
  AnswerEnvelope,
  AuditRow,
  BuildJob,
  CurationRequest,
  DatabaseSummary,
  Metrics,
  ManagedRule,
  MyRequest,
  ReviewItem,
  ObjectDetail,
  ObjectRow,
  ServerConfig,
  SetupStatus,
  User,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
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
    let message = `Error ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {}
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
  feedback: (trace_id: string, asset_key: string, verdict: "confirm" | "reject", comment?: string) =>
    request<{ confirmations: number; rejections: number }>("/discover/feedback", {
      method: "POST",
      json: { trace_id, asset_key, verdict, comment },
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
      let message = `Error ${res.status}`;
      try {
        const data = await res.json();
        if (typeof data.detail === "string") message = data.detail;
      } catch {}
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
    request<{ ok: boolean }>(`/curation/requests/${id}/answer`, { method: "POST", json: body }),
  reviewQueue: (domain?: string) =>
    request<{ items: ReviewItem[] }>(`/curation/review?limit=100${domain ? `&domain=${encodeURIComponent(domain)}` : ""}`),
  setDescription: (asset_key: string, description: string, synonyms?: string[]) =>
    request<{ ok: boolean; copies: number }>("/curation/description", { method: "PUT", json: { asset_key, description, synonyms } }),
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
  startBuild: (enrich: boolean) => request<BuildJob>("/admin/catalog/build", { method: "POST", json: { enrich } }),
  buildStatus: () => request<BuildJob>("/admin/catalog/build"),
  audit: (kind?: string) => request<{ items: AuditRow[] }>(`/admin/audit?limit=200${kind ? `&kind=${kind}` : ""}`),
};
