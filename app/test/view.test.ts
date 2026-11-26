import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { analyze, DEFAULT_SETTINGS } from "../src/practice/analyze";
import { trackPitch } from "../src/practice/pitch";
import { marksIn, noteKey, toggleMark, emptyMarks } from "../src/practice/marks";
import { applyView, cleanView, fifthsFor, moveNote, transposeLabel } from "../src/practice/view";
import { cleanPitch, cleanTiming } from "../src/core/tolerance";
import { render, scoreXml } from "./synth";

const xml = scoreXml();
const doc = () => new DOMParser().parseFromString(xml, "application/xml");
const viewed = (transpose: number, clef: Parameters<typeof applyView>[1]["clef"] = "written", parts = ["P1", "P2"]) => {
  const d = doc();
  applyView(d, { transpose, clef }, parts, "P2");
  return d;
};
const tags = (d: Document, part: string, tag: string) =>
  Array.from(d.querySelectorAll(`part[id="${part}"] ${tag}`)).map((e) => e.textContent?.replace(/\s+/g, ""));

describe("transpose", () => {
  it("moves every note by the semitones asked, in every shown part", () => {
    const plain = parseScore(xml);
    for (const t of [-12, -7, -5, -1, 1, 2, 3, 6, 11, 12]) {
      const d = viewed(t);
      const s = parseScore(d, "P2");
      expect(s.notes.map((n) => n.midi)).toEqual(plain.notes.map((n) => n.midi + t));
      expect(s.notes.map((n) => n.duration)).toEqual(plain.notes.map((n) => n.duration)); // ties still merge
      expect(parseScore(d, "P1").notes[0].midi).toBe(72 + t);
    }
  });

  it("spells notes for the new key and changes the key signature", () => {
    // D major (2 sharps) up a whole step is E major (4 sharps): F# becomes G#, C# becomes D#
    const d = viewed(2);
    expect(tags(d, "P2", "key fifths")).toEqual(["4"]);
    expect(tags(d, "P2", "pitch").slice(0, 4)).toEqual(["E3", "F13", "G13", "A3"]);
    // down a half step: D major to Db major (5 flats), not C# major (7 sharps)
    expect(tags(viewed(-1), "P2", "key fifths")).toEqual(["-5"]);
    expect(tags(viewed(-1), "P2", "pitch")[0]).toBe("D-13");
  });

  it("picks the spelling with fewer sharps or flats", () => {
    expect(fifthsFor(1, [0])).toBe(-5); // C up a half step: Db major, not C# major
    expect(fifthsFor(2, [2])).toBe(2); // D to E
    expect(fifthsFor(-2, [-3])).toBe(-2); // Eb to Db
    expect(fifthsFor(12, [3])).toBe(0);
    expect(moveNote("B", 0, 3, 1, -5)).toEqual({ step: "C", alter: 0, octave: 4 }); // octave follows the pitch
    expect(moveNote("C", 0, 4, -1, 5)).toEqual({ step: "B", alter: 0, octave: 3 });
    expect(moveNote("F", 2, 4, 1, 7)).toEqual({ step: "G", alter: 1, octave: 4 }); // F double-sharp + 1: no triple sharp
  });

  it("leaves parts that aren't shown alone", () => {
    const d = viewed(3, "written", ["P2"]);
    expect(parseScore(d, "P1").notes[0].midi).toBe(72);
  });

  it("checks a take against the transposed notes", () => {
    // play the score a fourth higher: against the transposed score it is in tune, against the written one it isn't
    const up = parseScore(viewed(5), "P2");
    const take = trackPitch(render(up), DEFAULT_SETTINGS.a4);
    const right = analyze(parseScore(viewed(5), "P2"), take, DEFAULT_SETTINGS).results.filter((r) => r.status !== "double_stop");
    expect(right.filter((r) => r.status === "in_tune").length / right.length).toBeGreaterThan(0.85);
    const wrong = analyze(parseScore(xml), take, DEFAULT_SETTINGS).results.filter((r) => r.status !== "double_stop");
    expect(wrong.filter((r) => r.status === "in_tune").length / wrong.length).toBeLessThan(0.4);
  });

  it("keeps marks on their notes when transposed", () => {
    const plain = parseScore(xml);
    const key = noteKey(plain.partId, plain.notes[3]);
    const marks = toggleMark(emptyMarks("x"), { note: key, kind: "finger", value: "2" });
    const up = parseScore(viewed(4), "P2");
    expect(noteKey(up.partId, up.notes[3], 4)).toBe(key);
    expect([...marksIn(marks, up, 4).keys()]).toEqual([key]);
    expect(marksIn(marks, up).size).toBe(0);
  });

  it("names the intervals", () => {
    expect(transposeLabel(0)).toBe("As written");
    expect(transposeLabel(2)).toBe("Up a whole step (+2)");
    expect(transposeLabel(-12)).toBe("Down an octave (-12)");
  });
});

