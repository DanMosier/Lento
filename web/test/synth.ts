/** Synthetic cello score and takes for the analyzer tests. Mirrors tests/practice_synth.py. */
import type { Score } from "../src/core/score";

export const SR = 22050;
type N = [string, number, number, number, string];
const MEASURES: N[][] = [
  [["D", 0, 3, 1, ""], ["E", 0, 3, 1, ""], ["F", 1, 3, 1, ""], ["G", 0, 3, 1, ""]],
  [["A", 0, 3, 1, ""], ["A", 0, 3, 0.5, ""], ["A", 0, 3, 0.5, ""], ["B", 0, 3, 1, ""], ["C", 1, 4, 1, ""]],
  [["D", 0, 4, 2, ""], ["", 0, 0, 1, "rest"], ["D", 0, 4, 1, ""]],
  [["D", 0, 3, 2, ""], ["A", 0, 3, 2, "chord"], ["G", 0, 2, 2, ""]],
  [["C", 0, 2, 1, ""], ["G", 0, 2, 1, ""], ["D", 0, 3, 1, ""], ["A", 0, 3, 1, ""]],
  [["E", 0, 4, 1, ""], ["E", 0, 4, 1, ""], ["F", 1, 4, 2, "tie-start"]],
  [["F", 1, 4, 2, "tie-stop"], ["", 0, 0, 2, "rest"]],
  [["B", 0, 3, 1, ""], ["C", 1, 4, 1, ""], ["D", 0, 4, 1, ""], ["E", 0, 4, 1, ""]],
  [["F", 1, 4, 1, ""], ["E", 0, 4, 1, ""], ["D", 0, 4, 2, ""]],
];
const TYPES: Record<number, string> = { 4: "whole", 2: "half", 1: "quarter", 0.5: "eighth" };

export function scoreXml(tempo = 80): string {
  const div = 2;
  const out = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<score-partwise version="4.0">',
    "<work><work-title>Test Etude</work-title></work>",
    '<part-list><score-part id="P1"><part-name>Piano</part-name></score-part><score-part id="P2"><part-name>Violoncello</part-name></score-part></part-list>',
    '<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes><note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure>' +
      Array.from({ length: 8 }, (_, i) => `<measure number="${i + 2}"><note><rest/><duration>4</duration><type>whole</type></note></measure>`).join("") +
      "</part>",
    '<part id="P2">',
  ];
  MEASURES.forEach((notes, i) => {
    out.push(`<measure number="${i + 1}">`);
    if (i === 0)
      out.push(
        `<attributes><divisions>${div}</divisions><key><fifths>2</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>` +
          `<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>${tempo}</per-minute></metronome></direction-type><sound tempo="${tempo}"/></direction>`,
      );
    for (const [step, alter, octave, q, extra] of notes) {
      const dur = q * div;
      if (extra === "rest") {
        out.push(`<note><rest/><duration>${dur}</duration><type>${TYPES[q]}</type></note>`);
        continue;
      }
      const chord = extra === "chord" ? "<chord/>" : "";
      const alt = alter ? `<alter>${alter}</alter>` : "";
      const tie = extra === "tie-start" ? '<tie type="start"/>' : extra === "tie-stop" ? '<tie type="stop"/>' : "";
      out.push(`<note>${chord}<pitch><step>${step}</step>${alt}<octave>${octave}</octave></pitch><duration>${dur}</duration>${tie}<voice>1</voice><type>${TYPES[q]}</type></note>`);
    }
    out.push("</measure>");
  });
  out.push("</part>", "</score-partwise>");
  return out.join("\n");
}

export interface Take {
  tempo?: number;
  detune?: Record<number, number>;
  skip?: number[];
  shiftMs?: Record<number, number>;
  overallCents?: number;
  firstMeasure?: number;
  lastMeasure?: number;
  slowDown?: number;
  reverb?: boolean;
  seed?: number;
}

