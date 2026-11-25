/**
 * Plays a part with Web Audio at any tempo, with an optional count-in and loop.
 * The sound is synthesised (bowed-string-like), so slowing down never changes pitch.
 */
import type { Score, ScoreNote } from "../core/score";

export interface PlayOptions {
  parts: Score[]; // the parts to sound; the first one sets the timeline
  fromMeasure: number; // measure index, inclusive
  toMeasure: number; // measure index, inclusive
  tempoFactor: number; // 0.5 = half speed
  countIn: boolean;
  loop: boolean;
  click: number; // metronome step in quarter notes (4 whole, 2 half, 1 quarter, 0.5 eighth, 0.25 16th); 0 off
  mute?: boolean; // count-in and clicks only (for recording without the part sounding)
}

const LOOKAHEAD = 0.25; // seconds scheduled ahead
let wave: PeriodicWave | null = null;

function stringWave(ctx: BaseAudioContext): PeriodicWave {
  if (wave) return wave;
  const n = 16;
  const real = new Float32Array(n);
  const imag = new Float32Array(n);
  for (let k = 1; k < n; k++) imag[k] = (1 / k) * (k % 2 ? 1 : 0.7);
  wave = ctx.createPeriodicWave(real, imag);
  return wave;
}

export class Player {
  private timer: number | null = null;
  private nodes = new Set<AudioScheduledSourceNode>();
  private startTime = 0;
  private opts: PlayOptions | null = null;
  private passStart = 0; // audio time at which the current pass's first beat sounds
  private passIndex = 0;
  private scheduledUntilBeat = 0;
  private startBeat = 0;
  private endBeat = 0;
  onEnd: (() => void) | null = null;

  constructor(readonly ctx: AudioContext, private readonly out: AudioNode = ctx.destination) {}

  get playing(): boolean {
    return this.timer !== null;
  }

  /** Seconds from the first beat to `beat` at the playback tempo. */
  private secs(beat: number): number {
    const s = this.opts!.parts[0];
    return (s.secondsAt(beat) - s.secondsAt(this.startBeat)) / this.opts!.tempoFactor;
  }

  private get passLength(): number {
    return this.secs(this.endBeat);
  }

