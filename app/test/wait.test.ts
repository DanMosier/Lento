import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { celloWhere, WaitJudge, waitSteps, type WaitStep } from "../src/practice/wait";
import { scoreXml } from "./synth";

const step = (midis: number[], beat: number): WaitStep => ({ beat, midis, notes: [], measure: "1", measureIndex: 0, beatInMeasure: beat, tries: 0, ms: 0 });
const opts = { cents: 25, holdMs: 150 };

/** Feeds `ms` of a steady pitch, one frame every 40 ms. Returns the events. */
function hold(j: WaitJudge, midi: number | null, ms: number, t: { now: number }, rms = 0.3): string[] {
  const out: string[] = [];
  for (const end = t.now + ms; t.now < end; t.now += 40) {
    const ev = j.feed(midi, rms, t.now);
    if (ev) out.push(ev);
  }
  return out;
}

describe("wait mode", () => {
  it("makes one step per note, measure range only", () => {
    const s = parseScore(scoreXml());
    const all = waitSteps(s, 0, s.measures.length - 1);
    expect(all.length).toBe(new Set(s.notes.map((n) => n.beat)).size);
    expect(all.reduce((k, x) => k + x.notes.length, 0)).toBe(s.notes.length);
    const first = waitSteps(s, 0, 0);
    expect(first.every((x) => x.measureIndex === 0)).toBe(true);
    expect(first.length).toBeGreaterThan(0);
  });

  it("moves on once the right note is held, not on a passing touch", () => {
    const j = new WaitJudge([step([48], 0), step([50], 1)], opts);
    const t = { now: 0 };
    expect(hold(j, 48.1, 80, t)).toEqual([]); // too short
    expect(hold(j, null, 40, t)).toEqual([]);
    expect(hold(j, 48.1, 200, t)).toEqual(["advance"]);
    expect(j.index).toBe(1);
    expect(hold(j, 50.05, 200, t)).toEqual(["done"]);
  });

  it("counts a held wrong note once as a wrong try", () => {
    const j = new WaitJudge([step([48], 0)], opts);
    const t = { now: 0 };
    expect(hold(j, 49, 600, t)).toEqual(["wrong"]);
    expect(hold(j, 47, 600, t)).toEqual(["wrong"]);
    expect(hold(j, 48.5, 300, t)).toEqual(["wrong"]); // 50 cents off is not close enough
    hold(j, 48, 200, t);
    expect(j.done).toBe(true);
    expect(j.steps[0].tries).toBe(3);
    expect(j.hardest().length).toBe(1);
  });

  it("needs a new attack for a repeated note", () => {
    const j = new WaitJudge([step([55], 0), step([55], 1)], opts);
    const t = { now: 0 };
    expect(hold(j, 55, 1000, t)).toEqual(["advance"]); // one long note ticks off only one
    expect(hold(j, 55, 40, t, 0.1)).toEqual([]); // bow change: the level dips...
    expect(hold(j, 55, 200, t, 0.3)).toEqual(["done"]); // ...and the new stroke counts
  });

  it("accepts either note of a double stop, and Skip moves on", () => {
    const j = new WaitJudge([step([50, 57], 0), step([60], 1)], opts);
    const t = { now: 0 };
    expect(hold(j, 57, 200, t)).toEqual(["advance"]);
    expect(j.skip(t.now)).toBe("done");
  });

  it("names where to play on the cello", () => {
    expect(celloWhere(36)).toBe("C string, open");
    expect(celloWhere(45)).toBe("G string, 1st finger");
    expect(celloWhere(55)).toBe("D string, 4th finger");
    expect(celloWhere(57)).toBe("A string, open");
    expect(celloWhere(66)).toBe("A string, upper position");
  });
});
