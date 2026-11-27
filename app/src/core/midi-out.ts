/**
 * Sends the score's notes to a MIDI output instead of playing them: a hardware keyboard or sound module, or on a PC
 * a virtual MIDI cable (such as loopMIDI) into a program that hosts VST instruments. Web MIDI works in Chrome and
 * Edge (PC and Android), not in Safari.
 *
 * Messages carry timestamps, so the browser sends each one at the moment its note should sound, in step with the
 * metronome clicks.
 */
import { MidiVoice } from "./midi-voice";

let access: Promise<MIDIAccess> | null = null;

/** Asks for MIDI (the browser may show a permission prompt the first time). */
export function midiAccess(): Promise<MIDIAccess> {
  access ??= navigator.requestMIDIAccess({ sysex: false }).catch((e) => {
    access = null;
    throw e;
  });
  return access;
}

export async function midiOutputs(): Promise<MIDIOutput[]> {
  return [...(await midiAccess()).outputs.values()];
}

/** The output called `name`, else the first one, else null. */
export async function findOutput(name: string): Promise<MIDIOutput | null> {
  const outs = await midiOutputs();
  return outs.find((o) => o.name === name) ?? outs[0] ?? null;
}

export class MidiOutVoice extends MidiVoice {
  constructor(
    ctx: BaseAudioContext,
    readonly port: MIDIOutput,
  ) {
    super(ctx);
  }

  /** Performance-clock milliseconds for an audio time, allowing for the speakers' delay as the clicks do. */
  private ms(when: number): number {
    const c = this.ctx as AudioContext;
    const ts = c.getOutputTimestamp?.();
    if (ts?.performanceTime && ts.contextTime !== undefined) return ts.performanceTime + (when - ts.contextTime) * 1000;
    return performance.now() + (when - this.ctx.currentTime) * 1000;
  }

  protected send(bytes: number[], when: number): void {
    try {
      this.port.send(bytes, Math.max(performance.now(), this.ms(when)));
    } catch {
      /* the device was unplugged: notes stop, nothing else breaks */
    }
  }

  /** One short middle C on channel 1, to check the connection from Settings (parts keep their channels). */
  test(): void {
    const now = this.ctx.currentTime;
    this.send([0x90, 60, 100], now + 0.05);
    this.send([0x80, 60, 0], now + 0.65);
  }
}

const made = new Map<string, Promise<MidiOutVoice | null>>();

/** The voice for the output called `name` (or the first output). Null when there are no MIDI outputs. */
export function midiOutVoice(ctx: BaseAudioContext, name: string): Promise<MidiOutVoice | null> {
  let v = made.get(name);
  if (!v) {
    v = findOutput(name).then((port) => (port ? new MidiOutVoice(ctx, port) : null));
    v.then((x) => !x && made.delete(name), () => made.delete(name));
    made.set(name, v);
  }
  return v;
}
