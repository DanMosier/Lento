/**
 * "Flag for splitting": PDFs that hold several pieces, noted in the Review window as a reminder to run the PDF
 * splitter on them at the PC. Pure functions, so they are tested on their own.
 *
 * Each device keeps a copy and the library keeps one in Drive (lento-split.json beside library.json), merged entry
 * by entry with the newest change winning, the same way favorites and setlists are. Unflagging and "Done" are kept
 * as dated entries so they win over an older flag from another device.
 */

export type SplitState = "flagged" | "done" | "off";

export interface SplitEntry {
  piece: string; // piece id (its folder under pieces/)
  pdf: string; // the PDF's file name in that folder
  title: string; // shown in the list, so it reads well before the library index has loaded
  state: SplitState;
  flagged: number; // ms since 1970, when it was last flagged
  at: number; // ms since 1970, the last change (flag, done or unflag)
}

export interface SplitList {
  format: "lento-split";
  version: 1;
  entries: Record<string, SplitEntry>; // splitKey(piece, pdf) -> entry
}

export const SPLIT_FILE = "lento-split.json";
const STATES: SplitState[] = ["flagged", "done", "off"];

export const splitKey = (piece: string, pdf: string): string => `${piece}/${pdf}`;

export function emptySplit(): SplitList {
  return { format: "lento-split", version: 1, entries: {} };
}

/** Accepts anything (a saved copy, Drive's file) and keeps only what makes sense. */
export function parseSplit(raw: unknown): SplitList {
  const out = emptySplit();
  if (!raw || typeof raw !== "object") return out;
  for (const e of Object.values((raw as Partial<SplitList>).entries ?? {})) {
    if (!e || typeof e.piece !== "string" || typeof e.pdf !== "string" || typeof e.at !== "number" || !STATES.includes(e.state)) continue;
    out.entries[splitKey(e.piece, e.pdf)] = {
      piece: e.piece,
      pdf: e.pdf,
      title: typeof e.title === "string" && e.title ? e.title : e.piece,
      state: e.state,
      flagged: typeof e.flagged === "number" ? e.flagged : e.at,
      at: e.at,
    };
  }
  return out;
}

/** Both copies together: per PDF the newer change wins. */
export function mergeSplit(a: SplitList, b: SplitList): SplitList {
  const out = emptySplit();
  for (const k of new Set([...Object.keys(a.entries), ...Object.keys(b.entries)])) {
    const x = a.entries[k];
    const y = b.entries[k];
    out.entries[k] = !x ? y : !y ? x : y.at > x.at ? y : x;
  }
  return out;
}

export function sameSplit(a: SplitList, b: SplitList): boolean {
  const flat = (l: SplitList) => JSON.stringify(Object.keys(l.entries).sort().map((k) => [k, l.entries[k]]));
  return flat(a) === flat(b);
}

export function isFlagged(l: SplitList, piece: string, pdf: string): boolean {
  return l.entries[splitKey(piece, pdf)]?.state === "flagged";
}

/** Flags a PDF, marks it done, or takes the flag off. Always dated after the entry's last change. */
export function setSplit(l: SplitList, piece: string, pdf: string, title: string, state: SplitState, now = Date.now()): SplitList {
  const k = splitKey(piece, pdf);
  const old = l.entries[k];
  if (old?.state === state && (state !== "flagged" || old.title === title)) return l;
  const at = old ? Math.max(now, old.at + 1) : now;
  const e: SplitEntry = { piece, pdf, title: title || old?.title || piece, state, flagged: state === "flagged" ? at : (old?.flagged ?? at), at };
  return { ...l, entries: { ...l.entries, [k]: e } };
}

/** What's still to split, oldest flag first (the order they were noticed). */
export function flagged(l: SplitList): SplitEntry[] {
  return Object.values(l.entries)
    .filter((e) => e.state === "flagged")
    .sort((a, b) => a.flagged - b.flagged || a.title.localeCompare(b.title));
}

/** Recently marked done, newest first, so a mistaken "Done" can be undone. */
export function recentlyDone(l: SplitList, max = 5): SplitEntry[] {
  return Object.values(l.entries)
    .filter((e) => e.state === "done")
    .sort((a, b) => b.at - a.at)
    .slice(0, max);
}
