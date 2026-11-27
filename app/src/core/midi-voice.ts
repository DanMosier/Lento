/**
 * The shared part of the two "bring your own sound" outputs: your own SoundFont (core/soundfont) and notes sent to
 * a MIDI device or a PC plugin host (core/midi-out). Both take MIDI messages timed on the audio clock, so playback
 * stays in step with the count-in and metronome clicks, which still come from Web Audio.
 *
 * Each part gets its own MIDI channel (the first part played gets channel 1, skipping channel 10, which is drums),
 * with a General MIDI program for its instrument.
 */

interface Pending {
  ch: number;
  midi: number;
  on: number; // audio time
  off: number;
}

export abstract class MidiVoice {
  private channels = new Map<string, number>();
  private pending: Pending[] = [];

  constructor(protected readonly ctx: BaseAudioContext) {}

  /** Sends one MIDI message to sound at audio time `when` (now if that has passed). */
  protected abstract send(bytes: number[], when: number): void;

  /** Called when stopping, from now until `until`: a SoundFont mutes its output there; a MIDI port can't. */
  protected silence(_until: number): void {}

  /** The channel for a part, given the first time it plays, with its program set then. */
  channel(key: string, program: number): number {
    let ch = this.channels.get(key);
    if (ch === undefined) {
      const n = this.channels.size % 15;
      ch = n < 9 ? n : n + 1; // 0..8, 10..15: never 9 (drums)
      this.channels.set(key, ch);
      const now = this.ctx.currentTime;
      this.send([0xc0 | ch, Math.max(0, Math.min(127, program - 1))], now);
      this.send([0xb0 | ch, 7, 100], now); // volume
      this.send([0xb0 | ch, 91, 0], now); // no built-in reverb: Lento's own room sound is used instead
      this.send([0xb0 | ch, 93, 0], now); // no chorus
    }
    return ch;
  }

  /** Plays one note of a part. `level` is 0..1 as in core/sounds (1 = the practised part). */
  note(key: string, program: number, midi: number, when: number, dur: number, level: number): void {
    const ch = this.channel(key, program);
    const now = this.ctx.currentTime;
    if (this.pending.length > 64) this.pending = this.pending.filter((p) => p.off > now);
    const vel = Math.max(1, Math.min(127, Math.round(30 + 90 * level)));
    const off = when + dur;
    this.send([0x90 | ch, midi, vel], when);
    this.send([0x80 | ch, midi, 0], off);
    this.pending.push({ ch, midi, on: when, off });
  }

  /**
   * Stops every note now, including ones already sent to start in the next moment (each gets a note-off just after
   * its start, since a sent message can't be taken back). Returns the audio time after which all is quiet.
   */
  stop(): number {
    const now = this.ctx.currentTime;
    let quiet = now;
    for (const p of this.pending) {
      if (p.off <= now) continue;
      if (p.on > now) {
        this.send([0x80 | p.ch, p.midi, 0], p.on + 0.002);
        quiet = Math.max(quiet, p.on + 0.01);
      } else this.send([0x80 | p.ch, p.midi, 0], now);
    }
    this.pending = [];
    for (const ch of new Set(this.channels.values())) this.send([0xb0 | ch, 123, 0], quiet); // all notes off
    this.silence(quiet + 0.05);
    return quiet;
  }
}
