/**
 * A little room sound for playback. Dry recordings in silence sound boxy, so a short reverb (made here from
 * decaying noise, so there's nothing to download) is mixed in. It's the "Room sound" setting.
 */
import { store } from "./app";

const rooms = new WeakMap<BaseAudioContext, { input: GainNode; conv: ConvolverNode; on: boolean }>();

/** An impulse response: about 1.6 s of stereo noise that dies away and darkens, after a short pre-delay. */
export function impulse(ctx: BaseAudioContext, seconds = 1.6): AudioBuffer {
  const rate = ctx.sampleRate;
  const n = Math.floor(seconds * rate);
  const pre = Math.floor(0.012 * rate);
  const buf = ctx.createBuffer(2, n, rate);
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    let seed = ch ? 0x9e3779b9 : 0x2545f491;
    let low = 0;
    for (let i = pre; i < n; i++) {
      seed ^= seed << 13;
      seed ^= seed >>> 17;
      seed ^= seed << 5;
      const white = (seed >>> 0) / 4294967296 - 0.5;
      const t = (i - pre) / rate;
      // higher frequencies die away faster, as in a real room: a low-pass that closes over time
      const k = 0.55 - 0.45 * Math.min(1, t / seconds);
      low += k * (white - low);
      d[i] = low * Math.exp(-4.2 * t) * 1.6;
    }
  }
  return buf;
}

export function roomOn(): boolean {
  return store.get<boolean>("room") ?? true;
}

/**
 * The node to play into: it goes to `dest` directly and through the room. Made once per audio context; the
 * setting is read each time, so switching it in Settings applies to the next playback.
 */
export function roomOut(ctx: BaseAudioContext, dest: AudioNode = ctx.destination): AudioNode {
  let r = rooms.get(ctx);
  if (!r) {
    const input = ctx.createGain();
    const conv = ctx.createConvolver();
    conv.buffer = impulse(ctx);
    const wet = ctx.createGain();
    wet.gain.value = 0.28;
    input.connect(dest);
    conv.connect(wet).connect(dest);
    r = { input, conv, on: false };
    rooms.set(ctx, r);
  }
  const on = roomOn();
  if (on !== r.on) {
    // when it's off the reverb is disconnected, so it costs nothing
    if (on) r.input.connect(r.conv);
    else r.input.disconnect(r.conv);
    r.on = on;
  }
  return r.input;
}
