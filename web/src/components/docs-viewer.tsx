"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { AlertCircle, ExternalLink, FileText, Lock, RefreshCw, Workflow } from "lucide-react";

import { decoded, Markdown, outline, slug } from "@/components/markdown";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { DocsEntry, DocsIndex } from "@/lib/types";

/**
 * Visor de la documentación interna (solo `data_admin`): manual, wiki, arquitectura y sus diagramas. Lo abierto vive
 * en la URL (`?tab=docs&doc=wiki/componentes/api.md#configuración`), así un enlace se puede compartir. Cada página o
 * diagrama que se abre es una lectura auditada en la API.
 *
 * Un diagrama es HTML autónomo con scripts en línea. Se pinta en un `iframe` con `srcdoc` y `sandbox` sin el permiso
 * de mismo origen: corre en un origen opaco, sin la cookie de sesión, sin el almacenamiento de la web y sin acceso
 * a esta página. Hereda el CSP de la web tal cual (no hay que relajarlo) y nunca entra en el DOM de la aplicación.
 */
const MANUAL = "manual-desarrollo.md";
const SECTIONS: Record<string, string> = { "": "Manual", wiki: "Wiki", "wiki/componentes": "Componentes", architecture: "Arquitectura" };
const SECTION_ORDER = ["", "wiki", "wiki/componentes", "architecture"];
const BASE = "https://docs.invalid/docs/"; // solo para resolver rutas relativas; nunca se pide

type Location = { path: string; hash: string };
type Doc = { path: string; title: string; updated_at: string } & ({ markdown: string } | { html: string });
type Target =
  | { kind: "doc"; path: string; hash: string } // página o diagrama servidos: se abre en el visor
  | { kind: "anchor"; hash: string }
  | { kind: "external"; href: string }
  | { kind: "outside"; path: string }; // existe en el repositorio, pero el visor no lo sirve

const isDiagram = (path: string) => path.endsWith(".html");

function readLocation(): Location {
  const params = new URLSearchParams(window.location.search);
  return { path: params.get("doc") || MANUAL, hash: decoded(window.location.hash.slice(1)) };
}

function viewerHref({ path, hash }: Location): string {
  const params = new URLSearchParams({ tab: "docs", doc: path });
  return `?${params.toString()}${hash ? `#${slug(hash)}` : ""}`;
}

/** A dónde lleva un enlace de la página `current` (ruta relativa a `docs/`). */
function resolveLink(href: string, current: string, served: Set<string>): Target {
  if (href.startsWith("#")) return { kind: "anchor", hash: decoded(href.slice(1)) };
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return href.startsWith("https://") ? { kind: "external", href } : { kind: "outside", path: href };
  let url: URL;
  try {
    url = new URL(href, BASE + current);
  } catch {
    return { kind: "outside", path: href };
  }
  const fromRoot = decoded(url.pathname).replace(/^\/+/, ""); // ruta dentro del repositorio
  const path = fromRoot.startsWith("docs/") ? fromRoot.slice("docs/".length) : null;
  if (path !== null && served.has(path)) return { kind: "doc", path, hash: isDiagram(path) ? "" : decoded(url.hash.slice(1)) };
  return { kind: "outside", path: fromRoot };
}

