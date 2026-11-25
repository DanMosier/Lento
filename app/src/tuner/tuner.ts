/** A live tuner: microphone in, nearest note and cents out, plus sustained reference tones. */
import { detectPitch, reading, type Reading } from "../core/live-pitch";

export { detectPitch, reading, type Reading };

export class Tuner {
  onReading: ((r: Reading | null) => void) | null = null;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private timer = 0;
  private recent: number[] = [];
  private osc: OscillatorNode | null = null;
  private gain: GainNode | null = null;

  constructor(private readonly ctx: AudioContext, public a4 = 440) {}

  get running(): boolean {
    return this.stream !== null;
  }

  async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("this browser cannot use the microphone (it needs https)");
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    if (this.ctx.state !== "running") await this.ctx.resume();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 4096;
    src.connect(this.analyser);
    const buf = new Float32Array(this.analyser.fftSize);
    this.timer = window.setInterval(() => {
      this.analyser!.getFloatTimeDomainData(buf);
      const hz = detectPitch(buf, this.ctx.sampleRate);
      if (hz === null) {
        this.recent = [];
        this.onReading?.(null);
        return;
      }
      // median of the last few readings steadies the needle without lagging much
      this.recent.push(hz);
      if (this.recent.length > 5) this.recent.shift();
      const sorted = [...this.recent].sort((p, q) => p - q);
      this.onReading?.(reading(sorted[sorted.length >> 1], this.a4));
    }, 60);
  }

  stop(): void {
    window.clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.analyser = null;
    this.tone(null);
  }

  /** Play a steady reference note (MIDI number), or stop it with null. */
  tone(midi: number | null): void {
    if (this.osc && this.gain) {
      const t = this.ctx.currentTime;
      this.gain.gain.setTargetAtTime(0, t, 0.05);
      this.osc.stop(t + 0.3);
      this.osc = this.gain = null;
    }
    if (midi === null) return;
    if (this.ctx.state !== "running") void this.ctx.resume();
    const osc = this.ctx.createOscillator();
    const real = new Float32Array([0, 1, 0.5, 0.33, 0.25, 0.2]);
    osc.setPeriodicWave(this.ctx.createPeriodicWave(real, new Float32Array(real.length)));
    osc.frequency.value = this.a4 * 2 ** ((midi - 69) / 12);
    const gain = this.ctx.createGain();
    gain.gain.value = 0;
    gain.gain.setTargetAtTime(0.15, this.ctx.currentTime, 0.05);
    osc.connect(gain).connect(this.ctx.destination);
    osc.start();
    this.osc = osc;
    this.gain = gain;
  }
}
