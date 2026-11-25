/**
 * Line a pitch track up with the score's notes. Mirrors lento_practice/align.py.
 *
 * A left-to-right dynamic programme over two states per note group ("event"):
 * the gap before it and the event itself. Every frame goes to one state, in
 * score order, at whatever tempo was played. The recording may start and stop
 * anywhere in the score unless `freeEnds` is false.
 */
import type { ScoreNote } from "../core/score";
import type { PitchTrack } from "./pitch";

const PITCH_CAP = 6; // semitones
const UNVOICED_IN_NOTE = 1;
const VOICED_IN_GAP = 6.5; // above PITCH_CAP so wrong notes stay notes
const SKIP = 8;
const ENTER = 0.5;
const LEGATO = 0.3;
const REPEAT = 4;
const POSITION = 1; // per frame and per beat beyond half a beat from where the rhythm expects a note
const OCTAVE = 2; // extra cost for hearing the note an octave out
const INF = 1e18;

export interface Event {
  index: number;
  notes: ScoreNote[];
  beat: number;
  duration: number;
  pitches: number[];
  startFrame: number; // -1 when not heard
  endFrame: number; // exclusive
}

export function groupEvents(notes: ScoreNote[]): Event[] {
  const events: Event[] = [];
  for (const n of notes) {
    const last = events[events.length - 1];
    if (last && Math.abs(last.beat - n.beat) < 1e-6) {
      last.notes.push(n);
      last.duration = Math.max(last.duration, n.duration);
      last.pitches.push(n.midi);
    } else {
      events.push({ index: events.length, notes: [n], beat: n.beat, duration: n.duration, pitches: [n.midi], startFrame: -1, endFrame: -1 });
    }
  }
  return events;
}

export interface AlignOptions {
  freeEnds?: boolean;
  expectedSec?: Float64Array;
  secPerBeat?: number;
}

function sharesPitch(a: Event, b: Event): boolean {
  return a.pitches.some((p) => b.pitches.includes(p));
}

export function align(track: PitchTrack, events: Event[], opts: AlignOptions = {}): Event[] {
  const freeEnds = opts.freeEnds ?? true;
  const nEv = events.length;
  const nFr = track.midi.length;
  if (!nEv || !nFr) return events;
  if (nEv * nFr > 120_000_000) throw new Error("recording and score are too long to compare at once; choose a range of measures");

  const same = events.map((e, j) => j > 0 && sharesPitch(e, events[j - 1]));
  const noteCost = new Float64Array(nEv);
  const fillCost = (t: number) => {
    const m = track.midi[t];
    const voiced = Number.isFinite(m);
    const time = track.times[t];
    for (let j = 0; j < nEv; j++) {
      let c: number;
      if (!voiced) c = UNVOICED_IN_NOTE;
      else {
        c = Infinity;
        for (const p of events[j].pitches) {
          const dd = Math.abs(m - p);
          c = Math.min(c, dd, Math.min(Math.abs(m - p - 12), Math.abs(m - p + 12)) + OCTAVE);
        }
        c = Math.min(c, PITCH_CAP);
      }
      if (opts.expectedSec && opts.secPerBeat) {
        const off = Math.abs(time - opts.expectedSec[j]) / opts.secPerBeat;
        c += Math.min(POSITION * Math.max(off - 0.5, 0), PITCH_CAP);
      }
      noteCost[j] = c;
    }
  };

  let E = new Float64Array(nEv);
  let G = new Float64Array(nEv + 1);
  let nE = new Float64Array(nEv);
  let nG = new Float64Array(nEv + 1);
  const backE = new Int8Array(nFr * nEv);
  const backG = new Int8Array(nFr * (nEv + 1));

  fillCost(0);
  const gap0 = Number.isFinite(track.midi[0]) ? VOICED_IN_GAP : 0;
  for (let j = 0; j < nEv; j++) E[j] = freeEnds || j === 0 ? noteCost[j] : INF;
  for (let j = 0; j <= nEv; j++) G[j] = freeEnds || j === 0 ? gap0 : INF;

  for (let t = 1; t < nFr; t++) {
    fillCost(t);
    const noOnset = 1 - track.onset[t];
    const gapCost = Number.isFinite(track.midi[t]) ? VOICED_IN_GAP : 0;
    for (let j = 0; j < nEv; j++) {
      let best = E[j];
      let code = 0;
      let c = G[j] + ENTER * noOnset;
      if (c < best) [best, code] = [c, 1];
      if (j >= 1) {
        c = E[j - 1] + (same[j] ? REPEAT : LEGATO) * noOnset;
        if (c < best) [best, code] = [c, 2];
        c = G[j - 1] + SKIP;
        if (c < best) [best, code] = [c, 4];
      }
      if (j >= 2) {
        c = E[j - 2] + SKIP;
        if (c < best) [best, code] = [c, 3];
      }
      nE[j] = best + noteCost[j];
      backE[t * nEv + j] = code;
    }
    for (let j = 0; j <= nEv; j++) {
      let best = G[j];
      let code = 0;
      if (j >= 1) {
        let c = E[j - 1];
        if (c < best) [best, code] = [c, 1];
        c = G[j - 1] + SKIP;
        if (c < best) [best, code] = [c, 2];
      }
      nG[j] = best + gapCost;
      backG[t * (nEv + 1) + j] = code;
    }
    [E, nE] = [nE, E];
    [G, nG] = [nG, G];
  }

  let isNote = true;
  let j = 0;
  let bestEnd = Infinity;
  for (let k = 0; k < nEv; k++) {
    const c = E[k] + (freeEnds ? 0 : SKIP * (nEv - 1 - k));
    if (c < bestEnd) [bestEnd, j, isNote] = [c, k, true];
  }
  for (let k = 0; k <= nEv; k++) {
    const c = G[k] + (freeEnds ? 0 : SKIP * (nEv - k));
    if (c < bestEnd) [bestEnd, j, isNote] = [c, k, false];
  }

  const path = new Int32Array(nFr).fill(-1);
  for (let t = nFr - 1; t >= 0; t--) {
    if (isNote) {
      path[t] = j;
      const code = t > 0 ? backE[t * nEv + j] : 0;
      if (code === 1) isNote = false;
      else if (code === 2) j -= 1;
      else if (code === 3) j -= 2;
      else if (code === 4) [isNote, j] = [false, j - 1];
    } else {
      const code = t > 0 ? backG[t * (nEv + 1) + j] : 0;
      if (code === 1) [isNote, j] = [true, j - 1];
      else if (code === 2) j -= 1;
    }
  }

  for (const ev of events) ev.startFrame = ev.endFrame = -1;
  for (let t = 0; t < nFr; t++) {
    const k = path[t];
    if (k < 0) continue;
    if (events[k].startFrame < 0) events[k].startFrame = t;
    events[k].endFrame = t + 1;
  }
  splitRepeated(track, events);
  return events;
}

