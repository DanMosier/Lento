/** Turn an aligned recording into per-note feedback. Mirrors lento_practice/analyze.py. */
import { midiName, type Score, type ScoreNote } from "../core/score";
import { align, groupEvents, type Event } from "./align";
import type { PitchTrack } from "./pitch";

export type Status =
  | "in_tune"
  | "slightly_off"
  | "out_of_tune"
  | "wrong_note"
  | "missed"
  | "score_suspect" // consistently off by one interval: the score may be wrong
  | "double_stop" // second note of a double stop; not measured yet
  | "not_played"; // outside the part of the score the recording covers

export interface Settings {
  a4: number;
  goodCents: number;
  okCents: number;
  wrongNoteCents: number;
  timingMs: number;
  measures?: [string, string];
  strict?: boolean; // with measures: the take must start and end there (default). false: it may cover part of the range
  suspectRun: number;
}

export const DEFAULT_SETTINGS: Settings = { a4: 440, goodCents: 10, okCents: 25, wrongNoteCents: 70, timingMs: 70, suspectRun: 4 };

export interface NoteResult {
  index: number;
  measure: string;
  beatInMeasure: number;
  written: string;
  writtenMidi: number;
  status: Status;
  heard: string | null;
  heardMidi: number | null;
  cents: number | null;
  onsetSec: number | null;
  timingMs: number | null; // + late, - early, against your local tempo
  timing: "early" | "late" | null;
  inChord: boolean;
  note: ScoreNote;
}

export interface Analysis {
  score: Score;
  settings: Settings;
  results: NoteResult[];
  firstMeasure: string | null;
  lastMeasure: string | null;
  tempoBpm: number | null;
  tempoStartBpm: number | null;
  tempoEndBpm: number | null;
  tuningOffsetCents: number | null;
  warnings: string[];
}

