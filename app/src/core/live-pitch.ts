/**
 * Live pitch from the microphone, for anything that reacts while you play (the tuner, wait mode).
 * Recorded takes use the more careful tracker in practice/pitch.ts instead.
 */
import { NOTE_NAMES } from "./score";

export interface Reading {
  name: string;
  octave: number;
  cents: number;
  hz: number;
}

const FMIN = 55;
const FMAX = 1400;

/** YIN on one buffer. Returns the frequency, or null when there is no clear pitch. */
export function detectPitch(x: Float32Array, rate: number): number | null {
  const tauMin = Math.floor(rate / FMAX);
  const tauMax = Math.min(Math.ceil(rate / FMIN), Math.floor(x.length / 2) - 2);
  const w = x.length - tauMax - 2;
  let energy = 0;
  for (let i = 0; i < w; i++) energy += x[i] * x[i];
  if (Math.sqrt(energy / w) < 0.01) return null;
  const d = new Float64Array(tauMax + 2);
  d[0] = 1;
  let running = 0;
  for (let tau = 1; tau <= tauMax + 1; tau++) {
    let s = 0;
    for (let i = 0; i < w; i++) {
      const v = x[i] - x[i + tau];
      s += v * v;
    }
    running += s;
    d[tau] = running > 0 ? (s * tau) / running : 1;
  }
  let best = -1;
  for (let tau = tauMin; tau <= tauMax; tau++) {
    if (d[tau] < 0.12) {
      while (tau + 1 <= tauMax && d[tau + 1] < d[tau]) tau++;
      best = tau;
      break;
    }
  }
  if (best < 1 || d[best] > 0.3) return null;
  const a = d[best - 1];
  const b = d[best];
  const c = d[best + 1];
  const den = a - 2 * b + c;
  const shift = den ? Math.max(-1, Math.min(1, (0.5 * (a - c)) / den)) : 0;
  return rate / (best + shift);
}

export function reading(hz: number, a4: number): Reading {
  const midi = 69 + 12 * Math.log2(hz / a4);
  const near = Math.round(midi);
  return { name: NOTE_NAMES[((near % 12) + 12) % 12], octave: Math.floor(near / 12) - 1, cents: (midi - near) * 100, hz };
}

/** One look at the microphone: the pitch heard (Hz, or null) and how loud it is (RMS, 0..1). */
export interface MicFrame {
  hz: number | null;
  rms: number;
  time: number; // ms, performance.now()
}

/** The microphone, read about 25 times a second. Only runs between start() and stop(). */
export class LiveMic {
  onFrame: ((f: MicFrame) => void) | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private timer = 0;

  constructor(private readonly ctx: AudioContext) {}

  get running(): boolean {
    return this.stream !== null;
  }

  async start(intervalMs = 40): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("this browser cannot use the microphone (it needs https)");
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    if (this.ctx.state !== "running") await this.ctx.resume();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    const analyser = this.ctx.createAnalyser();
    // 2048 samples is enough for the cello's low C at 48 kHz and keeps each look cheap on a phone
    analyser.fftSize = this.ctx.sampleRate > 50000 ? 4096 : 2048;
    this.source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    this.timer = window.setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let e = 0;
      for (let i = 0; i < buf.length; i += 4) e += buf[i] * buf[i];
      const rms = Math.sqrt((4 * e) / buf.length);
      this.onFrame?.({ hz: detectPitch(buf, this.ctx.sampleRate), rms, time: performance.now() });
    }, intervalMs);
  }

  stop(): void {
    window.clearInterval(this.timer);
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.source = null;
  }
}
