// Proxy hacia DiscoveryDataAgent-API: el navegador solo habla con este origen, así la cookie de sesión es httpOnly y
// del mismo sitio, y la URL interna de la API (API_URL) se lee en tiempo de ejecución, no al compilar.
import type { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
// `origin` viaja para que la API compruebe que un cambio de estado con cookie sale de este mismo sitio.
const FORWARD_REQUEST = ["content-type", "cookie", "authorization", "accept", "origin"];
// Solo detrás de un proxy inverso propio (IIS, ALB) que añade la dirección del cliente al final de X-Forwarded-For.
// Sin ese proxy la cabecera la escribe el cliente y no vale: se deja apagado.
const TRUST_FORWARDED_FOR = ["1", "true"].includes((process.env.TRUST_FORWARDED_FOR ?? "").toLowerCase());
// Solo las rutas que usa la web. El resto de la API (`/mcp`, `/health/metrics`, `/docs`) no se alcanza desde este origen.
const ALLOWED = ["auth", "login", "setup", "me", "discover", "catalog", "assets", "curation", "admin"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (!ALLOWED.includes(path[0])) {
    return Response.json({ detail: "No encontrado" }, { status: 404 });
  }
  const target = `${API_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  // El sitio que el navegador ve: la API lo compara con `origin`. Si delante hay un proxy que cambia `Host`, el
  // origen público debe estar además en DISCOVERY_DATA_AGENT_CORS_ORIGINS de la API.
  const host = req.headers.get("x-forwarded-host")?.split(",")[0].trim() || req.headers.get("host");
  if (host) headers.set("x-forwarded-host", host);
  if (TRUST_FORWARDED_FOR) {
    const client = (req.headers.get("x-forwarded-for") ?? "").split(",").pop()?.trim();
    if (client) headers.set("x-forwarded-for", client);
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "No se pudo contactar a la API de Discovery Data Agent" }, { status: 502 });
  }
  const out = new Headers();
  const type = upstream.headers.get("content-type");
  if (type) out.set("content-type", type);
  // La API marca todo como no almacenable; sin esta cabecera un proxy con caché delante de la web no lo sabría.
  out.set("cache-control", upstream.headers.get("cache-control") ?? "no-store");
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const dynamic = "force-dynamic";
export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
