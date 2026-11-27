import { describe, expect, it } from "vitest";
import { MidiVoice } from "../src/core/midi-voice";
import { gmProgram } from "../src/core/sounds";
import { isSoundFont } from "../src/core/user-sounds";

class Recorder extends MidiVoice {
  sent: { bytes: number[]; when: number }[] = [];
  silenced: number | null = null;
  constructor(readonly clock: { currentTime: number }) {
    super(clock as unknown as BaseAudioContext);
  }
  protected send(bytes: number[], when: number): void {
    this.sent.push({ bytes, when });
  }
  protected silence(until: number): void {
    this.silenced = until;
  }
}

describe("MIDI voice (your own SoundFont, MIDI out)", () => {
  it("gives each part its own channel with its program, skipping the drum channel", () => {
    const v = new Recorder({ currentTime: 0 });
    const chans = Array.from({ length: 12 }, (_, i) => v.channel(`P${i}`, 43));
    expect(chans).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12]);
    expect(v.channel("P0", 43)).toBe(0); // the same part keeps its channel
    expect(v.sent[0].bytes).toEqual([0xc0, 42]); // program change: General MIDI 43 (cello) is 42 on the wire
  });

  it("sends note on and off at the scheduled times, louder for the practised part", () => {
    const v = new Recorder({ currentTime: 1 });
    v.note("solo", 43, 57, 2, 0.5, 1);
    v.note("piano", 1, 60, 2, 0.5, 0.55);
    const notes = v.sent.filter((m) => (m.bytes[0] & 0xe0) === 0x80);
    expect(notes).toEqual([
      { bytes: [0x90, 57, 120], when: 2 },
      { bytes: [0x80, 57, 0], when: 2.5 },
      { bytes: [0x91, 60, 80], when: 2 },
      { bytes: [0x81, 60, 0], when: 2.5 },
    ]);
  });

  it("stopping ends sounding notes now and cuts off notes already sent for the next moment", () => {
    const clock = { currentTime: 1 };
    const v = new Recorder(clock);
    v.note("solo", 43, 50, 0.5, 2, 1); // sounding
    v.note("solo", 43, 52, 1.2, 1, 1); // starts in 0.2 s
    v.note("solo", 43, 48, 0.2, 0.3, 1); // already over
    v.sent = [];
    const quiet = v.stop();
    expect(v.sent).toContainEqual({ bytes: [0x80, 50, 0], when: 1 });
    expect(v.sent).toContainEqual({ bytes: [0x80, 52, 0], when: 1.202 });
    expect(v.sent.some((m) => m.bytes[1] === 48)).toBe(false);
    expect(quiet).toBeCloseTo(1.21);
    expect(v.silenced).toBeCloseTo(1.26);
    v.sent = [];
    expect(v.stop()).toBe(1); // nothing left to stop
  });
});

describe("gmProgram", () => {
  it("uses the instrument's General MIDI program, then the file's, then piano", () => {
    expect(gmProgram("cello")).toBe(43);
    expect(gmProgram("piano", 43)).toBe(1);
    expect(gmProgram("flute")).toBe(74);
    expect(gmProgram(null, 66)).toBe(66);
    expect(gmProgram(null)).toBe(1);
    expect(gmProgram(null, 300)).toBe(1);
  });
});

describe("isSoundFont", () => {
  const riff = (form: string) => new Blob([new TextEncoder().encode(`RIFF\0\0\0\0${form}rest of file`)]);
  it("accepts SoundFont 2/3 and DLS files and refuses anything else", async () => {
    expect(await isSoundFont(riff("sfbk"))).toBe(true);
    expect(await isSoundFont(riff("DLS "))).toBe(true);
    expect(await isSoundFont(riff("WAVE"))).toBe(false);
    expect(await isSoundFont(new Blob(["hello"]))).toBe(false);
  });
});
