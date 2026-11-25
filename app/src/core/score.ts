/**
 * Read one part of a MusicXML score into a flat list of notes with times.
 *
 * Shared by every feature of the app; features may import core, never each other.
 * Each note keeps its XML elements so results can be written back into a copy of
 * the score (for example colors). Mirrors lento_core/score.py.
 */
import { unzipSync, strFromU8 } from "fflate";

const STEP: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
export const DEFAULT_TEMPO = 90;
const CELLO = /\b(cello|violoncello|vc|vlc|celli)\b/i;
const BEAT_UNITS: Record<string, number> = { whole: 4, half: 2, quarter: 1, eighth: 0.5, "16th": 0.25 };

export function midiName(midi: number): string {
  const m = Math.round(midi);
  return `${NOTE_NAMES[((m % 12) + 12) % 12]}${Math.floor(m / 12) - 1}`;
}

export interface ScoreNote {
  index: number;
  midi: number;
  name: string;
  measure: string; // printed measure number
  measureIndex: number; // 0-based
  beat: number; // quarter notes from the start of the part
  beatInMeasure: number;
  duration: number; // quarter notes, ties merged
  startSec: number;
  durationSec: number;
  inChord: boolean; // part of a double stop
  voice: string;
  elements: Element[];
}

export interface PartInfo {
  id: string;
  name: string;
}

export interface Score {
  title: string;
  partId: string;
  partName: string;
  parts: PartInfo[];
  notes: ScoreNote[];
  tempos: [number, number][]; // [beat, quarter notes per minute]
  timeSignature: [number, number];
  measures: string[];
  measureStarts: number[];
  totalBeats: number;
  doc: Document;
  warnings: string[];
  secondsAt(beat: number): number;
  measureRange(first: string, last: string): [number, number];
}

function num(text: string | null | undefined, fallback = 0): number {
  const v = parseFloat((text ?? "").trim());
  return Number.isFinite(v) ? v : fallback;
}

function childText(el: Element, path: string): string | null {
  let cur: Element | null = el;
  for (const tag of path.split("/")) {
    if (!cur) return null;
    cur = Array.from(cur.children).find((c) => c.localName === tag) ?? null;
  }
  return cur ? cur.textContent : null;
}

function child(el: Element, tag: string): Element | null {
  return Array.from(el.children).find((c) => c.localName === tag) ?? null;
}

function children(el: Element, tag: string): Element[] {
  return Array.from(el.children).filter((c) => c.localName === tag);
}

/** Read a .musicxml/.xml file's text or a compressed .mxl file's bytes into XML text. */
export function scoreText(name: string, data: ArrayBuffer): string {
  const bytes = new Uint8Array(data);
  const isZip = bytes[0] === 0x50 && bytes[1] === 0x4b;
  if (!isZip) return new TextDecoder().decode(bytes);
  const files = unzipSync(bytes);
  let target: string | undefined;
  const container = files["META-INF/container.xml"];
  if (container) {
    const m = /full-path="([^"]+)"/.exec(strFromU8(container));
    if (m) target = m[1];
  }
  target ??= Object.keys(files).find((n) => /\.(xml|musicxml)$/i.test(n) && !n.startsWith("META-INF"));
  if (!target || !files[target]) throw new Error(`${name}: no score found inside the .mxl file`);
  return strFromU8(files[target]);
}

export function listParts(doc: Document): PartInfo[] {
  const names = new Map<string, string>();
  for (const sp of Array.from(doc.getElementsByTagName("score-part"))) {
    const id = sp.getAttribute("id") ?? "";
    names.set(id, (childText(sp, "part-name") || childText(sp, "score-instrument/instrument-name") || id).trim());
  }
  return children(doc.documentElement, "part").map((p) => {
    const id = p.getAttribute("id") ?? "";
    return { id, name: names.get(id) ?? id };
  });
}

/**
 * Parse one part. `part` is a part id or part of its name; without it the first
 * part named like a cello is used, else the first part.
 */
