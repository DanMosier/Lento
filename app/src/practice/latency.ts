/** Measuring how late sound arrives (Bluetooth headphones can add 150-300 ms) by tapping along with clicks. */

export interface DelayEstimate {
  ms: number; // how much later the sound is heard than the app scheduled it
  spreadMs: number; // typical distance of a tap from that (median absolute deviation)
  taps: number; // taps that were used
}

/**
 * Pairs each tap with the nearest click and takes the median offset. Taps more than half a click
 * away from any click are ignored, as are the first `skip` clicks (people need a few to lock in).
 * Returns null with fewer than `minTaps` usable taps.
 */
export function estimateDelay(clicks: number[], taps: number[], skip = 3, minTaps = 5): DelayEstimate | null {
  if (clicks.length < 2) return null;
  const period = clicks[1] - clicks[0];
  const used = clicks.slice(skip);
  const offsets: number[] = [];
  const taken = new Set<number>();
  for (const t of taps) {
    // sound is heard late, not early, so each click owns the window from -period/4 to +3*period/4
    const best = used.findIndex((c) => t - c > -period / 4 && t - c <= (period * 3) / 4);
    if (best >= 0 && !taken.has(best)) {
      taken.add(best);
      offsets.push(t - used[best]);
    }
  }
  if (offsets.length < minTaps) return null;
  const med = median(offsets);
  const spread = median(offsets.map((o) => Math.abs(o - med)));
  return { ms: Math.round(med * 1000), spreadMs: Math.round(spread * 1000), taps: offsets.length };
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** What the browser itself reports for output delay, in ms (often too low for Bluetooth), or null. */
export function reportedDelay(ctx: AudioContext): number | null {
  const out = (ctx as AudioContext & { outputLatency?: number }).outputLatency;
  if (out === undefined || !Number.isFinite(out)) return null;
  return Math.round((out + (ctx.baseLatency || 0)) * 1000);
}

/**
 * Plays `count` clicks and records taps on the audio clock. Call `tap(event)` from the tap handler.
 * `onClick(i, when)` lets the page flash a dot in time with each click (shifted by the current delay setting).
 */
export class TapTest {
  readonly clicks: number[] = [];
  readonly taps: number[] = [];
  private nodes: OscillatorNode[] = [];

  constructor(private readonly ctx: AudioContext, readonly count = 16, readonly period = 0.75) {}

  start(): number {
    const t0 = this.ctx.currentTime + 1;
    for (let i = 0; i < this.count; i++) {
      const t = t0 + i * this.period;
      this.clicks.push(t);
      const osc = this.ctx.createOscillator();
      osc.frequency.value = i % 4 === 0 ? 1760 : 1320;
      const env = this.ctx.createGain();
      env.gain.setValueAtTime(0.0001, t);
      env.gain.exponentialRampToValueAtTime(0.4, t + 0.002);
      env.gain.exponentialRampToValueAtTime(0.0001, t + 0.06);
      osc.connect(env).connect(this.ctx.destination);
      osc.start(t);
      osc.stop(t + 0.08);
      this.nodes.push(osc);
    }
    return t0 + this.count * this.period;
  }

  /** Records a tap, converting the event's time to the audio clock. */
  tap(e: Event): void {
    const ago = Math.max(0, (performance.now() - e.timeStamp) / 1000);
    this.taps.push(this.ctx.currentTime - (ago < 1 ? ago : 0));
  }

  stop(): void {
    for (const n of this.nodes) {
      try {
        n.stop();
      } catch {
        /* already stopped */
      }
    }
    this.nodes = [];
  }

  result(): DelayEstimate | null {
    return estimateDelay(this.clicks, this.taps);
  }
}
