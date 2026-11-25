import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { analyze, DEFAULT_SETTINGS, type Analysis } from "../src/practice/analyze";
import { trackPitch } from "../src/practice/pitch";
import { coloredScore, problemSpots, summaryMarkdown } from "../src/practice/report";
import { render, scoreXml, type Take } from "./synth";

const xml = scoreXml();
const run = (take: Take = {}, settings = DEFAULT_SETTINGS): Analysis => {
  const score = parseScore(xml);
  return analyze(score, trackPitch(render(score, take), settings.a4), settings);
};
const byIndex = (a: Analysis) => new Map(a.results.map((r) => [r.index, r]));

describe("score", () => {
  it("reads the cello part with ties, double stops and tempo", () => {
    const s = parseScore(xml);
    expect(s.partName).toBe("Violoncello");
    expect(s.tempos[0]).toEqual([0, 80]);
    expect(s.measures.length).toBe(9);
    expect(s.timeSignature).toEqual([4, 4]);
    const tied = s.notes.find((n) => n.name === "F#4" && n.measure === "6")!;
    expect(tied.duration).toBe(4);
    expect(tied.elements.length).toBe(2);
    expect(s.notes.filter((n) => n.inChord).map((n) => n.name).sort()).toEqual(["A3", "D3"]);
    expect(s.notes[1].startSec).toBeCloseTo(0.75);
  });
});

describe("analyzer", () => {
  it("finds a clean take in tune and on time", () => {
    const a = run();
    const graded = a.results.filter((r) => r.status !== "double_stop");
    expect(graded.filter((r) => r.status !== "in_tune").map((r) => [r.index, r.status, r.cents])).toEqual([]);
    expect(Math.max(...graded.map((r) => Math.abs(r.cents!)))).toBeLessThan(4);
    expect(graded.filter((r) => r.timing).map((r) => [r.index, r.timingMs])).toEqual([]);
    expect(a.tempoBpm).toBeGreaterThan(66.5);
    expect(a.tempoBpm).toBeLessThan(69.5);
    expect([a.firstMeasure, a.lastMeasure]).toEqual(["1", "9"]);
  });

  it("finds planted mistakes", () => {
    const a = run({ detune: { 2: 30, 7: -15, 16: 100 }, skip: [23], shiftMs: { 18: 150 } });
    const r = byIndex(a);
    expect(r.get(2)!.status).toBe("out_of_tune");
    expect(Math.abs(r.get(2)!.cents! - 30)).toBeLessThan(4);
    expect(r.get(7)!.status).toBe("slightly_off");
    expect(Math.abs(r.get(7)!.cents! + 15)).toBeLessThan(4);
    expect(r.get(16)!.status).toBe("wrong_note");
    expect(r.get(16)!.heard).toBe("Eb3");
    expect(r.get(23)!.status).toBe("missed");
    expect(r.get(18)!.timing).toBe("late");
    const others = a.results.filter((x) => ![2, 7, 16, 23, 18].includes(x.index) && x.status !== "double_stop");
    expect(others.filter((x) => x.status !== "in_tune" || x.timing).map((x) => [x.index, x.status, x.timing])).toEqual([]);
    const spots = problemSpots(a);
    expect(spots.length).toBe(3);
    expect(summaryMarkdown(a)).toContain("F#3 30 cents sharp");
  });

  it("splits repeated notes by rhythm", () => {
    const a = run();
    const spb = 60 / 68;
    const s = [4, 5, 6].map((i) => byIndex(a).get(i)!.onsetSec!);
    expect(Math.abs(s[1] - s[0] - spb)).toBeLessThan(0.06);
    expect(Math.abs(s[2] - s[1] - spb / 2)).toBeLessThan(0.06);
  });

  it("follows slowing down in an echoey room", () => {
    const a = run({ tempo: 76, slowDown: 0.2, reverb: true, detune: { 9: -30 } });
    const off = a.results.filter((r) => r.status !== "double_stop" && r.status !== "in_tune");
    expect(off.map((r) => r.index)).toEqual([9]);
    expect(a.results.filter((r) => r.timing).map((r) => [r.index, r.timingMs])).toEqual([]);
    expect(a.tempoStartBpm! - a.tempoEndBpm!).toBeGreaterThan(6);
    expect(summaryMarkdown(a)).toContain("slowed down");
  });

  it("finds a few measures without being told", () => {
    const a = run({ firstMeasure: 2, lastMeasure: 5 });
    expect([a.firstMeasure, a.lastMeasure]).toEqual(["3", "6"]);
    const inside = a.results.filter((r) => r.status !== "not_played" && r.status !== "double_stop");
    expect(inside.filter((r) => r.status !== "in_tune").map((r) => [r.index, r.status])).toEqual([]);
    expect(a.results.filter((r) => r.note.measureIndex < 2 || r.note.measureIndex > 5).every((r) => r.status === "not_played")).toBe(true);
  });

  it("uses a measure range when given", () => {
    const a = run({ firstMeasure: 2, lastMeasure: 5 }, { ...DEFAULT_SETTINGS, measures: ["3", "6"] });
    expect(new Set(a.results.map((r) => r.measure))).toEqual(new Set(["3", "4", "5", "6"]));
  });

  it("points at the score when a passage is off by one interval", () => {
    const a = run({ detune: { 14: 300, 15: 300, 16: 300, 17: 300 } });
    expect([14, 15, 16, 17].map((i) => byIndex(a).get(i)!.status)).toEqual(Array(4).fill("score_suspect"));
  });

  it("suggests a tuning pitch when everything is sharp", () => {
    const a = run({ overallCents: 20 });
    expect(Math.abs(a.tuningOffsetCents! - 20)).toBeLessThan(3);
    expect(a.warnings.some((w) => w.includes("445 Hz"))).toBe(true);
    const b = run({ overallCents: 20 }, { ...DEFAULT_SETTINGS, a4: 445.1 });
    expect(b.results.filter((r) => r.status !== "double_stop" && r.status !== "in_tune")).toEqual([]);
  });

  it("writes a colored, labelled copy of the score", () => {
    const a = run({ detune: { 2: 30 }, skip: [23] });
    const out = new DOMParser().parseFromString(coloredScore(a), "application/xml");
    const cello = Array.from(out.getElementsByTagName("part")).find((p) => p.getAttribute("id") === "P2")!;
    const colors = Array.from(cello.getElementsByTagName("note")).filter((n) => !n.getElementsByTagName("rest").length).map((n) => n.getAttribute("color"));
    expect(colors.filter((c) => c === "#D0342C").length).toBe(1);
    expect(colors.filter((c) => c === "#8E44AD").length).toBe(1);
    const piano = Array.from(out.getElementsByTagName("part")).find((p) => p.getAttribute("id") === "P1")!;
    expect(piano.getElementsByTagName("note")[0].getAttribute("color")).toBeNull();
    const labels = Array.from(cello.getElementsByTagName("lyric")).map((l) => l.textContent);
    expect(labels.some((t) => t?.includes("+30"))).toBe(true);
    expect(labels.some((t) => t?.includes("miss"))).toBe(true);
  });
});
