/**
 * Score marks: fingerings, bowings, string numbers, lifts, highlights and short notes that you add on top of a score.
 * They belong to notes (by measure, beat and pitch), not to places on the page, so they stay put at any zoom or
 * screen size, and they live in their own small file: the score itself is never changed.
 */
import type { Score, ScoreNote } from "../core/score";

export type MarkKind = "finger" | "string" | "down" | "up" | "lift" | "highlight" | "text";

export interface Mark {
  note: string; // noteKey()
  kind: MarkKind;
  value?: string; // finger 0-4, string I-IV, or the text
}

export interface MarkSet {
  format: "lento-marks";
  version: 1;
  score: string; // file name, for people reading the file
  updated: string; // ISO time of the last change, to pick the newer of two copies
  marks: Mark[];
}

/** The note's address: its part, measure index, beat within the measure, and pitch. */
export function noteKey(partId: string, n: ScoreNote): string {
  return `${partId}/${n.measureIndex}:${Math.round(n.beatInMeasure * 1000) / 1000}:${n.midi}`;
}

export function emptyMarks(score: string): MarkSet {
  return { format: "lento-marks", version: 1, score, updated: new Date(0).toISOString(), marks: [] };
}

/** Reads a marks file, or null if it isn't one. */
export function parseMarks(text: string): MarkSet | null {
  try {
    const m = JSON.parse(text) as MarkSet;
    return m?.format === "lento-marks" && Array.isArray(m.marks) ? m : null;
  } catch {
    return null;
  }
}

/** Only one of these per note: a new one replaces the old. Up and down bow replace each other. */
const ONE_PER_NOTE: MarkKind[][] = [["finger"], ["string"], ["down", "up"], ["lift"], ["highlight"], ["text"]];

/**
 * Adds a mark, or takes it off if the note already has exactly that mark (so tapping twice undoes).
 * Returns a new set; `now` stamps the change.
 */
export function toggleMark(set: MarkSet, mark: Mark, now = new Date()): MarkSet {
  const group = ONE_PER_NOTE.find((g) => g.includes(mark.kind))!;
  const same = set.marks.find((m) => m.note === mark.note && m.kind === mark.kind && (m.value ?? "") === (mark.value ?? ""));
  let marks = set.marks.filter((m) => !(m.note === mark.note && group.includes(m.kind)));
  if (!same && !(mark.kind === "text" && !mark.value?.trim())) marks = [...marks, mark];
  return { ...set, marks, updated: now.toISOString() };
}

/** Takes every mark off one note. */
export function clearNote(set: MarkSet, note: string, now = new Date()): MarkSet {
  return { ...set, marks: set.marks.filter((m) => m.note !== note), updated: now.toISOString() };
}

/** The newer of two copies (this device's and the library's). */
export function newer(a: MarkSet | null, b: MarkSet | null): MarkSet | null {
  if (!a) return b;
  if (!b) return a;
  return b.updated > a.updated ? b : a;
}

/** Marks whose note is in this score, so a mark for a note that no longer exists is simply not shown. */
export function marksIn(set: MarkSet, score: Score): Map<string, Mark[]> {
  const keys = new Set(score.notes.map((n) => noteKey(score.partId, n)));
  const out = new Map<string, Mark[]>();
  for (const m of set.marks) if (keys.has(m.note)) (out.get(m.note) ?? out.set(m.note, []).get(m.note)!).push(m);
  return out;
}

/** What a mark looks like on the score. */
export function glyph(m: Mark): string {
  switch (m.kind) {
    case "finger":
      return m.value ?? "";
    case "string":
      return m.value ?? "";
    case "down":
      return "⊓"; // ⊓
    case "up":
      return "V";
    case "lift":
      return "’"; // ’
    case "text":
      return m.value ?? "";
    default:
      return "";
  }
}

/** The order marks stack above a note, nearest first. */
export const STACK: MarkKind[] = ["finger", "string", "down", "up", "lift", "text"];