const median = (v: number[]): number => {
  const s = [...v].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const round = (v: number, digits = 1) => Math.round(v * 10 ** digits) / 10 ** digits;

function fitLine(x: number[], y: number[]): [number, number] | null {
  if (x.length < 2 || Math.max(...x) === Math.min(...x)) return null;
  let keep = x.map(() => true);
  let slope = 0;
  let icept = 0;
  for (let iter = 0; iter < 3; iter++) {
    const xs = x.filter((_, i) => keep[i]);
    const ys = y.filter((_, i) => keep[i]);
    const mx = xs.reduce((a, b) => a + b, 0) / xs.length;
    const my = ys.reduce((a, b) => a + b, 0) / ys.length;
    let sxy = 0;
    let sxx = 0;
    xs.forEach((xv, i) => {
      sxy += (xv - mx) * (ys[i] - my);
      sxx += (xv - mx) ** 2;
    });
    if (sxx === 0) break;
    slope = sxy / sxx;
    icept = my - slope * mx;
    const resid = x.map((xv, i) => Math.abs(y[i] - (slope * xv + icept)));
    const mad = median(resid.filter((_, i) => keep[i])) + 1e-3;
    const next = resid.map((r) => r <= 3 * mad + 0.05);
    if (next.filter(Boolean).length < 2 || next.every((v, i) => v === keep[i])) break;
    keep = next;
  }
  return [slope, icept];
}

function measurePitch(track: PitchTrack, ev: Event): [number | null, number] {
  const a = ev.startFrame;
  const b = ev.endFrame;
  const all: number[] = [];
  for (let t = a; t < b; t++) if (Number.isFinite(track.midi[t])) all.push(track.midi[t]);
  if (!all.length) return [null, 0];
  const length = b - a;
  const head = Math.max(5, Math.floor(0.2 * length)); // bow attack
  const tail = Math.floor(0.15 * length); // release, shift to the next note
  let mid: number[] = [];
  for (let t = a + head; t < b - tail; t++) if (Number.isFinite(track.midi[t])) mid.push(track.midi[t]);
  if (mid.length < 3) mid = all;
  return [median(mid), all.length];
}

function refineOnset(track: PitchTrack, frame: number): number {
  const lo = Math.max(0, frame - 4);
  const hi = Math.min(track.onset.length, frame + 3);
  let k = frame;
  let best = -1;
  for (let t = lo; t < hi; t++) if (track.onset[t] > best) [best, k] = [track.onset[t], t];
  return best >= 0.3 ? k : frame;
}

function expectedTimes(track: PitchTrack, events: Event[]): [Float64Array, number] | null {
  const beats: number[] = [];
  const secs: number[] = [];
  for (const ev of events) {
    if (ev.startFrame < 0 || ev.endFrame - ev.startFrame < 3) continue;
    const m: number[] = [];
    for (let t = ev.startFrame; t < ev.endFrame; t++) if (Number.isFinite(track.midi[t])) m.push(track.midi[t]);
    if (m.length < 3) continue;
    const med = median(m);
    if (Math.min(...ev.pitches.map((p) => Math.abs(med - p))) > 0.5) continue;
    beats.push(ev.beat);
    secs.push(track.times[ev.startFrame]);
  }
  if (beats.length < 4) return null;
  const fit = fitLine(beats, secs);
  if (!fit || fit[0] <= 0) return null;
  const [spb, icept] = fit;
  const kb: number[] = [];
  const kr: number[] = [];
  beats.forEach((b, i) => {
    const r = secs[i] - (spb * b + icept);
    if (Math.abs(r) <= spb) {
      kb.push(b);
      kr.push(r);
    }
  });
  if (kb.length < 4) return null;
  const interp = (b: number): number => {
    if (b <= kb[0]) return kr[0];
    if (b >= kb[kb.length - 1]) return kr[kr.length - 1];
    let i = 1;
    while (kb[i] < b) i++;
    const f = (b - kb[i - 1]) / (kb[i] - kb[i - 1] || 1);
    return kr[i - 1] * (1 - f) + kr[i] * f;
  };
  return [Float64Array.from(events, (ev) => spb * ev.beat + icept + interp(ev.beat)), spb];
}

export function analyze(score: Score, track: PitchTrack, settings: Settings = DEFAULT_SETTINGS): Analysis {
  const warnings = [...score.warnings];
  let notes = score.notes;
  let freeEnds = true;
  if (settings.measures) {
    const [lo, hi] = score.measureRange(...settings.measures);
    notes = notes.filter((n) => n.measureIndex >= lo && n.measureIndex <= hi);
    freeEnds = settings.strict === false;
  }
  if (!notes.length) throw new Error("no notes to compare in that part of the score");

  const events = groupEvents(notes);
  align(track, events, { freeEnds });
  const expected = expectedTimes(track, events);
  if (expected) align(track, events, { freeEnds, expectedSec: expected[0], secPerBeat: expected[1] });

  const played = events.filter((e) => e.startFrame >= 0);
  if (!played.length) throw new Error("could not find the score's notes in the recording");
  const firstEv = played[0].index;
  const lastEv = played[played.length - 1].index;

  const results = new Map<number, NoteResult>();
  const onsets: [number, number][] = [];
  for (const ev of events) {
    const inside = ev.index >= firstEv && ev.index <= lastEv;
    for (const n of ev.notes) {
      results.set(n.index, {
        index: n.index,
        measure: n.measure,
        beatInMeasure: round(n.beatInMeasure, 3),
        written: n.name,
        writtenMidi: n.midi,
        status: inside ? "missed" : "not_played",
        heard: null,
        heardMidi: null,
        cents: null,
        onsetSec: null,
        timingMs: null,
        timing: null,
        inChord: n.inChord,
        note: n,
      });
    }
    if (!inside || ev.startFrame < 0) continue;
    const [heard, nVoiced] = measurePitch(track, ev);
    if (heard === null || nVoiced < 3) continue;
    const target = ev.notes.reduce((a, b) => (Math.abs(heard - b.midi) < Math.abs(heard - a.midi) ? b : a));
    let diff = heard - target.midi;
    if (Math.abs(diff) > 6 && Math.abs(Math.abs(diff) - 12) < 1) diff -= 12 * Math.sign(diff); // tracker an octave out
    const r = results.get(target.index)!;
    r.heard = midiName(target.midi + diff);
    r.heardMidi = Math.round(target.midi + diff);
    if (Math.abs(diff) * 100 > settings.wrongNoteCents) {
      r.status = "wrong_note";
      r.cents = round((diff - Math.round(diff)) * 100);
    } else {
      r.cents = round(diff * 100);
      const c = Math.abs(r.cents);
      r.status = c <= settings.goodCents ? "in_tune" : c <= settings.okCents ? "slightly_off" : "out_of_tune";
    }
    r.onsetSec = round(track.times[refineOnset(track, ev.startFrame)], 3);
    onsets.push([ev.beat, r.onsetSec]);
    for (const other of ev.notes) {
      if (other === target) continue;
      const o = results.get(other.index)!;
      o.status = "double_stop";
      o.onsetSec = r.onsetSec;
    }
  }

  const ordered = [...results.keys()].sort((a, b) => a - b).map((i) => results.get(i)!);
  flagSuspectScore(ordered, settings);
  const [tempo, tStart, tEnd] = timing(ordered, onsets, settings);

  const measured = ordered.filter((r) => r.cents !== null && r.status !== "wrong_note" && r.status !== "score_suspect").map((r) => r.cents!);
  const offset = measured.length >= 5 ? round(median(measured)) : null;
  if (offset !== null && Math.abs(offset) >= 6) {
    const a4 = settings.a4 * 2 ** (offset / 1200);
    warnings.push(
      `On average you are ${Math.abs(offset).toFixed(0)} cents ${offset > 0 ? "sharp" : "flat"}. ` +
        `If you tuned to A=${a4.toFixed(0)}, set the tuning to ${a4.toFixed(0)} Hz to judge notes against your own tuning.`,
    );
  }
  const inScore = ordered.filter((r) => r.status !== "not_played");
  return {
    score,
    settings,
    results: ordered,
    firstMeasure: inScore[0]?.measure ?? null,
    lastMeasure: inScore[inScore.length - 1]?.measure ?? null,
    tempoBpm: tempo,
    tempoStartBpm: tStart,
    tempoEndBpm: tEnd,
    tuningOffsetCents: offset,
    warnings,
  };
}

/** Runs of notes all off by the same interval point at a misread score, not at the player. */
function flagSuspectScore(results: NoteResult[], settings: Settings): void {
  let run: NoteResult[] = [];
  let last: number | null = null;
  const close = () => {
    if (run.length >= settings.suspectRun) run.forEach((r) => (r.status = "score_suspect"));
  };
  for (const r of results) {
    if (r.heard === null || r.inChord) continue;
    const off = r.status === "wrong_note" && r.heardMidi !== null ? r.heardMidi - r.writtenMidi : 0;
    if (off !== 0 && off === last) run.push(r);
    else {
      close();
      run = off !== 0 ? [r] : [];
    }
    last = off !== 0 ? off : null;
  }
  close();
}

function timing(results: NoteResult[], onsets: [number, number][], settings: Settings): [number | null, number | null, number | null] {
  if (onsets.length < 4) return [null, null, null];
  const beats = onsets.map((o) => o[0]);
  const secs = onsets.map((o) => o[1]);
  const fit = fitLine(beats, secs);
  if (!fit || fit[0] <= 0) return [null, null, null];
  const tempo = round(60 / fit[0]);

  for (const r of results) {
    if (r.onsetSec === null || r.status === "double_stop") continue;
    const b = r.note.beat;
    let idx = beats.map((x, i) => [Math.abs(x - b), i]).filter(([d]) => d <= 4).map(([, i]) => i);
    if (idx.length < 4) idx = beats.map((x, i) => [Math.abs(x - b), i]).sort((p, q) => p[0] - q[0]).slice(0, 4).map(([, i]) => i);
    const local = fitLine(idx.map((i) => beats[i]), idx.map((i) => secs[i])) ?? fit;
    const dev = (r.onsetSec - (local[0] * b + local[1])) * 1000;
    r.timingMs = Math.round(dev);
    r.timing = dev > settings.timingMs ? "late" : dev < -settings.timingMs ? "early" : null;
  }

  const order = beats.map((_, i) => i).sort((p, q) => beats[p] - beats[q]);
  const q = Math.max(3, Math.floor(beats.length / 4));
  const head = order.slice(0, q);
  const tail = order.slice(-q);
  const fs = fitLine(head.map((i) => beats[i]), head.map((i) => secs[i]));
  const fe = fitLine(tail.map((i) => beats[i]), tail.map((i) => secs[i]));
  return [tempo, fs && fs[0] > 0 ? round(60 / fs[0]) : null, fe && fe[0] > 0 ? round(60 / fe[0]) : null];
}
