import { describe, expect, it } from "vitest";
import { emptySplit, flagged, isFlagged, mergeSplit, parseSplit, recentlyDone, sameSplit, setSplit } from "../src/convert/split-list";

describe("flag for splitting", () => {
  it("flags, marks done and unflags a PDF", () => {
    let l = setSplit(emptySplit(), "bach", "Suites.pdf", "Bach Suites", "flagged", 10);
    expect(isFlagged(l, "bach", "Suites.pdf")).toBe(true);
    expect(flagged(l).map((e) => e.title)).toEqual(["Bach Suites"]);
    l = setSplit(l, "bach", "Suites.pdf", "Bach Suites", "done", 20);
    expect(isFlagged(l, "bach", "Suites.pdf")).toBe(false);
    expect(flagged(l)).toEqual([]);
    expect(recentlyDone(l).map((e) => e.pdf)).toEqual(["Suites.pdf"]);
    l = setSplit(l, "bach", "Suites.pdf", "Bach Suites", "off", 30);
    expect(recentlyDone(l)).toEqual([]);
  });

  it("returns the same list when nothing changes, so no upload is made", () => {
    const l = setSplit(emptySplit(), "a", "a.pdf", "A", "flagged", 10);
    expect(setSplit(l, "a", "a.pdf", "A", "flagged", 20)).toBe(l);
  });

  it("dates a change after the last one even if the clock is behind", () => {
    const l = setSplit(setSplit(emptySplit(), "a", "a.pdf", "A", "flagged", 100), "a", "a.pdf", "A", "done", 50);
    expect(l.entries["a/a.pdf"].at).toBe(101);
  });

  it("lists the oldest flag first", () => {
    let l = setSplit(emptySplit(), "b", "b.pdf", "B", "flagged", 20);
    l = setSplit(l, "a", "a.pdf", "A", "flagged", 10);
    expect(flagged(l).map((e) => e.piece)).toEqual(["a", "b"]);
  });

  it("merges two devices: the newer change to each PDF wins, so an unflag isn't undone by an older flag", () => {
    const base = setSplit(setSplit(emptySplit(), "a", "a.pdf", "A", "flagged", 10), "b", "b.pdf", "B", "flagged", 10);
    const phone = setSplit(base, "a", "a.pdf", "A", "off", 20);
    const pc = setSplit(setSplit(base, "b", "b.pdf", "B", "done", 30), "c", "c.pdf", "C", "flagged", 30);
    const m = mergeSplit(phone, pc);
    expect(m.entries["a/a.pdf"].state).toBe("off");
    expect(m.entries["b/b.pdf"].state).toBe("done");
    expect(isFlagged(m, "c", "c.pdf")).toBe(true);
    expect(sameSplit(m, mergeSplit(pc, phone))).toBe(true);
  });

  it("parses what's saved and drops nonsense", () => {
    const l = setSplit(emptySplit(), "a", "a.pdf", "A", "flagged", 10);
    expect(sameSplit(parseSplit(JSON.parse(JSON.stringify(l))), l)).toBe(true);
    expect(parseSplit(null)).toEqual(emptySplit());
    const bad = parseSplit({ entries: { x: { piece: "x", pdf: "x.pdf", at: 1, state: "maybe" }, y: { piece: 3 }, z: null } });
    expect(bad.entries).toEqual({});
  });
});
