/**
 * Splitting a PDF of several pieces: which pages make up each piece, and what the new files are called. Pure
 * functions, tested on their own. The names follow the PC's splitter (lento_convertpdf/pdf_splitter.py), so a PDF
 * split on the phone looks the same as one split at the PC: "01 - Composer - Title.pdf" in a folder called
 * "<the PDF's name> (split)", in the library's inbox/ (pieces/ only holds scores that have been filed).
 */

export interface Part {
  start: number; // first page, from 1
  end: number; // last page, inclusive
  title: string;
  keep: boolean; // left out when false (a page of adverts, the piano part you don't need)
  named?: boolean; // the title was typed in, so it stays as it is (a suggested one follows the part's number)
}

/** Pages are split by where each piece starts. Page 1 always starts one. */
export function normalizeStarts(starts: Iterable<number>, pages: number): number[] {
  const set = new Set<number>([1]);
  for (const s of starts) if (Number.isInteger(s) && s >= 1 && s <= pages) set.add(s);
  return [...set].sort((a, b) => a - b);
}

/** Adds a start on that page, or takes it away (except page 1). */
export function toggleStart(starts: number[], page: number, pages: number): number[] {
  if (page === 1) return normalizeStarts(starts, pages);
  return normalizeStarts(starts.includes(page) ? starts.filter((s) => s !== page) : [...starts, page], pages);
}

/**
 * The parts for these starts. A part keeps its keep box, and a title that was typed in, while it still starts on the
 * same page, so adding a start further on doesn't wipe them. Other titles are `titleFor(its number, its start page)`,
 * so suggested names stay numbered in order.
 */
export function partsFor(starts: number[], pages: number, old: Part[], titleFor: (n: number, start: number) => string): Part[] {
  const s = normalizeStarts(starts, pages);
  return s.map((start, i) => {
    const prev = old.find((p) => p.start === start);
    const end = i + 1 < s.length ? s[i + 1] - 1 : pages;
    return { start, end, title: prev?.named ? prev.title : titleFor(i + 1, start), keep: prev?.keep ?? true, named: prev?.named ?? false };
  });
}

/** The same clean-up as the PC's splitter: no characters Windows or Drive object to, no runs of spaces, not too long. */
export function sanitize(name: string): string {
  const cleaned = name
    // eslint-disable-next-line no-control-regex
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/^[ .\-_]+|[ .\-_]+$/g, "");
  return cleaned ? cleaned.slice(0, 110) : "Untitled Piece";
}

/** "01 - Composer - Title.pdf", as the PC names them (no number added when the title already starts with one). */
export function fileName(n: number, title: string, composer = ""): string {
  const t = sanitize(title || `Piece ${n}`);
  const c = composer ? sanitize(composer) : "";
  const base = c && !t.toLowerCase().startsWith(c.toLowerCase()) ? `${c} - ${t}` : t;
  return /^\d+\s*[-_.]/.test(base) ? `${base}.pdf` : `${String(n).padStart(2, "0")} - ${base}.pdf`;
}

/** The file names for the kept parts, numbered by their place in the PDF, never two the same. */
export function fileNames(parts: Part[], composer = "", taken: Iterable<string> = []): string[] {
  const used = new Set([...taken].map((n) => n.toLowerCase()));
  const out: string[] = [];
  parts.forEach((p, i) => {
    if (!p.keep) return;
    const base = fileName(i + 1, p.title, composer);
    let name = base;
    for (let k = 2; used.has(name.toLowerCase()); k++) name = base.replace(/\.pdf$/, ` (${k}).pdf`);
    used.add(name.toLowerCase());
    out.push(name);
  });
  return out;
}

export const stemOf = (pdfName: string): string => pdfName.replace(/\.pdf$/i, "");

/** The folder the parts go in, inside the library's inbox/. */
export const splitFolder = (pdfName: string): string => `${sanitize(stemOf(pdfName))} (split)`;

/** A bookmark in the PDF (its outline): a title and the page it points at. */
export interface Bookmark {
  title: string;
  page: number;
}

/**
 * Starts suggested by the PDF's own bookmarks, when it has at least two pointing at different pages (an anthology
 * with a table of contents). Titles come along for the parts.
 */
export function fromBookmarks(marks: Bookmark[], pages: number): { starts: number[]; titles: Map<number, string> } | null {
  const titles = new Map<number, string>();
  for (const m of marks) if (m.page >= 1 && m.page <= pages && !titles.has(m.page)) titles.set(m.page, m.title.trim());
  if (titles.size < 2) return null;
  if (!titles.has(1)) titles.set(1, "");
  return { starts: normalizeStarts(titles.keys(), pages), titles };
}

export const pageRange = (p: Part): string => (p.start === p.end ? `p. ${p.start}` : `p. ${p.start}–${p.end}`);
