import type { NextConfig } from "next";

const production = process.env.NODE_ENV === "production";

// Cabeceras de seguridad de todas las respuestas de la web (las de la API no llegan al navegador: pasan por el proxy).
// Next.js inyecta scripts y estilos en línea, por eso `'unsafe-inline'`; `'unsafe-eval'` solo lo necesita `next dev`.
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${production ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  `connect-src 'self'${production ? "" : " ws: wss:"}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // El navegador solo la aplica sobre HTTPS (IIS o el balanceador terminan TLS).
  ...(production ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }] : []),
];

const nextConfig: NextConfig = {
  output: "standalone", // imagen Docker mínima (web/Dockerfile)
  poweredByHeader: false,
  // Permite compilar a otra carpeta sin pisar la de `next dev` (NEXT_DIST_DIR=.next-build npm run build).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
