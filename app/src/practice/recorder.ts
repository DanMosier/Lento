/** Microphone capture and audio file decoding, delivered at the analysis sample rate. */
import { SAMPLE_RATE } from "./pitch";

const WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("lento-capture", Capture);
`;

export class Recorder {
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[] = [];
  private loaded = false;

  constructor(private readonly ctx: AudioContext) {}

  get recording(): boolean {
    return this.node !== null;
  }

  async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("this browser cannot record audio (it needs https)");
    // processing meant for speech distorts pitch and loudness, so turn it off
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    if (!this.loaded) {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      this.loaded = true;
    }
    if (this.ctx.state !== "running") await this.ctx.resume();
    this.chunks = [];
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "lento-capture");
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => this.chunks.push(e.data);
    const silent = this.ctx.createGain();
    silent.gain.value = 0;
    this.source.connect(this.node).connect(silent).connect(this.ctx.destination);
  }

  /** Stops and returns the take at the context's sample rate. */
  stop(): Float32Array {
    this.source?.disconnect();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.node = null;
    this.source = null;
    this.stream = null;
    const n = this.chunks.reduce((s, c) => s + c.length, 0);
    const out = new Float32Array(n);
    let o = 0;
    for (const c of this.chunks) {
      out.set(c, o);
      o += c.length;
    }
    this.chunks = [];
    return out;
  }
}

/** Resample mono audio to the analysis rate with the browser's own resampler. */
export async function toAnalysisRate(samples: Float32Array, rate: number): Promise<Float32Array> {
  if (rate === SAMPLE_RATE) return samples;
  const length = Math.max(1, Math.ceil((samples.length * SAMPLE_RATE) / rate));
  const off = new OfflineAudioContext(1, length, SAMPLE_RATE);
  const buf = off.createBuffer(1, samples.length, rate);
  buf.copyToChannel(samples as Float32Array<ArrayBuffer>, 0);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

/** Decode any audio file the browser can read (wav, mp3, m4a, ogg, flac) to mono at the analysis rate. */
export async function decodeFile(ctx: BaseAudioContext, data: ArrayBuffer): Promise<Float32Array> {
  const buf = await ctx.decodeAudioData(data);
  const mono = new Float32Array(buf.length);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const ch = buf.getChannelData(c);
    for (let i = 0; i < ch.length; i++) mono[i] += ch[i] / buf.numberOfChannels;
  }
  return toAnalysisRate(mono, buf.sampleRate);
}

/** 16-bit mono WAV, so a take can be saved or shared. */
export function encodeWav(samples: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const dv = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((ch, i) => dv.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF");
  dv.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true);
  dv.setUint16(22, 1, true);
  dv.setUint32(24, rate, true);
  dv.setUint32(28, rate * 2, true);
  dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true);
  str(36, "data");
  dv.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) dv.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
  return new Blob([buf], { type: "audio/wav" });
}
