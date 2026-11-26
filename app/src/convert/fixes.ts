/**
 * Quick fixes for a converted score, made in the Review window: the instrument of a part, the clef of a staff, the
 * key and the time signature, each from a given measure on. They change the MusicXML document in place.
 *
 * A misread clef also misreads every note on that staff, since the converter works out pitches from the clef it
 * saw. So changing a clef can move the notes with it: each note stays on its line or space and is renamed for the
 * new clef, with sharps and flats worked out again from the key signature and the accidentals printed beside it.
 */

export type Clef = "G2" | "F4" | "C3" | "C4" | "G2-8";

export const CLEFS: { id: Clef; name: string }[] = [
  { id: "F4", name: "Bass" },
  { id: "C4", name: "Tenor" },
  { id: "C3", name: "Alto" },
  { id: "G2", name: "Treble" },
  { id: "G2-8", name: "Treble, octave lower" },
];

/** MIDI program (1-based) and MusicXML instrument-sound for the instruments a part can be set to. */
export const INSTRUMENTS: { name: string; program: number; sound: string }[] = [
  { name: "Cello", program: 43, sound: "strings.cello" },
  { name: "Viola", program: 42, sound: "strings.viola" },
  { name: "Violin", program: 41, sound: "strings.violin" },
  { name: "Double Bass", program: 44, sound: "strings.contrabass" },
  { name: "Piano", program: 1, sound: "keyboard.piano" },
  { name: "Voice", program: 54, sound: "voice" },
];

const STEPS = ["C", "D", "E", "F", "G", "A", "B"];
const SHARPS = ["F", "C", "G", "D", "A", "E", "B"]; // the order sharps are added to a key; flats go the other way
const ACCIDENTALS: Record<string, number> = { sharp: 1, flat: -1, natural: 0, "double-sharp": 2, "sharp-sharp": 2, "flat-flat": -2 };

export interface Staff {
  part: string; // part id
  name: string; // part name
  staff: number; // 1 for the top (or only) staff of the part
  staves: number; // how many staves the part has
  clef: Clef | string; // the first clef, as sign + line ("G2"), with "-8" for an octave lower
}

const kids = (el: Element, name: string) => Array.from(el.children).filter((c) => c.localName === name);
const kid = (el: Element, name: string) => Array.from(el.children).find((c) => c.localName === name) ?? null;
const text = (el: Element | null, name: string) => (el ? kid(el, name)?.textContent?.trim() ?? "" : "");

function parts(doc: Document): Element[] {
  return kids(doc.documentElement, "part");
}

function scoreParts(doc: Document): Element[] {
  const list = kid(doc.documentElement, "part-list");
  return list ? kids(list, "score-part") : [];
}

function clefId(clef: Element): string {
  const octave = Number(text(clef, "clef-octave-change") || 0);
  return `${text(clef, "sign")}${text(clef, "line")}${octave === -1 ? "-8" : octave === 1 ? "+8" : ""}`;
}

function clefNumber(clef: Element): number {
  return Number(clef.getAttribute("number") || 1);
}

/** The staves of the score, top to bottom. */
export function staves(doc: Document): Staff[] {
  const names = new Map(scoreParts(doc).map((p) => [p.getAttribute("id") ?? "", text(p, "part-name")]));
  const out: Staff[] = [];
  for (const part of parts(doc)) {
    const id = part.getAttribute("id") ?? "";
    let count = 1;
    const first = new Map<number, string>();
    for (const m of kids(part, "measure"))
      for (const a of kids(m, "attributes")) {
        const n = Number(text(a, "staves") || 0);
        if (n > count) count = n;
        for (const c of kids(a, "clef")) if (!first.has(clefNumber(c))) first.set(clefNumber(c), clefId(c));
      }
    for (let s = 1; s <= count; s++) out.push({ part: id, name: names.get(id) || id, staff: s, staves: count, clef: first.get(s) ?? "G2" });
  }
  return out;
}