/**
 * Pitch alone cannot tell where one A ends and the next begins, so inside a run
 * of same-pitch notes each boundary goes to the strongest onset or end of a
 * silence near where the written rhythm puts it.
 */
function splitRepeated(track: PitchTrack, events: Event[]): void {
  const silent = (t: number) => !Number.isFinite(track.midi[t]);
  let j = 0;
  while (j < events.length) {
    let k = j;
    while (k + 1 < events.length && events[k].startFrame >= 0 && events[k + 1].startFrame >= 0 && sharesPitch(events[k], events[k + 1])) k++;
    if (k > j && events[j].startFrame >= 0) {
      const run = events.slice(j, k + 1);
      const a = run[0].startFrame;
      const b = run[run.length - 1].endFrame;
      const total = run[run.length - 1].beat + run[run.length - 1].duration - run[0].beat;
      let prev = a;
      for (let r = 1; r < run.length; r++) {
        const ev = run[r];
        const expect = a + ((b - a) * (ev.beat - run[0].beat)) / total;
        const reach = (0.35 * (b - a) * Math.min(ev.duration, ev.beat - run[r - 1].beat)) / total;
        const lo = Math.max(prev + 1, Math.floor(expect - reach));
        const hi = Math.min(b - 1, Math.floor(expect + reach) + 1);
        let cut = Math.round(expect);
        if (hi > lo) {
          let bestScore = -Infinity;
          for (let t = lo; t < hi; t++) {
            const afterSilence = t > 0 && silent(t - 1) && !silent(t) ? 1 : 0;
            const evidence = Math.max(track.onset[t], afterSilence);
            const closeness = 1 - Math.abs(t - expect) / Math.max(reach, 1);
            const s = evidence + 0.5 * closeness;
            if (s > bestScore) [bestScore, cut] = [s, t];
          }
        }
        cut = Math.max(prev + 1, Math.min(cut, b - 1));
        run[r - 1].endFrame = cut;
        ev.startFrame = cut;
        prev = cut;
      }
      for (const ev of run.slice(1)) while (ev.startFrame < ev.endFrame - 1 && silent(ev.startFrame)) ev.startFrame++;
    }
    j = k + 1;
  }
}
