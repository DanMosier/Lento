/** The library.json index (written by `lento-library build` on the desktop) and searching it. */

export interface LibraryFile {
  name: string;
  kind: "pdf" | "musicxml";
  variant: string;
  edition?: string;
  source?: string;
  pages?: number;
  /** For a PDF: the MusicXML of the same name beside it, if there is one. */
  musicxml?: string;
  /** Lento_ConvertPDF's rating of that MusicXML. */
  quality?: "OK" | "REVIEW" | "UNRELIABLE" | string;
  /** For a PDF with no MusicXML: conversion already asked for. */
  requested?: boolean;
}

export interface Piece {
  id: string;
  title: string;
  composer: string;
  catalog_no?: string;
  key?: string;
  clefs?: string;
  positions?: string;
  notes?: string;
  tags?: string[];
  /** True when any edition has a MusicXML. */
  musicxml?: boolean;
  files: LibraryFile[];
}

export interface LibraryIndex {
  format: "lento-library";
  version: number;
  generated: string;
  pieces: Piece[];
}

export function parseIndex(text: string): LibraryIndex {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("library.json is not valid JSON. Run lento-library build again.");
  }
  const d = data as Partial<LibraryIndex>;
  if (d?.format !== "lento-library" || !Array.isArray(d.pieces)) throw new Error("This library.json was not made by lento-library build.");
  if ((d.version ?? 0) > 1) throw new Error("This library.json is newer than the app. Reload the app to update it.");
  const pieces = d.pieces.filter((p): p is Piece => !!p && typeof p.id === "string" && Array.isArray(p.files));
  return { format: "lento-library", version: d.version ?? 1, generated: d.generated ?? "", pieces };
}

/** Lowercase, accents removed, so "saint saens" finds "Saint-Saëns". */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[-_]/g, " ");
}

function haystack(p: Piece): string {
  return fold([p.title, p.composer, p.id, p.catalog_no, p.key, ...(p.tags ?? []), ...p.files.map((f) => f.edition ?? "")].join(" "));
}

const cache = new WeakMap<Piece, string>();

/** Every word of the query must appear somewhere in the piece. Sorted by composer, then title. */
export function search(pieces: Piece[], query: string, tag = ""): Piece[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  return pieces
    .filter((p) => {
      if (tag && !p.tags?.includes(tag)) return false;
      let h = cache.get(p);
      if (h === undefined) cache.set(p, (h = haystack(p)));
      return words.every((w) => h!.includes(w));
    })
    .sort((a, b) => a.composer.localeCompare(b.composer) || a.title.localeCompare(b.title));
}

export function allTags(pieces: Piece[]): string[] {
  return [...new Set(pieces.flatMap((p) => p.tags ?? []))].sort();
}

/** Accepts a Drive folder link (…/folders/<id>…, ?id=<id>) or a bare id. */
export function folderIdFromLink(text: string): string | null {
  const t = text.trim();
  const m = t.match(/\/folders\/([\w-]{10,})/) ?? t.match(/[?&]id=([\w-]{10,})/);
  if (m) return m[1];
  return /^[\w-]{10,}$/.test(t) ? t : null;
}

/** The MusicXML to practise from for this file: the file itself, or the one beside a PDF. */
export function musicxmlOf(f: LibraryFile): LibraryFile | null {
  if (f.kind === "musicxml") return f;
  return f.musicxml ? { name: f.musicxml, kind: "musicxml", variant: f.variant, quality: f.quality } : null;
}

/** "convert__<pdf name without .pdf>.json", the file `lento-library convert` looks for. */
export function requestName(f: LibraryFile): string {
  return `convert__${f.name.replace(/\.pdf$/i, "")}.json`;
}