export function measureCount(doc: Document): number {
  const p = parts(doc)[0];
  return p ? kids(p, "measure").length : 0;
}

/** The printed number of the measure at this position (1-based), for showing. */
export function measureNumber(doc: Document, at: number): string {
  const m = kids(parts(doc)[0] ?? doc.documentElement, "measure")[at - 1];
  return m?.getAttribute("number") || String(at);
}

/** Things worth a look before approving, such as a cello part that starts in treble clef. */
export function warnings(doc: Document): string[] {
  const out: string[] = [];
  for (const s of staves(doc)) {
    if (s.name === "Voice") out.push(`"${s.name}" is what the converter calls a one-staff part it can't name. Set the instrument if it's your cello part.`);
    if (/cello|voice/i.test(s.name) && s.staves === 1 && s.clef.startsWith("G"))
      out.push(`${s.name} starts in treble clef. If the PDF shows bass or tenor clef, change the clef below (the notes move with it).`);
  }
  return out;
}

/** Renames a part and sets the sound it plays with. */
export function setInstrument(doc: Document, partId: string, name: string): void {
  const sp = scoreParts(doc).find((p) => p.getAttribute("id") === partId);
  if (!sp) throw new Error(`There is no part ${partId}.`);
  const known = INSTRUMENTS.find((i) => i.name.toLowerCase() === name.toLowerCase());
  const set = (parent: Element, tag: string, value: string, before?: string) => {
    let el = kid(parent, tag);
    if (!el) {
      el = doc.createElementNS(parent.namespaceURI, tag);
      const ref = before ? kid(parent, before) : null;
      parent.insertBefore(el, ref ? ref.nextSibling : parent.firstChild);
    }
    el.textContent = value;
  };
  set(sp, "part-name", name);
  kid(sp, "part-abbreviation")?.remove(); // homr's or a wrong one; MusicXML viewers fall back to the name
  for (const si of kids(sp, "score-instrument")) {
    set(si, "instrument-name", name);
    if (known) set(si, "instrument-sound", known.sound, "instrument-name");
  }
  if (known) for (const mi of kids(sp, "midi-instrument")) kid(mi, "midi-program") && set(mi, "midi-program", String(known.program));
}

// ---- pitch ----

function clefBottomLine(clef: string): number {
  // the diatonic number (C0 = 0) of the bottom line of the staff
  const sign = clef[0];
  const line = Number(clef[1]);
  const octave = clef.endsWith("-8") ? -7 : clef.endsWith("+8") ? 7 : 0;
  const ref = sign === "G" ? 4 * 7 + 4 : sign === "F" ? 3 * 7 + 3 : 4 * 7; // G4, F3, middle C
  return ref - 2 * (line - 1) + octave;
}

function keyAlter(fifths: number, step: string): number {
  if (fifths > 0) return SHARPS.slice(0, fifths).includes(step) ? 1 : 0;
  if (fifths < 0) return [...SHARPS].reverse().slice(0, -fifths).includes(step) ? -1 : 0;
  return 0;
}

/** Each measure of a part with the key in force there (fifths), position by position. */
function keys(part: Element): number[] {
  let fifths = 0;
  return kids(part, "measure").map((m) => {
    for (const a of kids(m, "attributes")) {
      const k = kid(a, "key");
      if (k && kid(k, "fifths")) fifths = Number(text(k, "fifths"));
    }
    return fifths;
  });
}

function noteStaff(note: Element): number {
  return Number(text(note, "staff") || 1);
}

/**
 * Moves the notes of one staff by `shift` lines and spaces in measures from..to (positions, inclusive), and works
 * out each note's sharp or flat again: its printed accidental, else one earlier in the measure, else the key.
 * With shift 0 it only does the second part (after a key change).
 */
