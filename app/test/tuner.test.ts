import { describe, expect, it } from "vitest";
import { detectPitch, reading } from "../src/tuner/tuner";

describe("tuner", () => {
  it("reads note and cents from a bowed-string-like tone", () => {
    for (const [midi, cents] of [[36, 0], [43, -12], [57, 7], [69, 20]]) {
      const rate = 48000;
      const f = 440 * 2 ** ((midi - 69) / 12 + cents / 1200);
      const x = new Float32Array(4096);
      for (let i = 0; i < x.length; i++) for (let k = 1; k <= 8; k++) x[i] += Math.sin((2 * Math.PI * f * k * i) / rate) / k;
      const r = reading(detectPitch(x, rate)!, 440);
      expect(r.name + r.octave).toBe(["C2", "G2", "A3", "A4"][[36, 43, 57, 69].indexOf(midi)]);
      expect(Math.abs(r.cents - cents)).toBeLessThan(2);
    }
  });
});