export function DocsViewer() {
  const [index, setIndex] = useState<DocsIndex | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [location, setLocation] = useState<Location>(readLocation);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false); // la persona navegó: el foco va al título de lo nuevo

  useEffect(() => {
    api
      .docsIndex()
      .then(setIndex)
      .catch((e: Error) => setIndexError(e.message));
  }, []);

  useEffect(() => {
    const onPop = () => {
      setDocError(null);
      setLocation(readLocation());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Cada apertura es una lectura auditada: se pide al cambiar de documento, no al cambiar de ancla.
  useEffect(() => {
    let live = true;
    const load: Promise<Doc> = isDiagram(location.path) ? api.docsDiagram(location.path) : api.docsPage(location.path);
    load
      .then((d) => {
        if (!live) return;
        setDoc(d);
        setDocError(null);
      })
      .catch((e: Error) => {
        if (!live) return;
        setDoc(null);
        setDocError(e.message);
      });
    return () => {
      live = false;
    };
  }, [location.path, attempt]);

  // Ya pintado: al ancla pedida, o al principio con el foco en el título si se llegó navegando.
  useEffect(() => {
    if (!doc || doc.path !== location.path) return;
    const target = location.hash ? document.getElementById(slug(location.hash)) : null;
    if (target) target.scrollIntoView();
    else if (moved.current) titleRef.current?.scrollIntoView();
    if (moved.current) titleRef.current?.focus({ preventScroll: true });
    moved.current = false;
  }, [doc, location]);

  const go = useCallback((next: Location) => {
    window.history.pushState(null, "", viewerHref(next));
    moved.current = true;
    setDocError(null);
    setLocation(next);
  }, []);

  const follow = useCallback(
    (next: Location) => (e: MouseEvent<HTMLAnchorElement>) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // otra pestaña: lo hace el navegador
      e.preventDefault();
      go(next);
    },
    [go],
  );

  const served = useMemo(() => new Set([...(index?.pages ?? []), ...(index?.diagrams ?? [])].map((d) => d.path)), [index]);

  const renderLink = useCallback(
    (href: string, children: ReactNode, key: number): ReactNode => {
      const target = resolveLink(href, location.path, served);
      switch (target.kind) {
        case "doc": {
          const next = { path: target.path, hash: target.hash };
          return (
            <a key={key} href={viewerHref(next)} onClick={follow(next)} className="text-foreground underline underline-offset-4">
              {children}
            </a>
          );
        }
        case "anchor":
          return (
            <a key={key} href={`#${slug(target.hash)}`} className="text-foreground underline underline-offset-4">
              {children}
            </a>
          );
        case "external":
          return (
            <a key={key} href={target.href} target="_blank" rel="noopener noreferrer" className="text-foreground underline underline-offset-4">
              {children}
              <ExternalLink aria-hidden className="ml-0.5 inline size-3" />
              <span className="sr-only"> (se abre en una pestaña nueva)</span>
            </a>
          );
        case "outside":
          return (
            <span key={key} title="No se muestra en la aplicación: está en el repositorio">
              {children}{" "}
              <code className="text-muted-foreground bg-muted rounded px-1 font-mono text-[0.75em]">{target.path}</code>
            </span>
          );
      }
    },
    [location.path, served, follow],
  );

  const groups = useMemo(() => {
    const bySection = new Map<string, DocsEntry[]>();
    for (const p of index?.pages ?? []) bySection.set(p.section ?? "", [...(bySection.get(p.section ?? "") ?? []), p]);
    const sorted = [...bySection.entries()].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
    if (index?.diagrams.length) sorted.push(["diagramas", index.diagrams]);
    return sorted;
  }, [index]);

  if (indexError)
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>No se pudo abrir la documentación</AlertTitle>
        <AlertDescription>{indexError}</AlertDescription>
      </Alert>
    );

  const stale = !!doc && doc.path !== location.path; // lo siguiente está en camino
  const toc = doc && "markdown" in doc ? outline(doc.markdown) : [];
  return (
    <div className="grid gap-5 md:grid-cols-[15rem_minmax(0,1fr)]">
      <nav
        aria-label="Índice de la documentación"
        className="space-y-4 text-sm md:sticky md:top-4 md:max-h-[calc(100svh-2rem)] md:self-start md:overflow-y-auto"
      >
        {!index ? (
          <div className="space-y-2" aria-busy="true" aria-label="Cargando el índice">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>
        ) : (
          groups.map(([section, entries]) => (
            <div key={section}>
              <h3 className="text-muted-foreground mb-1 px-2 text-xs font-medium tracking-wide uppercase">
                {section === "diagramas" ? "Diagramas" : (SECTIONS[section] ?? section)}
              </h3>
              <ul className="space-y-0.5">
                {entries.map((entry) => {
                  const active = entry.path === location.path;
                  const next = { path: entry.path, hash: "" };
                  const Icon = isDiagram(entry.path) ? Workflow : FileText;
                  return (
                    <li key={entry.path}>
                      <a
                        href={viewerHref(next)}
                        onClick={follow(next)}
                        aria-current={active ? "page" : undefined}
                        className={`focus-visible:ring-ring flex gap-2 rounded-md px-2 py-1 outline-none focus-visible:ring-2 ${active ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"}`}
                      >
                        <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                        <span>{shortTitle(entry)}</span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </nav>

      <div className="min-w-0" aria-busy={(!doc && !docError) || stale}>
        {docError ? (
          <Alert variant="destructive">
            <AlertCircle />
            <AlertTitle>No se pudo abrir docs/{location.path}</AlertTitle>
            <AlertDescription>
              <p>{docError}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setDocError(null);
                    setAttempt((n) => n + 1);
                  }}
                >
                  <RefreshCw /> Reintentar
                </Button>
                {location.path !== MANUAL && (
                  <Button size="sm" variant="outline" asChild>
                    <a href={viewerHref({ path: MANUAL, hash: "" })} onClick={follow({ path: MANUAL, hash: "" })}>
                      Ir al manual
                    </a>
                  </Button>
                )}
              </div>
            </AlertDescription>
          </Alert>
        ) : !doc ? (
          <div className="space-y-3" aria-label="Cargando">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-96 w-full" />
          </div>
        ) : (
          <Card className={stale ? "opacity-60 transition-opacity" : undefined}>
            <CardHeader className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="gap-1 font-normal">
                  <Lock className="size-3" /> Solo administradores de datos
                </Badge>
                <code className="text-muted-foreground text-xs">docs/{doc.path}</code>
                <span className="text-muted-foreground text-xs">
                  Actualizado el {dateTime(doc.updated_at)} · cada lectura queda en la auditoría
                </span>
              </div>
              <h2 ref={titleRef} tabIndex={-1} className="text-xl font-semibold tracking-tight outline-none">
                {doc.title}
              </h2>
              {toc.length > 0 && (
                <details open className="rounded-lg border px-3 py-2 text-sm">
                  <summary className="cursor-pointer font-medium">En esta página</summary>
                  <nav aria-label="En esta página">
                    <ul className="mt-2 space-y-1">
                      {toc.map((h) => (
                        <li key={h.id} className={h.level === 3 ? "pl-4" : undefined}>
                          <a href={`#${h.id}`} className="text-muted-foreground hover:text-foreground underline-offset-4 hover:underline">
                            {h.text}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </nav>
                </details>
              )}
            </CardHeader>
            <CardContent>
              {"markdown" in doc ? (
                <Markdown text={withoutTitle(doc.markdown)} renderLink={renderLink} />
              ) : (
                <iframe
                  key={doc.path}
                  title={`Diagrama: ${doc.title}`}
                  srcDoc={doc.html}
                  sandbox="allow-scripts allow-downloads"
                  referrerPolicy="no-referrer"
                  className="h-[75svh] min-h-[28rem] w-full rounded-lg border bg-white"
                />
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function rank(section: string): number {
  const i = SECTION_ORDER.indexOf(section);
  return i < 0 ? SECTION_ORDER.length - 1 : i; // otra carpeta de la wiki, antes de la arquitectura
}

/** Títulos cortos para el índice: "ConverData — C4 nivel 1: contexto" → "C4 nivel 1: contexto". */
function shortTitle(entry: DocsEntry): string {
  if (entry.path === "wiki/README.md") return "Inicio de la wiki";
  if (entry.path === "architecture/README.md") return "Arquitectura (C4)";
  if (entry.path === MANUAL) return "Manual de desarrollo";
  return entry.title.replace(/^ConverData\s+—\s+/, "");
}

/** El título ya va en la cabecera de la tarjeta. */
function withoutTitle(markdown: string): string {
  return markdown.replace(/^﻿?# .*(\r?\n)+/, "");
}