function respell(part: Element, staff: number | null, from: number, to: number, shift: number): void {
  const measures = kids(part, "measure");
  const fifths = keys(part);
  for (let i = from - 1; i < to && i < measures.length; i++) {
    const carried = new Map<string, number>(); // step+octave -> alter set by an accidental earlier in the measure
    for (const note of kids(measures[i], "note")) {
      if (staff != null && noteStaff(note) !== staff) continue;
      const pitch = kid(note, "pitch");
      if (!pitch) continue;
      const d = STEPS.indexOf(text(pitch, "step")) + 7 * Number(text(pitch, "octave")) + shift;
      const step = STEPS[((d % 7) + 7) % 7];
      const octave = Math.floor(d / 7);
      const where = `${step}${octave}`;
      const printed = text(note, "accidental");
      let alter: number;
      if (printed in ACCIDENTALS) {
        alter = ACCIDENTALS[printed];
        carried.set(where, alter);
      } else alter = carried.get(where) ?? keyAlter(fifths[i], step);
      kid(pitch, "step")!.textContent = step;
      kid(pitch, "octave")!.textContent = String(octave);
      let alt = kid(pitch, "alter");
      if (alter === 0) alt?.remove();
      else {
        if (!alt) {
          alt = pitch.ownerDocument.createElementNS(pitch.namespaceURI, "alter");
          pitch.insertBefore(alt, kid(pitch, "octave"));
        }
        alt.textContent = String(alter);
      }
    }
  }
}

// ---- attributes ----

const ORDER = ["footnote", "level", "divisions", "key", "time", "staves", "part-symbol", "instruments", "clef", "staff-details", "transpose", "directive", "measure-style"];

/** The attributes at the start of the measure (before its first note), made after any <print> if there are none. */
function attributes(measure: Element): Element {
  for (const c of Array.from(measure.children)) {
    if (c.localName === "attributes") return c;
    if (c.localName === "note" || c.localName === "backup" || c.localName === "forward") break;
  }
  const a = measure.ownerDocument.createElementNS(measure.namespaceURI, "attributes");
  measure.insertBefore(a, Array.from(measure.children).find((c) => c.localName !== "print") ?? null);
  return a;
}

/** Puts `el` into attributes in the order MusicXML requires. */
function place(attrs: Element, el: Element): void {
  const rank = ORDER.indexOf(el.localName);
  const after = Array.from(attrs.children).find((c) => ORDER.indexOf(c.localName) > rank);
  attrs.insertBefore(el, after ?? null);
}

function makeClef(doc: Document, ns: string | null, clef: Clef, staff: number, staves: number): Element {
  const el = doc.createElementNS(ns, "clef");
  if (staves > 1) el.setAttribute("number", String(staff));
  const sign = doc.createElementNS(ns, "sign");
  sign.textContent = clef[0];
  const line = doc.createElementNS(ns, "line");
  line.textContent = clef[1];
  el.append(sign, line);
  if (clef.endsWith("-8")) {
    const oct = doc.createElementNS(ns, "clef-octave-change");
    oct.textContent = "-1";
    el.append(oct);
  }
  return el;
}

/** The clef of a staff in force at each measure position. */
function clefs(part: Element, staff: number): string[] {
  let clef = "G2";
  return kids(part, "measure").map((m) => {
    for (const a of kids(m, "attributes")) for (const c of kids(a, "clef")) if (clefNumber(c) === staff) clef = clefId(c);
    return clef;
  });
}

/**
 * Sets the clef of a staff from measure `from` (a position, 1-based) up to where the original score changes to a
 * different clef. With `moveNotes`, the notes keep their place on the staff and are renamed for the new clef.
 * Returns the last measure position changed.
 */