function rng(seed: number) {
  let s = seed >>> 0;
  const uni = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = () => Math.sqrt(-2 * Math.log(uni() + 1e-12)) * Math.cos(2 * Math.PI * uni());
  return { uni, normal };
}

export function render(score: Score, take: Take = {}): Float32Array {
  const { tempo = 68, detune = {}, skip = [], shiftMs = {}, overallCents = 0, firstMeasure = 0, lastMeasure = 99, slowDown = 0, reverb = false, seed = 1 } = take;
  const r = rng(seed);
  const notes = score.notes.filter((n) => n.measureIndex >= firstMeasure && n.measureIndex <= lastMeasure);
  const startBeat = Math.min(...notes.map((n) => n.beat));
  const endBeat = Math.max(...notes.map((n) => n.beat + n.duration));
  const span = endBeat - startBeat;
  // time at beat, tempo falling linearly by slowDown
  const at = (beat: number) => {
    const steps = 400;
    const b = beat - startBeat;
    let t = 0;
    for (let i = 0; i < steps; i++) {
      const mid = ((i + 0.5) / steps) * b;
      t += (b / steps) * (60 / (tempo * (1 - (slowDown * mid) / span)));
    }
    return t;
  };
  const lead = 0.5;
  const y = new Float32Array(Math.floor((lead + at(endBeat) + 1.5) * SR));
  for (const n of notes) {
    if (skip.includes(n.index)) continue;
    const t0 = lead + at(n.beat) + (shiftMs[n.index] ?? 0) / 1000;
    // a late note still ends on time, as when a player comes in late
    const dur = at(n.beat + n.duration) - at(n.beat) - 0.03 - Math.max(0, (shiftMs[n.index] ?? 0) / 1000);
    const cents = overallCents + (detune[n.index] ?? 0);
    const freq = 440 * 2 ** ((n.midi - 69) / 12 + cents / 1200);
    const len = Math.floor(dur * SR);
    const vibPhase = r.uni() * 6.28;
    const phases = Array.from({ length: 12 }, () => r.uni() * 6.28);
    let phase = 0;
    const i0 = Math.floor(t0 * SR);
    const gain = n.inChord ? 0.6 : 1;
    for (let i = 0; i < len && i0 + i < y.length; i++) {
      const t = i / SR;
      const vib = Math.min(1, Math.max(0, (t - 0.15) / 0.2)) * 15 * Math.sin(2 * Math.PI * 5.5 * t + vibPhase);
      phase += (2 * Math.PI * freq * 2 ** (vib / 1200)) / SR;
      let s = 0;
      for (let k = 1; k <= 11 && freq * k < SR / 2 - 500; k++) s += Math.sin(k * phase + phases[k]) / k;
      const env = Math.min(1, t / 0.04, (dur - t) / 0.03);
      let v = s * env * gain;
      if (t < 0.03) v += r.normal() * 0.15;
      y[i0 + i] += v;
    }
  }
  if (reverb) {
    // three feedback combs: a cheap room
    const wet = new Float32Array(y.length);
    for (const [delay, fb] of [[1116, 0.84], [1356, 0.82], [1557, 0.8]] as const) {
      const buf = new Float32Array(y.length);
      for (let i = 0; i < y.length; i++) buf[i] = y[i] + (i >= delay ? fb * buf[i - delay] : 0);
      for (let i = 0; i < y.length; i++) wet[i] += buf[i];
    }
    let pw = 0;
    let py = 0;
    for (let i = 0; i < y.length; i++) [pw, py] = [Math.max(pw, Math.abs(wet[i])), Math.max(py, Math.abs(y[i]))];
    for (let i = 0; i < y.length; i++) y[i] += (0.3 * wet[i] * py) / (pw || 1);
  }
  let peak = 0;
  for (let i = 0; i < y.length; i++) {
    y[i] += r.normal() * 0.003;
    peak = Math.max(peak, Math.abs(y[i]));
  }
  for (let i = 0; i < y.length; i++) y[i] = (y[i] / peak) * 0.8;
  return y;
}
