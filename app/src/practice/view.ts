/**
 * How the score is shown in Practice: transposed and with a different clef.
 *
 * Both are changes to a copy of the MusicXML, made before the score is read and drawn. So everything that reads
 * notes from it (the drawing, playback, wait mode and the check of a recording) sees the same transposed pitches,
 * and you are judged against the notes you see. A clef change moves no pitch at all, only how notes are drawn.
 */

export type ClefChoice = "written" | "bass" | "tenor" | "alto" | "treble";

export interface ScoreView {
  /** Semitones up (+) or down (-), all shown parts together. */
  transpose: number;
  /** The clef for the practised part, or "written" to keep the score's own clefs (with its clef changes). */
  clef: ClefChoice;
}

export const PLAIN_VIEW: ScoreView = { transpose: 0, clef: "written" };
export const MAX_TRANSPOSE = 12;

const CLEFS: Record<Exclude<ClefChoice, "written">, [string, number]> = {
  bass: ["F", 4],
  tenor: ["C", 4],
  alto: ["C", 3],
  treble: ["G", 2],
};

export const CLEF_LABELS: Record<ClefChoice, string> = {
  written: "As written",
  bass: "Bass",
  tenor: "Tenor",
  alto: "Alto",
  treble: "Treble",
};

const INTERVALS = ["", "a half step", "a whole step", "a minor third", "a major third", "a fourth", "a tritone", "a fifth", "a minor sixth", "a major sixth", "a minor seventh", "a major seventh", "an octave"];

/** "Up a whole step (+2)" and so on, for the Transpose menu. */
export function transposeLabel(semis: number): string {
  if (!semis) return "As written";
  return `${semis > 0 ? "Up" : "Down"} ${INTERVALS[Math.abs(semis)]} (${semis > 0 ? "+" : ""}${semis})`;
}

export const isPlain = (v: ScoreView): boolean => v.transpose === 0 && v.clef === "written";

/** A saved view, cleaned up (an old or hand-edited value can't break opening a score). */
export function cleanView(v: Partial<ScoreView> | null | undefined): ScoreView {
  const t = Math.round(Number(v?.transpose) || 0);
  return {
    transpose: Math.max(-MAX_TRANSPOSE, Math.min(MAX_TRANSPOSE, t)),
    clef: v?.clef && v.clef in CLEF_LABELS ? v.clef : "written",
  };
}

// ---- spelling: transposing by an interval on the line of fifths keeps notes spelled for the new key ----

const STEPS = ["C", "D", "E", "F", "G", "A", "B"];
const STEP_SEMI: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const FIFTHS_ORDER = ["F", "C", "G", "D", "A", "E", "B"]; // F is -1 on the line of fifths, C 0, G 1 …

/** Position on the line of fifths: C 0, G 1, F -1, F# 6, Bb -2. */
function tpc(step: string, alter: number): number {
  return FIFTHS_ORDER.indexOf(step) - 1 + 7 * alter;
}

function fromTpc(t: number): { step: string; alter: number } {
  const i = t + 1;
  return { step: FIFTHS_ORDER[((i % 7) + 7) % 7], alter: Math.floor(i / 7) };
}

/**
 * The interval to move by, as a number of fifths, for a part whose key signatures are `keys`: of the two ways
 * to spell it (C up a half step is C# or Db major), the one whose keys need fewer sharps or flats.
 */
export function fifthsFor(semis: number, keys: number[]): number {
  const a = (((7 * semis) % 12) + 12) % 12; // 0..11
  if (a === 0) return 0;
  const b = a - 12;
  const cost = (f: number) => Math.max(...(keys.length ? keys : [0]).map((k) => Math.abs(k + f)));
  const ca = cost(a);
  const cb = cost(b);
  return ca < cb ? a : cb < ca ? b : Math.abs(a) <= Math.abs(b) ? a : b;
}

/** A written note moved by `semis` semitones, spelled by moving `fifths` along the line of fifths. */
export function moveNote(step: string, alter: number, octave: number, semis: number, fifths: number): { step: string; alter: number; octave: number } {
  let { step: s, alter: a } = fromTpc(tpc(step, alter) + fifths);
  if (Math.abs(a) > 2) {
    // a triple sharp or flat: respell it as the plain note it sounds as
    const pc = (((STEP_SEMI[s] + a) % 12) + 12) % 12;
    s = STEPS.find((x) => STEP_SEMI[x] === pc) ?? STEPS.find((x) => STEP_SEMI[x] === pc - 1)!;
    a = pc - STEP_SEMI[s];
  }
  const midi = 12 * (octave + 1) + STEP_SEMI[step] + alter + semis;
  const o = Math.round((midi - STEP_SEMI[s] - a) / 12) - 1;
  return { step: s, alter: a, octave: o };
}

// ---- small XML helpers ----

const kids = (el: Element, tag: string): Element[] => Array.from(el.children).filter((c) => c.localName === tag);
const kid = (el: Element, tag: string): Element | null => Array.from(el.children).find((c) => c.localName === tag) ?? null;
const text = (el: Element | null): string => (el?.textContent ?? "").trim();