export function setClef(doc: Document, partId: string, staff: number, from: number, clef: Clef, moveNotes = true): number {
  const part = parts(doc).find((p) => p.getAttribute("id") === partId);
  if (!part) throw new Error(`There is no part ${partId}.`);
  const measures = kids(part, "measure");
  if (from < 1 || from > measures.length) throw new Error(`Measure ${from} is not in this score.`);
  const before = clefs(part, staff);
  const old = before[from - 1];
  let to = from;
  while (to < measures.length && before[to] === old) to++; // positions from..to keep the old clef
  const count = Math.max(...staves(doc).filter((s) => s.part === partId).map((s) => s.staves));
  for (let i = from - 1; i < to; i++)
    for (const a of kids(measures[i], "attributes")) for (const c of kids(a, "clef")) if (clefNumber(c) === staff) c.remove();
  place(attributes(measures[from - 1]), makeClef(doc, part.namespaceURI, clef, staff, count));
  if (moveNotes) respell(part, staff, from, to, clefBottomLine(clef) - clefBottomLine(old));
  return to;
}

/** Fifths in force at each measure position, from the first part (all parts share the key here). */
function keyRun(doc: Document, from: number): number {
  const ks = keys(parts(doc)[0]);
  let to = from;
  while (to < ks.length && ks[to] === ks[from - 1]) to++;
  return to;
}

/** Sets the key (in fifths, -7 to 7) of every part from measure `from` to where the score next changes key. */
export function setKey(doc: Document, from: number, fifths: number): number {
  const to = keyRun(doc, from);
  for (const part of parts(doc)) {
    const measures = kids(part, "measure");
    for (let i = from - 1; i < to; i++) for (const a of kids(measures[i] ?? part, "attributes")) for (const k of kids(a, "key")) k.remove();
    const k = doc.createElementNS(part.namespaceURI, "key");
    const f = doc.createElementNS(part.namespaceURI, "fifths");
    f.textContent = String(fifths);
    k.append(f);
    if (measures[from - 1]) place(attributes(measures[from - 1]), k);
    respell(part, null, from, to, 0);
  }
  return to;
}

/** Sets the time signature of every part from measure `from` to where the score next changes it. Notes don't move. */
export function setTime(doc: Document, from: number, beats: number, beatType: number): number {
  const first = kids(parts(doc)[0], "measure");
  let sig = "";
  const sigs = first.map((m) => {
    for (const a of kids(m, "attributes")) {
      const t = kid(a, "time");
      if (t) sig = `${text(t, "beats")}/${text(t, "beat-type")}`;
    }
    return sig;
  });
  let to = from;
  while (to < sigs.length && sigs[to] === sigs[from - 1]) to++;
  for (const part of parts(doc)) {
    const measures = kids(part, "measure");
    for (let i = from - 1; i < to; i++) for (const a of kids(measures[i] ?? part, "attributes")) for (const t of kids(a, "time")) t.remove();
    const t = doc.createElementNS(part.namespaceURI, "time");
    const b = doc.createElementNS(part.namespaceURI, "beats");
    b.textContent = String(beats);
    const bt = doc.createElementNS(part.namespaceURI, "beat-type");
    bt.textContent = String(beatType);
    t.append(b, bt);
    if (measures[from - 1]) place(attributes(measures[from - 1]), t);
  }
  return to;
}

export const KEYS: { fifths: number; name: string }[] = [
  [-7, "C♭ major / A♭ minor"], [-6, "G♭ major / E♭ minor"], [-5, "D♭ major / B♭ minor"], [-4, "A♭ major / F minor"],
  [-3, "E♭ major / C minor"], [-2, "B♭ major / G minor"], [-1, "F major / D minor"], [0, "C major / A minor"],
  [1, "G major / E minor"], [2, "D major / B minor"], [3, "A major / F♯ minor"], [4, "E major / C♯ minor"],
  [5, "B major / G♯ minor"], [6, "F♯ major / D♯ minor"], [7, "C♯ major / A♯ minor"],
].map(([fifths, name]) => ({ fifths: fifths as number, name: name as string }));

export function serialize(doc: Document): string {
  const body = new XMLSerializer().serializeToString(doc);
  return body.startsWith("<?xml") ? body : `<?xml version="1.0" encoding="UTF-8"?>\n${body}`;
}
