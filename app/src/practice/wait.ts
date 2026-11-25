/**
 * Wait mode: the cursor stops on each note and moves on only once you play it. No metronome: the point is
 * finding the right notes. This file is the judging, with no audio or page code, so it can be tested.
 */
import { midiName, type Score, type ScoreNote } from "../core/score";

/** One place the cursor stops: a note, or the notes of a double stop. */
export interface WaitStep {
  beat: number;
  midis: number[];
  notes: ScoreNote[];
  measure: string;
  measureIndex: number;
  beatInMeasure: number;
  tries: number; // wrong notes held before the right one
  ms: number; // how long it took
}

/** The steps from measure index `from` to `to` (inclusive), in order. */
export function waitSteps(score: Score, from: number, to: number): WaitStep[] {
  const steps: WaitStep[] = [];
  for (const n of score.notes) {
    if (n.measureIndex < from || n.measureIndex > to) continue;
    const last = steps[steps.length - 1];
    if (last && Math.abs(last.beat - n.beat) < 1e-6) {
      last.notes.push(n);
      if (!last.midis.includes(n.midi)) last.midis.push(n.midi);
      continue;
    }
    steps.push({ beat: n.beat, midis: [n.midi], notes: [n], measure: n.measure, measureIndex: n.measureIndex, beatInMeasure: n.beatInMeasure, tries: 0, ms: 0 });
  }
  return steps;
}

export interface JudgeOptions {
  cents: number; // how close counts as the right note
  holdMs: number; // how long it must be held, so a slide or a scratchy start doesn't count
}

export type JudgeEvent = "advance" | "wrong" | "done" | null;

/**
 * Feed it what the microphone hears, frame by frame. A note counts once it stays within `cents` of a target for
 * `holdMs`. After a note counts, the next one must be a new attack: a different pitch, a gap, or (for a repeated
 * note) a dip in loudness such as a bow change, so one long note can't tick off several.
 */
export class WaitJudge {
  index = 0;
  private stepStart: number | null = null;
  private matchSince: number | null = null;
  private wrongSince: number | null = null;
  private wrongMidi = 0;
  private wrongCounted = false;
  private armed = true;
  private lastMidi = 0;
  private heldPeak = 0;

  constructor(
    readonly steps: WaitStep[],
    readonly opts: JudgeOptions,
  ) {}

  get done(): boolean {
    return this.index >= this.steps.length;
  }

  get current(): WaitStep | null {
    return this.steps[this.index] ?? null;
  }

  /** `midi` is the fractional pitch heard (null for none), `rms` its loudness, `t` the time in ms. */
  feed(midi: number | null, rms: number, t: number): JudgeEvent {
    const step = this.current;
    if (!step) return null;
    this.stepStart ??= t;
    if (midi === null) {
      this.armed = true;
      this.matchSince = this.wrongSince = null;
      return null;
    }
    if (!this.armed) {
      if (Math.abs(midi - this.lastMidi) > 0.6 || rms < 0.55 * this.heldPeak) this.armed = true;
      else {
        this.heldPeak = Math.max(this.heldPeak, rms);
        return null;
      }
    }
    const hit = step.midis.find((m) => Math.abs(midi - m) * 100 <= this.opts.cents);
    if (hit !== undefined) {
      this.wrongSince = null;
      this.matchSince ??= t;
      if (t - this.matchSince < this.opts.holdMs) return null;
      step.ms = t - this.stepStart;
      this.index += 1;
      this.stepStart = t;
      this.matchSince = null;
      this.armed = false;
      this.lastMidi = hit;
      this.heldPeak = rms;
      return this.done ? "done" : "advance";
    }
    this.matchSince = null;
    if (this.wrongSince === null || Math.abs(midi - this.wrongMidi) > 0.6) {
      this.wrongSince = t;
      this.wrongMidi = midi;
      this.wrongCounted = false;
    }
    if (!this.wrongCounted && t - this.wrongSince >= this.opts.holdMs * 1.5) {
      this.wrongCounted = true;
      step.tries += 1;
      return "wrong";
    }
    return null;
  }

  /** Moves on without hearing the note (the Skip button). */
  skip(t: number): JudgeEvent {
    const step = this.current;
    if (!step) return null;
    step.ms = t - (this.stepStart ?? t);
    this.index += 1;
    this.stepStart = t;
    this.matchSince = this.wrongSince = null;
    this.armed = true;
    return this.done ? "done" : "advance";
  }

  /** Steps that needed several tries, the hardest first. */
  hardest(minTries = 2): WaitStep[] {
    return this.steps.filter((s) => s.tries >= minTries).sort((a, b) => b.tries - a.tries || a.beat - b.beat);
  }
}

const CELLO_STRINGS: [string, number][] = [
  ["A", 57],
  ["D", 50],
  ["G", 43],
  ["C", 36],
];
const FIRST_POSITION = ["open", "1st finger, half position", "1st finger", "2nd finger", "3rd finger", "4th finger"];

/** Where a note is usually played on the cello: the highest string that reaches it in the lowest position. */
export function celloWhere(midi: number): string {
  for (const [name, open] of CELLO_STRINGS) {
    const up = midi - open;
    if (up >= 0 && up < FIRST_POSITION.length) return `${name} string, ${FIRST_POSITION[up]}`;
  }
  if (midi < 36) return "below the cello's range";
  return midi - 57 <= 12 ? "A string, upper position" : "A string, thumb position";
}

/** "F#3", or "D3 + A3" for a double stop. */
export function stepName(s: WaitStep): string {
  return s.midis.map(midiName).join(" + ");
}
