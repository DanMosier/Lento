/**
 * The Library table: its columns, and filtering and sorting the pieces for it. Pure functions over the index, so
 * the screen only draws the rows in view (see ui.ts) and these are tested on their own.
 */
import type { Piece } from "../core/library/model";
import { matching, musicxmlOf } from "../core/library/model";

export type ColumnId = "title" | "composer" | "genre" | "year" | "instrumentation" | "level" | "key" | "tags" | "editions" | "musicxml";

export interface Column {
  id: ColumnId;
  label: string;
  width: number; // px
  numeric?: boolean;
}

export const COLUMNS: Column[] = [
  { id: "title", label: "Title", width: 220 },
  { id: "composer", label: "Composer", width: 170 },
  { id: "genre", label: "Genre / era", width: 140 },
  { id: "year", label: "Year", width: 64, numeric: true },
  { id: "instrumentation", label: "Instrumentation", width: 190 },
  { id: "level", label: "Level", width: 140 },
  { id: "key", label: "Key", width: 90 },
  { id: "tags", label: "Technique", width: 170 },
  { id: "editions", label: "PDFs", width: 56, numeric: true },
  { id: "musicxml", label: "MusicXML", width: 96 },
];

/** "Yes", "check" (converted automatically, may be wrong), "MuseScore", or "" for none. */
export function xmlState(p: Piece): string {
  let best = "";
  for (const f of p.files) {
    const x = musicxmlOf(f);
    if (!x) continue;
    if (x.from === "musescore") return "MuseScore";
    const s = x.quality === "REVIEW" || x.quality === "UNRELIABLE" ? "check" : "Yes";
    if (s === "Yes" || !best) best = s;
  }
  return best;
}

export function cell(p: Piece, id: ColumnId): string {
  switch (id) {
    case "tags":
      return (p.tags ?? []).join(", ");
    case "editions":
      return String(p.files.filter((f) => f.kind === "pdf").length || "");
    case "musicxml":
      return xmlState(p);
    default:
      return p[id] ?? "";
  }
}

export interface Filters {
  query: string;
  genre: string;
  instrumentation: string;
  level: string;
  tag: string;
  /** "", "yes" (has MusicXML) or "no". */
  musicxml: string;
}

export interface Sort {
  by: ColumnId;
  desc: boolean;
}

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

function num(s: string): number {
  const m = s.match(/\d{3,4}|\d+/);
  return m ? Number(m[0]) : Number.NaN;
}

/** Filters, then sorts; empty values always sort last, and ties fall back to composer, then title. */
export function rows(pieces: Piece[], f: Filters, sort: Sort): Piece[] {
  const found = matching(pieces, f.query, f.tag).filter(
    (p) =>
      (!f.genre || p.genre === f.genre) &&
      (!f.instrumentation || p.instrumentation === f.instrumentation) &&
      (!f.level || p.level === f.level) &&
      (!f.musicxml || (f.musicxml === "yes") === !!xmlState(p)),
  );
  const col = COLUMNS.find((c) => c.id === sort.by) ?? COLUMNS[0];
  const dir = sort.desc ? -1 : 1;
  const keyed = found.map((p) => ({ p, v: cell(p, col.id) }));
  keyed.sort((a, b) => {
    if (!a.v !== !b.v) return a.v ? -1 : 1;
    let c = 0;
    if (col.numeric) {
      const x = num(a.v);
      const y = num(b.v);
      c = Number.isNaN(x) || Number.isNaN(y) ? collator.compare(a.v, b.v) : x - y;
    } else c = collator.compare(a.v, b.v);
    return c * dir || collator.compare(a.p.composer, b.p.composer) || collator.compare(a.p.title, b.p.title);
  });
  return keyed.map((k) => k.p);
}

/** The distinct values of a column, for its filter menu, most common first and then alphabetical. */
export function choices(pieces: Piece[], id: "genre" | "instrumentation" | "level"): string[] {
  const n = new Map<string, number>();
  for (const p of pieces) {
    const v = p[id];
    if (v) n.set(v, (n.get(v) ?? 0) + 1);
  }
  return [...n.keys()].sort((a, b) => (id === "level" ? collator.compare(a, b) : n.get(b)! - n.get(a)! || collator.compare(a, b)));
}
