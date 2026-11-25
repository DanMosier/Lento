/**
 * Recorded instrument sounds for playback (VS Chamber Orchestra: Community Edition, CC0), built by
 * scripts/build_sounds.py into public/sounds/. Each instrument is one small Opus file per loudness layer
 * holding a recording every few semitones; notes in between are pitch-shifted, and sustained instruments
 * loop a crossfaded stretch so notes last as long as the score says.
 *
 * Nothing here loads at startup. A pack downloads the first time a score needs it, in the background, and
 * is kept in the browser's Cache Storage so it works offline. Until it is ready, playback uses the synth.
 */
import { store } from "./app";
import { timed } from "./perf";

export const SOUND_CACHE = "lento-sounds-v1";
const BASE = "sounds/";

interface PackNote {
  key: number;
  lo: number;
  hi: number;
  start: number;
  end: number;
  loopStart?: number;
  loopEnd?: number;
  tune?: number; // cents
}
interface IndexLayer {
  file: string;
  vel: number;
  bytes: number;
  notes: PackNote[];
}
interface SoundIndex {
  instruments: Record<string, { loop: boolean; layers: Record<string, IndexLayer> }>;
}
interface Layer {
  vel: number;
  buffer: AudioBuffer;
  notes: PackNote[];
}
interface Pack {
  loop: boolean;
  layers: Layer[]; // loudest first
}

/** How a note joins its neighbours, and a steady per-note number (0..1) for small differences between notes. */
export interface NoteShape {
  legatoIn?: boolean;
  legatoOut?: boolean;
  vary?: number;
}

export type SoundQuality = "synth" | "light" | "full";

/** The sound setting from Settings, with "auto" decided by the device: phones get the light packs. */
export function soundQuality(): SoundQuality {
  const v = store.get<string>("sound") ?? "auto";
  if (v === "synth" || v === "light" || v === "full") return v;
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const phone = matchMedia?.("(pointer: coarse)").matches && Math.min(screen.width, screen.height) < 700;
  return phone || mem < 4 ? "light" : "full";
}

// Part names in English, Italian, German and French, then General MIDI program numbers (1-based).
const BY_NAME: [RegExp, string][] = [
  [/violoncell|\bcello|\bvc\b|\bvlc\b/i, "cello"],
  [/contrabass|kontrabass|double bass|contrebasse|\bbass[io]?\b|\bcb\b|\bkb\b/i, "contrabass"],
  [/violin|violino|geige|violon\b|\bvn\b|\bvln?\b/i, "violin"],
  [/viola|bratsche|\bvla?\b/i, "viola"],
  [/piccolo|flute|flauto|flauti|flöte|flote|\bfl\b/i, "flute"],
  [/oboe|oboi|hautbois|\bob\b/i, "oboe"],
  [/clarinet|clarinetto|clarinetti|klarinette|\bcl\b/i, "clarinet"],
  [/bassoon|fagott|fagotto|fagotti|basson|\bbn\b|\bfg\b/i, "bassoon"],
  [/\bhorn|corno|corni|\bcor\b|\bhn\b/i, "horn"],
  [/trombon|posaune|\btbn\b|\btrb\b/i, "trombone"],
  [/trumpet|tromba|trombe|trompete|trompette|\btpt\b|\btr\b/i, "trumpet"],
  [/tuba/i, "tuba"],
  [/timpan|pauke|timbales/i, "timpani"],
  [/harp|arpa|harfe|harpe/i, "harp"],
  [/piano|klavier|pianoforte|keyboard|celesta/i, "piano"],
];
const BY_PROGRAM: [number, number, string][] = [
  [1, 8, "piano"],
  [41, 41, "violin"],
  [42, 42, "viola"],
  [43, 43, "cello"],
  [44, 44, "contrabass"],
  [47, 47, "harp"],
  [48, 48, "timpani"],
  [57, 57, "trumpet"],
  [58, 58, "trombone"],
  [59, 59, "tuba"],
  [61, 61, "horn"],
  [69, 69, "oboe"],
  [71, 71, "bassoon"],
  [72, 72, "clarinet"],
  [73, 74, "flute"],
];

/** Which sound pack fits a part, from its name or MIDI program. Unknown instruments use the synth. */
export function instrumentFor(name: string, program?: number | null): string | null {
  for (const [re, id] of BY_NAME) if (re.test(name)) return id;
  if (program) for (const [lo, hi, id] of BY_PROGRAM) if (program >= lo && program <= hi) return id;
  return null;
}

async function cachedFetch(url: string): Promise<Response> {
  let cache: Cache | null = null;
  try {
    cache = await caches.open(SOUND_CACHE);
    const hit = await cache.match(url);
    if (hit) return hit;
  } catch {
    /* no Cache Storage (private window): just download */
  }
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  if (cache) await cache.put(url, r.clone()).catch(() => {});
  return r;
}

/** Sound packs for one AudioContext. `want()` starts downloads; `play()` uses whatever has arrived. */
export class SoundBank {
  private index: Promise<SoundIndex> | null = null;
  private packs = new Map<string, Pack>();
  private loading = new Map<string, Promise<Pack | null>>();
  private quality: SoundQuality = "light";

