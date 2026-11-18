import { Fragment, type ReactNode } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

/**
 * Markdown mínimo para documentos propios (el manual de desarrollo): títulos, párrafos, listas, tablas, bloques de
 * código, negrita y código en línea. Construye elementos de React; nunca inserta HTML, así que el texto no puede
 * inyectar marcado.
 */
type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "code"; text: string };

const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
    } else if (line.startsWith("```")) {
      const body: string[] = [];
      for (i += 1; i < lines.length && !lines[i].startsWith("```"); i += 1) body.push(lines[i]);
      i += 1;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (/^#{1,4}\s/.test(line)) {
      const level = line.match(/^#+/)![0].length;
      blocks.push({ kind: "heading", level, text: line.slice(level).trim() });
      i += 1;
    } else if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i += 1) rows.push(cells(lines[i]));
      blocks.push({ kind: "table", head, rows });
    } else if (LIST_ITEM.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      for (; i < lines.length && lines[i].trim(); i += 1) {
        const item = lines[i].match(LIST_ITEM);
        if (item) items.push(item[3]);
        else if (items.length) items[items.length - 1] += ` ${lines[i].trim()}`;
      }
      blocks.push({ kind: "list", ordered, items });
    } else {
      const body: string[] = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\|)/.test(lines[i]) && !LIST_ITEM.test(lines[i]); i += 1)
        body.push(lines[i].trim());
      blocks.push({ kind: "paragraph", text: body.join(" ") });
    }
  }
  return blocks;
}

function inline(text: string): ReactNode {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("`") && part.length > 2)
      return (
        <code key={i} className="bg-muted rounded px-1 py-0.5 font-mono text-[0.85em] break-words">
          {part.slice(1, -1)}
        </code>
      );
    if (part.startsWith("**") && part.length > 4)
      return (
        <strong key={i} className="text-foreground font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function slug(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export function headings(markdown: string, level = 2): { id: string; text: string }[] {
  return parse(markdown)
    .filter((b): b is Extract<Block, { kind: "heading" }> => b.kind === "heading" && b.level === level)
    .map((b) => ({ id: slug(b.text), text: b.text }));
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-4 text-sm leading-relaxed">
      {parse(text).map((block, i) => {
        switch (block.kind) {
          case "heading": {
            if (block.level === 1) return <h1 key={i} className="text-2xl font-semibold tracking-tight">{inline(block.text)}</h1>;
            if (block.level === 2)
              return (
                <h2 key={i} id={slug(block.text)} className="scroll-mt-20 border-b pt-6 pb-2 text-lg font-semibold tracking-tight">
                  {inline(block.text)}
                </h2>
              );
            return <h3 key={i} className="pt-2 text-base font-semibold">{inline(block.text)}</h3>;
          }
          case "paragraph":
            return <p key={i} className="text-muted-foreground max-w-prose">{inline(block.text)}</p>;
          case "list": {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List key={i} className={`text-muted-foreground max-w-prose space-y-1.5 pl-5 ${block.ordered ? "list-decimal" : "list-disc"}`}>
                {block.items.map((item, j) => (
                  <li key={j}>{inline(item)}</li>
                ))}
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
                        <TableHead key={j} className="whitespace-nowrap">{inline(h)}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {block.rows.map((row, j) => (
                      <TableRow key={j}>
                        {row.map((cell, k) => (
                          <TableCell key={k} className={`align-top whitespace-normal ${k === 0 ? "text-foreground min-w-36" : "text-muted-foreground min-w-48"}`}>
                            {inline(cell)}
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
