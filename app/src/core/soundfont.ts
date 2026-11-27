/**
 * Plays scores with your own SoundFont (.sf2 / .sf3), chosen in Settings. Uses SpessaSynth (Apache-2.0), which
 * synthesizes in an AudioWorklet: the work happens on the audio thread, never the page's.
 *
 * This file and the synthesizer load only the first time a score is played with "My SoundFont" chosen, so nobody
 * else downloads them. One synthesizer is made per AudioContext and shared by Practice and the Review window.
 */
import { WorkletSynthesizer } from "spessasynth_lib";
import processorUrl from "spessasynth_lib/dist/spessasynth_processor.min.js?url";
import { MidiVoice } from "./midi-voice";

class SoundFontVoice extends MidiVoice {
  private readonly gain: GainNode;
  private connected = new Set<AudioNode>();

  constructor(
    ctx: BaseAudioContext,
    readonly synth: WorkletSynthesizer,
  ) {
    super(ctx);
    this.gain = ctx.createGain();
    synth.connect(this.gain);
  }

  /** Sends the sound to `out` (Lento's room sound or the speakers) the first time it's asked for. */
  route(out: AudioNode): void {
    if (this.connected.has(out)) return;
    this.connected.add(out);
    this.gain.connect(out);
  }

  protected send(bytes: number[], when: number): void {
    this.synth.sendMessage(bytes, 0, { time: Math.max(when, this.ctx.currentTime) });
  }

  protected silence(until: number): void {
    const g = this.gain.gain;
    const now = this.ctx.currentTime;
    g.cancelScheduledValues(now);
    g.setValueAtTime(0, now);
    g.setValueAtTime(1, until);
  }
}

export type { SoundFontVoice };

/**
 * The synthesizer keeps its own clock by counting the blocks it renders. When the audio thread is busy (reading a
 * SoundFont happens there) blocks are missed and that clock falls behind the page's by a tenth of a second or more:
 * notes would sound late, out of step with the metronome, and stopping would leave a tail. This tiny module, loaded
 * into the audio thread first, sets the synthesizer's clock from the audio thread's own at every block.
 */
const CLOCK_SYNC = `const reg = globalThis.registerProcessor;
globalThis.registerProcessor = (name, Base) => reg(name, class extends Base {
  process(inputs, outputs, params) {
    const s = this.core?.synthesizer;
    if (s && typeof s.currentTime === "number") s.currentTime = currentTime;
    return super.process(inputs, outputs, params);
  }
});`;

async function addModules(ctx: BaseAudioContext): Promise<void> {
  const url = URL.createObjectURL(new Blob([CLOCK_SYNC], { type: "text/javascript" }));
  try {
    await ctx.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  await ctx.audioWorklet.addModule(processorUrl);
}

const made = new WeakMap<BaseAudioContext, { stamp: number; voice: Promise<SoundFontVoice> }>();
const modules = new WeakMap<BaseAudioContext, Promise<void>>();

/**
 * The SoundFont voice for this context with the file `data` (identified by `stamp`). A new stamp (a different file
 * chosen in Settings) replaces the sound bank in the same synthesizer.
 */
export function soundFontVoice(ctx: BaseAudioContext, stamp: number, data: () => Promise<ArrayBuffer | null>): Promise<SoundFontVoice> {
  const have = made.get(ctx);
  if (have?.stamp === stamp) return have.voice;
  const voice = (async () => {
    const old = have ? await have.voice.catch(() => null) : null;
    const buf = await data();
    if (!buf) throw new Error("No SoundFont saved on this device.");
    let synth: WorkletSynthesizer;
    if (old) synth = old.synth;
    else {
      let m = modules.get(ctx);
      if (!m) modules.set(ctx, (m = addModules(ctx)));
      await m;
      synth = new WorkletSynthesizer(ctx, { eventsEnabled: false });
      await synth.isReady;
    }
    await synth.soundBankManager.addSoundBank(buf, "user");
    return old ?? new SoundFontVoice(ctx, synth);
  })();
  made.set(ctx, { stamp, voice });
  voice.catch(() => made.delete(ctx));
  return voice;
}
