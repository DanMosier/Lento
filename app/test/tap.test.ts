import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { Player } from "../src/practice/player";
import { beatAt, measureAt, tapPlay, type BeatPlace } from "../src/practice/tap";
import { scoreXml } from "./synth";

// two systems of one staff each: beats 0..3 on the first (y 100..140), 4..7 on the second (y 300..340)
const places: BeatPlace[] = [0, 1, 2, 3, 4, 5, 6, 7].map((b) => ({ beat: b, x: 50 + (b % 4) * 100, top: b < 4 ? 100 : 300, bottom: b < 4 ? 140 : 340 }));

describe("tap a note", () => {
  it("finds the note on the staff tapped, nearest side to side", () => {
    expect(beatAt(places, 155, 120)).toBe(1);
    expect(beatAt(places, 340, 320)).toBe(7);
    expect(beatAt(places, 260, 160)).toBe(2); // a ledger line below the first staff
    expect(beatAt(places, 260, 280)).toBe(6); // just above the second
    expect(beatAt(places, 100, 10)).toBeNull(); // the title
    expect(beatAt([], 100, 120)).toBeNull();
  });

  it("finds the measure a beat is in", () => {
    const starts = [0, 4, 8, 12];
    expect(measureAt(starts, 0)).toBe(0);
    expect(measureAt(starts, 3.99)).toBe(0);
    expect(measureAt(starts, 4)).toBe(1);
    expect(measureAt(starts, 13)).toBe(3);
  });

  it("plays from the note to the end of the chosen measures, or to the end of the score from outside them", () => {
    const starts = [0, 4, 8, 12, 16];
    expect(tapPlay(starts, 1, 2, 9, true)).toEqual({ fromMeasure: 1, toMeasure: 2, fromBeat: 9, loop: true });
    expect(tapPlay(starts, 1, 2, 13, true)).toEqual({ fromMeasure: 3, toMeasure: 4, fromBeat: 13, loop: false });
    expect(tapPlay(starts, 1, 2, 1, false)).toEqual({ fromMeasure: 0, toMeasure: 4, fromBeat: 1, loop: false });
  });
});

describe("playing from a tapped note", () => {
  function fakeCtx() {
    return { currentTime: 10, state: "running", destination: {} } as unknown as AudioContext & { currentTime: number };
  }

  it("starts at the note, then loops from the first chosen measure", async () => {
    const s = parseScore(scoreXml(60)); // 60 bpm: a beat a second
    const ctx = fakeCtx();
    const p = new Player(ctx);
    const from = s.measureStarts[1];
    const end = s.measureStarts[3];
    await p.play({ parts: [s], fromMeasure: 1, toMeasure: 2, fromBeat: from + 2, tempoFactor: 1, countIn: false, loop: true, click: 0, mute: true });
    expect(p.firstBeatTime).toBeCloseTo(10.1, 3);
    ctx.currentTime = 10.1 + 0.5;
    expect(p.currentBeat()).toBeCloseTo(from + 2.5, 2);
    ctx.currentTime = 10.1 + (end - from - 2) + 0.5; // past the end: round again from the first chosen measure
    expect(p.currentBeat()).toBeCloseTo(from + 0.5, 2);
    p.stop();
  });

  it("is silent through the count-in, then starts at the note", async () => {
    const s = parseScore(scoreXml(60));
    const ctx = fakeCtx();
    const p = new Player(ctx);
    p.click = () => {}; // no audio nodes in the test
    const from = s.measureStarts[0];
    await p.play({ parts: [s], fromMeasure: 0, toMeasure: s.measures.length - 1, fromBeat: from + 3, tempoFactor: 1, countIn: true, loop: false, click: 0, mute: true });
    const beats = s.timeSignature[0];
    expect(p.firstBeatTime).toBeCloseTo(10.1 + beats, 3);
    ctx.currentTime = 10.1 + beats - 0.5;
    expect(p.currentBeat()).toBeNull();
    ctx.currentTime = 10.1 + beats + 0.25;
    expect(p.currentBeat()).toBeCloseTo(from + 3.25, 2);
    p.stop();
  });
});
