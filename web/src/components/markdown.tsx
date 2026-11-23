import { Fragment, type ReactNode } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

/**
 * Markdown mínimo para documentos propios (el manual, la wiki y la arquitectura): títulos, párrafos, listas (con un
 * nivel de anidación), tablas, bloques de código, enlaces, negrita, cursiva y código en línea. Construye elementos de
 * React; nunca inserta HTML, así que el texto no puede inyectar marcado.
 *
 * Los enlaces los decide quien muestra el documento (`renderLink`). Sin él, solo se enlazan las anclas de la misma
 * página y las direcciones `https:`; cualquier otro destino queda como texto.
 */
type ListItem = { text: string; children?: { ordered: boolean; items: string[] } };
type Block =
  | { kind: "heading"; level: number; text: string; id: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: ListItem[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "code"; text: string };

export type RenderLink = (href: string, children: ReactNode, key: number) => ReactNode;

const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
const HEADING = /^(#{1,4})\s+(.*)$/;
const ESCAPED_PIPE = "\u0000";

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/\\\|/g, ESCAPED_PIPE) // `\|` dentro de una celda es una barra, no un separador
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.replaceAll(ESCAPED_PIPE, "|").trim());
}

/** Texto plano de un título (sin `código`, **negrita** ni enlaces) para su ancla. */
function plain(text: string): string {
  return text.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[`*]/g, "");
}

function parseList(lines: string[], start: number): { block: Extract<Block, { kind: "list" }>; next: number } {
  const first = lines[start].match(LIST_ITEM)!;
  const base = first[1].length;
  const ordered = /^\d+\./.test(first[2]);
  const items: ListItem[] = [];
  let childIndent = -1;
  let i = start;
  for (; i < lines.length && lines[i].trim(); i += 1) {
    const line = lines[i];
    const item = line.match(LIST_ITEM);
    const indent = line.length - line.trimStart().length;
    const parent = items[items.length - 1];
    if (item && indent <= base + 1) {
      items.push({ text: item[3] });
      childIndent = -1;
    } else if (item && parent) {
      parent.children ??= { ordered: /^\d+\./.test(item[2]), items: [] };
      parent.children.items.push(item[3]);
      childIndent = indent;
    } else if (parent) {
      // Continuación: va al último subelemento si está más sangrada que su viñeta; si no, al elemento.
      const children = parent.children?.items;
      if (children && childIndent >= 0 && indent > childIndent) children[children.length - 1] += ` ${line.trim()}`;
      else parent.text += ` ${line.trim()}`;
    }
  }
  return { block: { kind: "list", ordered, start: ordered ? parseInt(first[2], 10) : 1, items }, next: i };
}

function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const heading = line.match(HEADING);
    if (!line.trim()) {
      i += 1;
    } else if (line.startsWith("```")) {
      const body: string[] = [];
      for (i += 1; i < lines.length && !lines[i].startsWith("```"); i += 1) body.push(lines[i]);
      i += 1;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (heading) {
      const text = heading[2].trim();
      blocks.push({ kind: "heading", level: heading[1].length, text, id: slug(plain(text)) });
      i += 1;
    } else if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i += 1) rows.push(cells(lines[i]));
      blocks.push({ kind: "table", head, rows });
    } else if (LIST_ITEM.test(line)) {
      const { block, next } = parseList(lines, i);
      blocks.push(block);
      i = next;
    } else {
      const body: string[] = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\|)/.test(lines[i]) && !LIST_ITEM.test(lines[i]); i += 1)
        body.push(lines[i].trim());
      blocks.push({ kind: "paragraph", text: body.join(" ") });
    }
  }
  return blocks;
}

// Código en línea, enlace, negrita y cursiva, en ese orden de prioridad: lo que va entre comillas invertidas no se
// interpreta (`docs/architecture/*.html` no abre una cursiva).
const INLINE = /(`[^`]+`)|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*\s](?:[^*]*[^*\s])?)\*/g;

function defaultLink(href: string, children: ReactNode, key: number): ReactNode {
  if (href.startsWith("#"))
    return (
      <a key={key} href={`#${slug(decoded(href.slice(1)))}`} className="text-foreground underline underline-offset-4">
        {children}
      </a>
    );
  if (href.startsWith("https://"))
    return (
      <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="text-foreground underline underline-offset-4">
        {children}
      </a>
    );
  return <Fragment key={key}>{children}</Fragment>;
}