export function parseScore(xml: string, part?: string, fallbackTitle = "Untitled"): Score {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const root = doc.documentElement;
  if (!root || root.localName === "parsererror" || doc.getElementsByTagName("parsererror").length) {
    throw new Error("this file is not valid MusicXML");
  }
  if (root.localName === "score-timewise") throw new Error("timewise MusicXML is not supported; export as partwise");
  if (root.localName !== "score-partwise") throw new Error("this file is not a MusicXML score");

  const title = (childText(root, "work/work-title") || childText(root, "movement-title") || fallbackTitle).trim();
  const parts = listParts(doc);
  if (!parts.length) throw new Error("the score has no parts");
  let chosen: PartInfo | undefined;
  if (part) {
    chosen = parts.find((p) => p.id === part || p.name.toLowerCase().includes(part.toLowerCase()));
    if (!chosen) throw new Error(`no part matches "${part}"; parts are: ${parts.map((p) => p.name).join(", ")}`);
  } else {
    chosen = parts.find((p) => CELLO.test(p.name)) ?? parts[0];
  }
  const partEl = children(root, "part").find((p) => (p.getAttribute("id") ?? "") === chosen!.id)!;

  const warnings: string[] = [];
  const notes: ScoreNote[] = [];
  const tempos: [number, number][] = [];
  const measures: string[] = [];
  const measureStarts: number[] = [];
  let timeSignature: [number, number] = [4, 4];
  let divisions = 1;
  let transpose = 0;
  let cursor = 0;
  const openTies = new Map<string, ScoreNote>();
  let sawRepeat = false;

  children(partEl, "measure").forEach((mEl, mIdx) => {
    const mNum = mEl.getAttribute("number") ?? String(mIdx + 1);
    measures.push(mNum);
    measureStarts.push(cursor);
    let pos = cursor;
    let furthest = cursor;
    let lastOnset = cursor;
    for (const el of Array.from(mEl.children)) {
      const tag = el.localName;
      if (tag === "attributes") {
        const d = num(childText(el, "divisions"), 0);
        if (d > 0) divisions = d;
        const tr = child(el, "transpose");
        if (tr) transpose = Math.round(num(childText(tr, "chromatic"))) + 12 * Math.round(num(childText(tr, "octave-change")));
        const time = child(el, "time");
        if (time && childText(time, "beats")) {
          timeSignature = [Math.round(num(childText(time, "beats"), 4)) || 4, Math.round(num(childText(time, "beat-type"), 4)) || 4];
        }
      } else if (tag === "direction") {
        const snd = child(el, "sound");
        if (snd?.hasAttribute("tempo")) {
          tempos.push([pos, num(snd.getAttribute("tempo"), DEFAULT_TEMPO)]);
        } else {
          const dt = child(el, "direction-type");
          const met = dt ? child(dt, "metronome") : null;
          const perMinute = met ? childText(met, "per-minute") : null;
          if (met && perMinute) {
            let unit = BEAT_UNITS[(childText(met, "beat-unit") ?? "quarter").trim()] ?? 1;
            if (child(met, "beat-unit-dot")) unit *= 1.5;
            const bpm = num(perMinute.replace(/[^0-9.]/g, ""));
            if (bpm > 0) tempos.push([pos, bpm * unit]);
          }
        }
      } else if (tag === "sound" && el.hasAttribute("tempo")) {
        tempos.push([pos, num(el.getAttribute("tempo"), DEFAULT_TEMPO)]);
      } else if (tag === "barline" && child(el, "repeat")) {
        sawRepeat = true;
      } else if (tag === "backup") {
        pos -= num(childText(el, "duration")) / divisions;
      } else if (tag === "forward") {
        pos += num(childText(el, "duration")) / divisions;
        furthest = Math.max(furthest, pos);
      } else if (tag === "note") {
        if (child(el, "grace") || child(el, "cue")) continue;
        const dur = num(childText(el, "duration")) / divisions;
        const chord = !!child(el, "chord");
        const onset = chord ? lastOnset : pos;
        if (!chord) {
          lastOnset = pos;
          pos += dur;
          furthest = Math.max(furthest, pos);
        }
        const pitch = child(el, "pitch");
        if (child(el, "rest") || !pitch) continue;
        const midi =
          12 * (Math.round(num(childText(pitch, "octave"), 4)) + 1) +
          (STEP[(childText(pitch, "step") ?? "C").trim().toUpperCase()] ?? 0) +
          Math.round(num(childText(pitch, "alter"))) +
          transpose;
        const voice = (childText(el, "voice") ?? "1").trim();
        const tieTypes = new Set(children(el, "tie").map((t) => t.getAttribute("type")));
        const key = `${voice}:${midi}`;
        const held = openTies.get(key);
        if (tieTypes.has("stop") && held) {
          held.duration = onset + dur - held.beat;
          held.elements.push(el);
          if (!tieTypes.has("start")) openTies.delete(key);
          continue;
        }
        const note: ScoreNote = {
          index: notes.length,
          midi,
          name: midiName(midi),
          measure: mNum,
          measureIndex: mIdx,
          beat: onset,
          beatInMeasure: onset - cursor,
          duration: dur,
          startSec: 0,
          durationSec: 0,
          inChord: chord,
          voice,
          elements: [el],
        };
        notes.push(note);
        if (tieTypes.has("start")) openTies.set(key, note);
      }
    }
    if (furthest > cursor) cursor = furthest;
  });

  if (sawRepeat) warnings.push("The score has repeat signs. Notes are read once, as written; play repeats only once.");
  if (!tempos.length || tempos[0][0] > 0) {
    tempos.unshift([0, tempos.length ? tempos[0][1] : DEFAULT_TEMPO]);
    if (tempos.length === 1) warnings.push(`No tempo marking found; assuming ${DEFAULT_TEMPO} quarter notes per minute.`);
  }
  tempos.sort((a, b) => a[0] - b[0]);

  const byOnset = new Map<string, ScoreNote[]>();
  for (const n of notes) {
    const k = n.beat.toFixed(6);
    byOnset.set(k, [...(byOnset.get(k) ?? []), n]);
  }
  for (const group of byOnset.values()) if (group.length > 1) group.forEach((n) => (n.inChord = true));
  notes.sort((a, b) => a.beat - b.beat || b.midi - a.midi);
  notes.forEach((n, i) => (n.index = i));

  const secondsAt = (beat: number): number => {
    let secs = 0;
    let lastBeat = 0;
    let bpm = tempos[0][1];
    for (const [tb, tbpm] of tempos.slice(1)) {
      if (tb >= beat) break;
      secs += ((tb - lastBeat) * 60) / bpm;
      lastBeat = tb;
      bpm = tbpm;
    }
    return secs + ((beat - lastBeat) * 60) / bpm;
  };
  for (const n of notes) {
    n.startSec = secondsAt(n.beat);
    n.durationSec = secondsAt(n.beat + n.duration) - n.startSec;
  }

  return {
    title,
    partId: chosen.id,
    partName: chosen.name,
    parts,
    notes,
    tempos,
    timeSignature,
    measures,
    measureStarts,
    totalBeats: cursor,
    doc,
    warnings,
    secondsAt,
    measureRange(first: string, last: string): [number, number] {
      const a = measures.indexOf(first);
      const b = measures.lastIndexOf(last);
      if (a < 0) throw new Error(`measure ${first} is not in the score`);
      if (b < 0) throw new Error(`measure ${last} is not in the score`);
      return [a, b];
    },
  };
}

/**
 * The score as MusicXML with only one part kept. The sheet renderer gets this instead of the whole file:
 * loading and drawing all 19 parts of an orchestral score took minutes on a phone.
 */
export function partXml(doc: Document, partId: string): string {
  const root = doc.documentElement;
  const out = new XMLSerializer();
  let body = "";
  for (const child of Array.from(root.children)) {
    if (child.localName === "part" && child.getAttribute("id") !== partId) continue;
    if (child.localName === "part-list") {
      const list = child.cloneNode(false) as Element;
      for (const item of Array.from(child.children))
        if (item.localName === "score-part" && item.getAttribute("id") === partId) list.appendChild(item.cloneNode(true));
      body += out.serializeToString(list);
    } else body += out.serializeToString(child);
  }
  const attrs = Array.from(root.attributes).map((a) => ` ${a.name}="${a.value.replace(/"/g, "&quot;")}"`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?><${root.localName}${attrs}>${body}</${root.localName}>`;
}