function setChild(doc: Document, parent: Element, tag: string, value: string | null, before?: string[]): void {
  let c = kid(parent, tag);
  if (value === null) {
    c?.remove();
    return;
  }
  if (!c) {
    c = doc.createElementNS(parent.namespaceURI, tag);
    const next = before?.map((t) => kid(parent, t)).find(Boolean) ?? null;
    parent.insertBefore(c, next);
  }
  c.textContent = value;
}

const ACCIDENTALS: Record<number, string> = { [-2]: "flat-flat", [-1]: "flat", 0: "natural", 1: "sharp", 2: "double-sharp" };

/** Moves one <pitch>, <root>-like or <bass>-like element whose children are named `${prefix}step` etc. */
function movePitchEl(doc: Document, el: Element, prefix: string, semis: number, fifths: number, octaves: boolean): { alter: number } {
  const step = text(kid(el, `${prefix}step`)).toUpperCase() || "C";
  const alter = Math.round(parseFloat(text(kid(el, `${prefix}alter`))) || 0);
  const octave = octaves ? Math.round(parseFloat(text(kid(el, "octave"))) || 4) : 4;
  const m = moveNote(step, alter, octave, semis, fifths);
  setChild(doc, el, `${prefix}step`, m.step);
  setChild(doc, el, `${prefix}alter`, m.alter ? String(m.alter) : null, octaves ? ["octave"] : []);
  if (octaves) setChild(doc, el, "octave", String(m.octave));
  return m;
}

/** Transposes one <part> in place by `semis` semitones. */
function transposePart(doc: Document, part: Element, semis: number): void {
  const measures = kids(part, "measure");
  const keys: number[] = [];
  for (const m of measures)
    for (const a of kids(m, "attributes"))
      for (const k of kids(a, "key")) {
        const f = kid(k, "fifths");
        if (f) keys.push(Math.round(parseFloat(text(f)) || 0));
      }
  const fifths = fifthsFor(semis, keys);
  for (const m of measures) {
    for (const el of Array.from(m.children)) {
      if (el.localName === "attributes") {
        for (const k of kids(el, "key")) {
          const f = kid(k, "fifths");
          if (f) f.textContent = String(Math.round(parseFloat(text(f)) || 0) + fifths);
        }
      } else if (el.localName === "note") {
        const p = kid(el, "pitch");
        if (p) {
          const { alter } = movePitchEl(doc, p, "", semis, fifths, true);
          const acc = kid(el, "accidental");
          if (acc && !acc.hasAttribute("cautionary") && ACCIDENTALS[alter]) acc.textContent = ACCIDENTALS[alter];
        }
        const rest = kid(el, "rest");
        const dOct = rest && kid(rest, "display-octave");
        if (dOct && Math.abs(semis) === 12) dOct.textContent = String(Math.round(parseFloat(text(dOct)) || 4) + Math.sign(semis));
      } else if (el.localName === "harmony") {
        for (const r of kids(el, "root")) movePitchEl(doc, r, "root-", semis, fifths, false);
        for (const b of kids(el, "bass")) movePitchEl(doc, b, "bass-", semis, fifths, false);
      }
    }
  }
}

// attributes children in schema order, after which a new <clef> must go
const AFTER_CLEF = ["staff-details", "transpose", "for-part", "directive", "measure-style"];

/** Gives `part` one clef throughout (staff 1 of a part with several staves), in place. */
function setPartClef(doc: Document, part: Element, clef: Exclude<ClefChoice, "written">): void {
  const [sign, line] = CLEFS[clef];
  const onStaff1 = (c: Element) => !c.hasAttribute("number") || c.getAttribute("number") === "1";
  const fill = (c: Element) => {
    for (const ch of Array.from(c.children)) ch.remove();
    for (const [tag, v] of [["sign", sign], ["line", String(line)]] as const) {
      const e = doc.createElementNS(c.namespaceURI, tag);
      e.textContent = v;
      c.appendChild(e);
    }
  };
  const measures = kids(part, "measure");
  let found = false;
  for (const m of measures)
    for (const a of kids(m, "attributes"))
      for (const c of kids(a, "clef"))
        if (onStaff1(c)) {
          fill(c);
          found = true;
        }
  if (found || !measures.length) return;
  // no clef in the file means treble: add one at the start
  const first = measures[0];
  let attrs = kid(first, "attributes");
  if (!attrs) {
    attrs = doc.createElementNS(first.namespaceURI, "attributes");
    first.insertBefore(attrs, first.firstElementChild);
  }
  const c = doc.createElementNS(attrs.namespaceURI, "clef");
  fill(c);
  attrs.insertBefore(c, AFTER_CLEF.map((t) => kid(attrs!, t)).find(Boolean) ?? null);
}

/**
 * Applies a view to `doc` in place: transposes the parts in `parts` (all shown parts move together, so they
 * still fit each other) and sets the clef of `practise`.
 */
export function applyView(doc: Document, view: ScoreView, parts: string[], practise: string): void {
  const keep = new Set(parts);
  for (const p of kids(doc.documentElement, "part")) {
    const id = p.getAttribute("id") ?? "";
    if (!keep.has(id)) continue;
    if (view.transpose) transposePart(doc, p, view.transpose);
    if (id === practise && view.clef !== "written") setPartClef(doc, p, view.clef);
  }
}
