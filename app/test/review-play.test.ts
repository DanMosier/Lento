import { describe, expect, it } from "vitest";
import { readParts } from "../src/convert/review-play";
import { partInstrument } from "../src/core/player";
import { scoreXml } from "./synth";

describe("Review window playback", () => {
  it("reads every part with notes, each with its own instrument", () => {
    const parts = readParts(scoreXml());
    expect(parts.map((p) => p.partId)).toEqual(["P1", "P2"]);
    expect(parts.map(partInstrument)).toEqual(["piano", "cello"]);
    expect(parts[1].notes.length).toBeGreaterThan(20);
    expect(parts[0].measures.length).toBe(parts[1].measures.length);
  });

  it("leaves out parts with no notes", () => {
    const xml = scoreXml().replace(/<note><pitch><step>C<\/step><octave>5<\/octave><\/pitch><duration>4<\/duration><type>whole<\/type><\/note>/, "<note><rest/><duration>4</duration><type>whole</type></note>");
    expect(readParts(xml).map((p) => p.partId)).toEqual(["P2"]);
  });
});
