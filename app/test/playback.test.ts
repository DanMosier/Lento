import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { impulse } from "../src/core/room";
import { noteShapes } from "../src/practice/player";
import { scoreXml } from "./synth";

describe("natural playback", () => {
  it("joins back-to-back notes of different pitch, and varies every note a little", () => {
    const s = parseScore(scoreXml());
    const shapes = noteShapes(s);
    expect(shapes.size).toBe(s.notes.length);
    const varies = [...shapes.values()].map((x) => x.vary!);
    expect(varies.every((v) => v >= 0 && v < 1)).toBe(true);
    expect(new Set(varies.map((v) => v.toFixed(3))).size).toBeGreaterThan(s.notes.length / 2);
    for (let i = 1; i < s.notes.length; i++) {
      const [a, b] = [s.notes[i - 1], s.notes[i]];
      if (a.inChord || b.inChord || a.voice !== b.voice) continue;
      const joined = a.midi !== b.midi && Math.abs(a.beat + a.duration - b.beat) < 1e-3;
      expect(!!shapes.get(b)!.legatoIn).toBe(joined);
      expect(!!shapes.get(a)!.legatoOut).toBe(joined);
    }
  });

  it("makes a room echo that dies away", () => {
    const fake = { sampleRate: 8000, createBuffer: (ch: number, n: number) => ({ length: n, ch: Array.from({ length: ch }, () => new Float32Array(n)), getChannelData(i: number) { return this.ch[i]; } }) };
    const ir = impulse(fake as unknown as BaseAudioContext, 1.6) as unknown as { getChannelData(i: number): Float32Array; length: number };
    const d = ir.getChannelData(0);
    const energy = (a: number, b: number) => d.slice(a, b).reduce((s, v) => s + v * v, 0);
    expect(energy(0, 1600)).toBeGreaterThan(20 * energy(8000, 9600));
    expect(d.slice(0, 90).every((v) => v === 0)).toBe(true); // a short pre-delay
    expect(ir.getChannelData(1)[500]).not.toBe(d[500]); // left and right differ, for width
  });
});