  constructor(private readonly ctx: BaseAudioContext) {}

  /** Starts loading these instruments' packs in the background. Resolves once all have loaded or failed. */
  want(instruments: (string | null)[], quality = soundQuality()): Promise<void> {
    if (quality === "synth") return Promise.resolve();
    if (quality !== this.quality) {
      this.quality = quality;
      this.loading.clear();
      this.packs.clear();
    }
    const ids = [...new Set(instruments.filter((x): x is string => !!x))];
    return Promise.all(ids.map((id) => this.load(id))).then(() => undefined);
  }

  ready(instrument: string | null): boolean {
    return !!instrument && this.packs.has(instrument);
  }

  private load(id: string): Promise<Pack | null> {
    let p = this.loading.get(id);
    if (!p) {
      const quality = this.quality;
      p = timed("load-sound", () => this.fetchPack(id, quality)).then(
        (pack) => {
          if (pack && quality === this.quality) this.packs.set(id, pack);
          return pack;
        },
        () => null, // offline and never downloaded, or no Opus support: keep the synth
      );
      this.loading.set(id, p);
    }
    return p;
  }

  private async fetchPack(id: string, quality: SoundQuality): Promise<Pack | null> {
    this.index ??= cachedFetch(`${BASE}index.json`).then((r) => r.json() as Promise<SoundIndex>);
    const entry = (await this.index).instruments[id];
    if (!entry) return null;
    const names = quality === "full" ? Object.keys(entry.layers) : Object.keys(entry.layers).slice(0, 1);
    const layers = await Promise.all(
      names.map(async (n) => {
        const l = entry.layers[n];
        const data = await (await cachedFetch(BASE + l.file)).arrayBuffer();
        return { vel: l.vel, notes: l.notes, buffer: await this.ctx.decodeAudioData(data) };
      }),
    );
    layers.sort((a, b) => b.vel - a.vel);
    return { loop: entry.loop, layers };
  }

  /**
   * Schedules one note. Returns false when that instrument's pack isn't loaded (the caller then uses the synth).
   * `level` is 0..1 (1 = the practised part, softer for accompaniment). `shape` joins it smoothly to its neighbours
   * and gives each note a slight difference, the way no two bow strokes or breaths are the same.
   */
  play(
    instrument: string | null,
    midi: number,
    when: number,
    dur: number,
    level: number,
    out: AudioNode,
    track: (n: AudioScheduledSourceNode) => void,
    shape: NoteShape = {},
  ): boolean {
    const pack = instrument ? this.packs.get(instrument) : undefined;
    if (!pack) return false;
    const vel = 40 + 80 * level;
    const layer = pack.layers.find((l, i) => i === pack.layers.length - 1 || vel >= (l.vel + pack.layers[i + 1].vel) / 2)!;
    let note = layer.notes.find((n) => midi >= n.lo && midi <= n.hi);
    if (!note) note = layer.notes.reduce((a, b) => (Math.abs(b.key - midi) < Math.abs(a.key - midi) ? b : a));
    const ctx = this.ctx;
    const v = shape.vary ?? 0.5; // 0..1, steady per note
    const src = ctx.createBufferSource();
    src.buffer = layer.buffer;
    // up to ±3 cents and ±6% loudness, so repeated notes don't sound like one copy played over and over
    src.playbackRate.value = 2 ** ((midi - note.key) / 12 + ((note.tune ?? 0) + (v - 0.5) * 6) / 1200);
    const sustained = pack.loop && note.loopStart !== undefined && note.loopEnd !== undefined;
    // A note slurred from the one before skips its own attack and fades in under the previous note's tail;
    // a note followed straight away by another rings on a little into it, so there's no gap between them.
    const legIn = sustained && !!shape.legatoIn;
    const legOut = sustained && !!shape.legatoOut;
    // (bowed and blown recordings take a few tenths of a second to reach full tone, so it starts well in)
    const offset = legIn ? Math.max(0, Math.min(0.3, note.loopStart! - note.start - 0.05)) : v * 0.01;
    const length = (note.end - note.start - offset) / src.playbackRate.value; // seconds of sample at this pitch
    const release = legOut ? 0.1 : pack.loop ? 0.12 : 0.35;
    let stopAt: number;
    if (sustained) {
      src.loop = true;
      src.loopStart = note.loopStart!;
      src.loopEnd = note.loopEnd!;
      stopAt = when + dur + release;
    } else stopAt = when + Math.min(length, dur + release);
    const env = ctx.createGain();
    const peak = 0.55 * (0.45 + 0.55 * level) * (0.94 + 0.12 * v);
    if (legIn) {
      env.gain.setValueAtTime(0, when);
      env.gain.linearRampToValueAtTime(peak, when + 0.05);
    } else env.gain.setValueAtTime(peak, when);
    env.gain.setValueAtTime(peak, Math.max(when + (legIn ? 0.05 : 0), stopAt - release));
    env.gain.linearRampToValueAtTime(0, stopAt);
    src.connect(env).connect(out);
    src.start(when, note.start + offset);
    src.stop(stopAt + 0.01);
    track(src);
    return true;
  }
}
