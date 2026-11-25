import { describe, expect, it } from "vitest";
import { estimateDelay } from "../src/practice/latency";

describe("headphone delay", () => {
  const clicks = Array.from({ length: 16 }, (_, i) => 1 + i * 0.75);
  const jitter = [0.012, -0.018, 0.005, 0.02, -0.01, 0.0, -0.015, 0.008, 0.017, -0.004, 0.011, -0.02, 0.003, 0.009, -0.007, 0.014];

  it("finds the delay from taps that follow late sound", () => {
    for (const lateMs of [0, 40, 180, 320]) {
      const taps = clicks.map((c, i) => c + lateMs / 1000 + jitter[i]);
      const r = estimateDelay(clicks, taps)!;
      expect(Math.abs(r.ms - lateMs)).toBeLessThanOrEqual(8);
      expect(r.taps).toBe(13); // the first 3 clicks are for settling in
    }
  });

  it("ignores stray and doubled taps, and gives up with too few", () => {
    const taps = clicks.map((c, i) => c + 0.2 + jitter[i]);
    taps.push(clicks[8] + 0.21, clicks[10] + 0.5 - 0.95); // a double tap and a stray one
    expect(Math.abs(estimateDelay(clicks, taps)!.ms - 200)).toBeLessThanOrEqual(8);
    expect(estimateDelay(clicks, taps.slice(0, 6))).toBeNull();
  });
});