  /** The beat being heard now, or null before the first beat (count-in) and after the end. */
  currentBeat(): number | null {
    if (!this.opts || !this.playing) return null;
    const t = this.ctx.currentTime - this.passStart;
    if (t < 0) return null;
    const len = this.passLength;
    const into = this.opts.loop ? t % len : t;
    if (into > len) return null;
    // invert secs() by bisection
    let lo = this.startBeat;
    let hi = this.endBeat;
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2;
      if (this.secs(mid) < into) lo = mid;
      else hi = mid;
    }
    return lo;
  }

  /** Audio-clock time at which the first beat sounds (after any count-in). */
  get firstBeatTime(): number {
    return this.startTime;
  }

  async play(opts: PlayOptions): Promise<void> {
    this.stop();
    if (this.ctx.state !== "running") await this.ctx.resume();
    this.opts = opts;
    const s = opts.parts[0];
    this.startBeat = s.measureStarts[opts.fromMeasure] ?? 0;
    this.endBeat = s.measureStarts[opts.toMeasure + 1] ?? s.totalBeats;
    const now = this.ctx.currentTime + 0.1;
    const [beatsPerBar, beatType] = s.timeSignature;
    const clickBeat = 4 / beatType; // quarter notes per click
    const tempo = s.tempos.findLast?.((t) => t[0] <= this.startBeat)?.[1] ?? s.tempos[0][1];
    const clickSec = (60 / (tempo * opts.tempoFactor)) * clickBeat;
    if (opts.countIn) {
      for (let i = 0; i < beatsPerBar; i++) this.click(now + i * clickSec, i === 0 ? 2 : 1);
      this.startTime = now + beatsPerBar * clickSec;
    } else {
      this.startTime = now;
    }
    this.passStart = this.startTime;
    this.passIndex = 0;
    this.scheduledUntilBeat = this.startBeat;
    this.timer = window.setInterval(() => this.schedule(), 50);
    this.schedule();
  }

  stop(): void {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    for (const n of this.nodes) {
      try {
        n.stop();
      } catch {
        /* already stopped */
      }
    }
    this.nodes.clear();
  }

  private schedule(): void {
    const o = this.opts!;
    const horizon = this.ctx.currentTime + LOOKAHEAD;
    for (;;) {
      const passStart = this.startTime + this.passIndex * this.passLength;
      if (this.ctx.currentTime >= passStart) this.passStart = passStart;
      const fromBeat = this.scheduledUntilBeat;
      // schedule up to the horizon within this pass
      let toBeat = this.endBeat;
      if (passStart + this.secs(this.endBeat) > horizon) {
        let lo = fromBeat;
        let hi = this.endBeat;
        for (let i = 0; i < 25; i++) {
          const mid = (lo + hi) / 2;
          if (passStart + this.secs(mid) < horizon) lo = mid;
          else hi = mid;
        }
        toBeat = lo;
      }
      if (!o.mute) {
        for (const part of o.parts) {
          for (const n of part.notes) if (n.beat >= fromBeat && n.beat < toBeat && n.beat < this.endBeat) this.note(n, passStart, part === o.parts[0] ? 1 : 0.55);
        }
      }
      if (o.click > 0) {
        const s0 = o.parts[0];
        const beatUnit = 4 / s0.timeSignature[1];
        for (let b = Math.ceil((fromBeat - this.startBeat) / o.click - 1e-9) * o.click + this.startBeat; b < toBeat - 1e-9; b += o.click) {
          const m = [...s0.measureStarts].reverse().find((ms) => ms <= b + 1e-6) ?? 0;
          const level = Math.abs(b - m) < 1e-6 ? 2 : Math.abs(((b - m) / beatUnit) % 1) < 1e-6 ? 1 : 0;
          this.click(passStart + this.secs(b), level);
        }
      }
      this.scheduledUntilBeat = toBeat;
      if (toBeat < this.endBeat) return;
      if (!o.loop) {
        const endAt = passStart + this.passLength;
        if (this.ctx.currentTime > endAt + 0.3) {
          this.stop();
          this.onEnd?.();
        }
        return;
      }
      this.passIndex += 1;
      this.scheduledUntilBeat = this.startBeat;
    }
  }

  private note(n: ScoreNote, passStart: number, level: number): void {
    const t0 = passStart + this.secs(n.beat);
    const t1 = passStart + this.secs(Math.min(n.beat + n.duration, this.endBeat));
    const dur = Math.max(0.06, t1 - t0 - 0.02);
    const freq = 440 * 2 ** ((n.midi - 69) / 12);
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    osc.setPeriodicWave(stringWave(ctx));
    osc.frequency.value = freq;
    const vib = ctx.createOscillator();
    vib.frequency.value = 5.3;
    const vibDepth = ctx.createGain();
    vibDepth.gain.setValueAtTime(0, t0);
    vibDepth.gain.linearRampToValueAtTime(freq * 0.004, t0 + Math.min(0.35, dur));
    vib.connect(vibDepth).connect(osc.frequency);
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = Math.min(6000, freq * 8);
    const env = ctx.createGain();
    const peak = 0.18 * level * (n.inChord ? 0.7 : 1);
    env.gain.setValueAtTime(0, t0);
    env.gain.linearRampToValueAtTime(peak, t0 + 0.05);
    env.gain.setValueAtTime(peak, t0 + dur);
    env.gain.linearRampToValueAtTime(0, t0 + dur + 0.08);
    osc.connect(filter).connect(env).connect(this.out);
    for (const node of [osc, vib]) {
      node.start(t0);
      node.stop(t0 + dur + 0.1);
      this.nodes.add(node);
      node.onended = () => this.nodes.delete(node);
    }
  }

  /** level 2: first beat of the measure, 1: a beat, 0: a subdivision. */
  click(t: number, level: 0 | 1 | 2): void {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    // well above the pitch tracker's range, so clicks heard by the mic are not taken for notes
    osc.frequency.value = [2640, 3150, 3520][level];
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, t);
    env.gain.exponentialRampToValueAtTime([0.1, 0.22, 0.35][level], t + 0.002);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
    osc.connect(env).connect(this.out);
    osc.start(t);
    osc.stop(t + 0.06);
    this.nodes.add(osc);
    osc.onended = () => this.nodes.delete(osc);
  }
}
