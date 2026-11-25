import { describe, expect, it } from "vitest";
import { parseScore } from "../src/core/score";
import { clearNote, emptyMarks, glyph, marksIn, newer, noteKey, parseMarks, toggleMark } from "../src/practice/marks";
import { scoreXml } from "./synth";

describe("score marks", () => {
  const s = parseScore(scoreXml());
  const [a, b] = s.notes.map((n) => noteKey(s.partId, n));

  it("addresses notes by part, measure, beat and pitch", () => {
    expect(a).toMatch(new RegExp(`^${s.partId}/0:0:\\d+$`));
    expect(new Set(s.notes.map((n) => noteKey(s.partId, n))).size).toBe(s.notes.length);
  });

  it("adds, replaces and takes off marks", () => {
    let m = emptyMarks("x.musicxml");
    m = toggleMark(m, { note: a, kind: "finger", value: "1" });
    m = toggleMark(m, { note: a, kind: "finger", value: "3" }); // replaces the 1
    m = toggleMark(m, { note: a, kind: "down" });
    m = toggleMark(m, { note: a, kind: "up" }); // up replaces down
    m = toggleMark(m, { note: b, kind: "highlight" });
    expect(m.marks.map((x) => `${x.kind}${x.value ?? ""}`).sort()).toEqual(["finger3", "highlight", "up"]);
    m = toggleMark(m, { note: b, kind: "highlight" }); // the same mark again takes it off
    expect(m.marks.some((x) => x.kind === "highlight")).toBe(false);
    m = toggleMark(m, { note: b, kind: "text", value: "  " }); // empty text adds nothing
    expect(m.marks).toHaveLength(2);
    m = clearNote(m, a);
    expect(m.marks).toHaveLength(0);
  });

  it("keeps the newer copy and drops marks for notes that aren't in the score", () => {
    const old = { ...emptyMarks("x"), updated: "2026-11-01T00:00:00.000Z" };
    const fresh = toggleMark(old, { note: a, kind: "finger", value: "2" }, new Date("2026-11-02T00:00:00Z"));
    expect(newer(old, fresh)).toBe(fresh);
    expect(newer(fresh, old)).toBe(fresh);
    expect(newer(null, old)).toBe(old);
    const withGhost = toggleMark(fresh, { note: "P1/99:0:60", kind: "finger", value: "1" });
    expect([...marksIn(withGhost, s).keys()]).toEqual([a]);
    expect(parseMarks(JSON.stringify(withGhost))!.marks).toHaveLength(2);
    expect(parseMarks("{}")).toBeNull();
    expect(glyph({ note: a, kind: "down" })).toBe("⊓");
  });
});