function inline(text: string, renderLink: RenderLink): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(<Fragment key={key++}>{text.slice(last, m.index)}</Fragment>);
    const [, code, label, href, bold, italic] = m;
    if (code)
      out.push(
        <code key={key++} className="bg-muted rounded px-1 py-0.5 font-mono text-[0.85em] break-words">
          {code.slice(1, -1)}
        </code>,
      );
    else if (label !== undefined) out.push(renderLink(href, inline(label, renderLink), key++));
    else if (bold)
      out.push(
        <strong key={key++} className="text-foreground font-semibold">
          {inline(bold, renderLink)}
        </strong>,
      );
    else out.push(<em key={key++}>{inline(italic, renderLink)}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return out;
}

/** `decodeURIComponent` que no lanza con un `%` suelto. */
export function decoded(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/** Ancla de un título: minúsculas, sin acentos y lo demás a guiones (`#configuración` y `#configuracion` coinciden). */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Títulos de nivel 2 y 3, para la tabla de contenidos de la página. */
export function outline(markdown: string): { id: string; text: string; level: number }[] {
  return parse(markdown)
    .filter((b): b is Extract<Block, { kind: "heading" }> => b.kind === "heading" && (b.level === 2 || b.level === 3))
    .map((b) => ({ id: b.id, text: plain(b.text), level: b.level }));
}

export function Markdown({ text, renderLink = defaultLink }: { text: string; renderLink?: RenderLink }) {
  const md = (t: string) => inline(t, renderLink);
  return (
    <div className="space-y-4 text-sm leading-relaxed">
      {parse(text).map((block, i) => {
        switch (block.kind) {
          case "heading": {
            if (block.level === 1)
              return (
                <h1 key={i} id={block.id} className="scroll-mt-20 text-2xl font-semibold tracking-tight">
                  {md(block.text)}
                </h1>
              );
            if (block.level === 2)
              return (
                <h2 key={i} id={block.id} className="scroll-mt-20 border-b pt-6 pb-2 text-lg font-semibold tracking-tight">
                  {md(block.text)}
                </h2>
              );
            if (block.level === 3)
              return (
                <h3 key={i} id={block.id} className="scroll-mt-20 pt-2 text-base font-semibold">
                  {md(block.text)}
                </h3>
              );
            return (
              <h4 key={i} id={block.id} className="scroll-mt-20 pt-1 text-sm font-semibold">
                {md(block.text)}
              </h4>
            );
          }
          case "paragraph":
            return <p key={i} className="text-muted-foreground max-w-prose">{md(block.text)}</p>;
          case "list": {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List
                key={i}
                start={block.ordered && block.start !== 1 ? block.start : undefined}
                className={`text-muted-foreground max-w-prose space-y-1.5 pl-5 ${block.ordered ? "list-decimal" : "list-disc"}`}
              >
                {block.items.map((item, j) => {
                  const Sub = item.children?.ordered ? "ol" : "ul";
                  return (
                    <li key={j}>
                      {md(item.text)}
                      {item.children && (
                        <Sub className={`mt-1.5 space-y-1 pl-5 ${item.children.ordered ? "list-decimal" : "list-[circle]"}`}>
                          {item.children.items.map((child, k) => (
                            <li key={k}>{md(child)}</li>
                          ))}
                        </Sub>
                      )}
                    </li>
                  );
                })}
              </List>
            );
          }
          case "code":
            return (
              <pre key={i} className="bg-muted overflow-x-auto rounded-lg border p-3 font-mono text-xs leading-relaxed">
                {block.text}
              </pre>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      {block.head.map((h, j) => (
                        <TableHead key={j} className="whitespace-nowrap">{md(h)}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {block.rows.map((row, j) => (
                      <TableRow key={j}>
                        {row.map((cell, k) => (
                          <TableCell key={k} className={`align-top whitespace-normal ${k === 0 ? "text-foreground min-w-36" : "text-muted-foreground min-w-48"}`}>
                            {md(cell)}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            );
        }
      })}
    </div>
  );
}
