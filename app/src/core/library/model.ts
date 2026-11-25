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
  /** "musescore": the MusicXML and PDF were exported from a MuseScore file, so the notes are exact. */
  from?: "musescore" | string;
  /** For a PDF with no MusicXML: conversion already asked for. */
  requested?: boolean;
  /** For a PDF with no MusicXML: the last conversion on the PC failed. */
  convert_failed?: boolean;
}

/** requests/_status.json, written by `lento-library watch` on the PC. */
export interface PcStatus {
  pc: string;
  state: "idle" | "converting" | "exporting" | "stopped" | string;
  heartbeat: string;
  interval_s: number;
  /** PDF names still to come in this batch, in the order they will convert. */
  queue: string[];
  current: string | null;
  results: { pdf: string; ok: boolean; at: string; seconds?: number }[];
  musescore?: boolean; // false when MuseScore files are waiting but MuseScore isn't installed on the PC
  /** Version 2 and later: the PDFs converting now, since when, and how far the batch has got. */
  current_files?: string[];
  started?: string;
  batch?: { total: number; done: number; started: string };
  /** Recent seconds per converted PDF (median), for time estimates. */
  avg_s?: number | null;
}

/** Is the watcher running? It writes a heartbeat on every look, so a stale one means the PC is off or it stopped. */
export function pcOnline(s: PcStatus, now = Date.now()): boolean {
  if (s.state === "stopped") return false;
  const age = now - Date.parse(s.heartbeat);
  const looks = Math.max(3, 3 * (s.interval_s || 30)) * 1000 + 120_000;
  // newer watchers renew the heartbeat during a conversion; older ones hold it, so allow an hour for those
  return age < (s.state === "converting" && !s.batch ? 3600_000 : looks);
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
  /** From catalog.csv's newer columns (filled by `lento-library details` from a spreadsheet). */
  year?: string;
  genre?: string;
  instrumentation?: string;
  level?: string;
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
  return fold(
    [p.title, p.composer, p.id, p.catalog_no, p.key, p.year, p.genre, p.instrumentation, p.level, ...(p.tags ?? []), ...p.files.map((f) => f.edition ?? "")].join(" "),
  );
}

const cache = new WeakMap<Piece, string>();

/** Every word of the query must appear somewhere in the piece (and it has the tag, if one is given). Keeps the order. */
export function matching(pieces: Piece[], query: string, tag = ""): Piece[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length && !tag) return pieces.slice();
  return pieces.filter((p) => {
    if (tag && !p.tags?.includes(tag)) return false;
    let h = cache.get(p);
    if (h === undefined) cache.set(p, (h = haystack(p)));
    return words.every((w) => h!.includes(w));
  });
}

const byName = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

/** matching(), sorted by composer, then title. */
export function search(pieces: Piece[], query: string, tag = ""): Piece[] {
  return matching(pieces, query, tag).sort((a, b) => byName.compare(a.composer, b.composer) || byName.compare(a.title, b.title));
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
  return f.musicxml ? { name: f.musicxml, kind: "musicxml", variant: f.variant, quality: f.quality, from: f.from } : null;
}

/** "convert__<pdf name without .pdf>.json", the file `lento-library convert` looks for. */
export function requestName(f: LibraryFile): string {
  return `convert__${f.name.replace(/\.pdf$/i, "")}.json`;
}