describe("clef", () => {
  it("changes only how notes are drawn, never their pitch", () => {
    const plain = parseScore(xml).notes.map((n) => n.midi);
    for (const clef of ["treble", "tenor", "alto", "bass"] as const) {
      const d = viewed(0, clef);
      expect(parseScore(d, "P2").notes.map((n) => n.midi)).toEqual(plain);
    }
    expect(tags(viewed(0, "tenor"), "P2", "clef")).toEqual(["C4"]);
    expect(tags(viewed(0, "treble"), "P2", "clef")).toEqual(["G2"]);
  });

  it("replaces clef changes and adds a clef when the file has none", () => {
    const [head, cello] = xml.split('<part id="P2">');
    const withChange = `${head}<part id="P2">${cello.replace('<measure number="5">', '<measure number="5"><attributes><clef><sign>C</sign><line>4</line></clef></attributes>')}`;
    const d = new DOMParser().parseFromString(withChange, "application/xml");
    applyView(d, { transpose: 0, clef: "bass" }, ["P2"], "P2");
    expect(tags(d, "P2", "clef")).toEqual(["F4", "F4"]);
    const p1 = doc();
    applyView(p1, { transpose: 0, clef: "bass" }, ["P1"], "P1"); // the piano part has no clef element
    expect(tags(p1, "P1", "clef")).toEqual(["F4"]);
    expect(parseScore(p1, "P1").notes[0].midi).toBe(72);
  });

  it("cleans up saved views", () => {
    expect(cleanView(null)).toEqual({ transpose: 0, clef: "written" });
    expect(cleanView({ transpose: 40, clef: "nonsense" as never })).toEqual({ transpose: 12, clef: "written" });
    expect(cleanView({ transpose: -3.4, clef: "tenor" })).toEqual({ transpose: -3, clef: "tenor" });
  });
});

describe("custom tolerance windows", () => {
  it("keeps windows sensible", () => {
    expect(cleanPitch({ good: 12, ok: 30 })).toEqual({ good: 12, ok: 30 });
    expect(cleanPitch({ good: 30, ok: 20 })).toEqual({ good: 30, ok: 31 }); // slightly off is always wider
    expect(cleanPitch({ good: 0.2, ok: 999 })).toEqual({ good: 1, ok: 60 });
    expect(cleanPitch(null)).toEqual({ good: 10, ok: 25 });
    expect(cleanTiming(5)).toBe(20);
    expect(cleanTiming("135")).toBe(135);
    expect(cleanTiming(undefined)).toBe(100);
  });

  it("judges a take by the custom windows", () => {
    const score = () => parseScore(xml);
    const take = trackPitch(render(score(), { detune: { 0: 15, 1: 15, 2: 15 } }), 440);
    const tight = analyze(score(), take, { ...DEFAULT_SETTINGS, goodCents: 10, okCents: 25 }).results.slice(0, 3);
    const loose = analyze(score(), take, { ...DEFAULT_SETTINGS, goodCents: 22, okCents: 40 }).results.slice(0, 3);
    expect(tight.every((r) => r.status === "slightly_off")).toBe(true);
    expect(loose.every((r) => r.status === "in_tune")).toBe(true);
  });
});
