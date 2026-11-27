import { describe, expect, it } from "vitest";
import { barPage, pageXml, serialize, setClef, setInstrument, setKey, setTime, staves, unknownParts, warnings } from "../src/convert/fixes";

const note = (step: string, octave: number, extra = "", accidental = "") =>
  `<note><pitch><step>${step}</step>${extra}<octave>${octave}</octave></pitch><duration>1</duration>${accidental ? `<accidental>${accidental}</accidental>` : ""}</note>`;

// homr's way: a one-staff part called Voice, read in treble clef, with the clef repeated at each new system
function score(): Document {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name>
<score-instrument id="P1-I1"><instrument-name>Voice</instrument-name><instrument-sound>voice</instrument-sound></score-instrument>
<midi-instrument id="P1-I1"><midi-channel>1</midi-channel><midi-program>54</midi-program></midi-instrument></score-part></part-list>
<part id="P1">
<measure number="1"><attributes><divisions>1</divisions><key><fifths>-1</fifths></key><time><beats>2</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>${note("E", 4)}${note("B", 4, "<alter>-1</alter>")}</measure>
<measure number="2"><attributes><clef><sign>G</sign><line>2</line></clef></attributes>${note("G", 4, "<alter>1</alter>", "sharp")}${note("G", 4, "<alter>1</alter>")}</measure>
<measure number="3"><attributes><clef><sign>C</sign><line>4</line></clef></attributes>${note("A", 3)}${note("D", 4)}</measure>
</part></score-partwise>`;
  return new DOMParser().parseFromString(xml, "application/xml");
}

const pitches = (doc: Document, m: number) =>
  Array.from(doc.querySelectorAll(`measure:nth-of-type(${m}) note pitch`)).map(
    (p) => `${p.querySelector("step")!.textContent}${({ "1": "#", "-1": "b" } as Record<string, string>)[p.querySelector("alter")?.textContent ?? ""] ?? ""}${p.querySelector("octave")!.textContent}`,
  );

describe("quick fixes", () => {
  it("finds the staves and asks which instrument an unnamed part is, assuming none", () => {
    const doc = score();
    expect(staves(doc)).toEqual([{ part: "P1", name: "Voice", staff: 1, staves: 1, clef: "G2" }]);
    expect(unknownParts(doc).map((s) => s.part)).toEqual(["P1"]);
    expect(warnings(doc)).toEqual([]); // no instrument known, so no clef counts as unusual
    setInstrument(doc, "P1", "Violin");
    expect(unknownParts(doc)).toEqual([]);
    expect(warnings(doc)).toEqual([]); // treble is right for a violin
  });

  it("asks about the converter's Part 2 too", () => {
    const doc = new DOMParser().parseFromString(serialize(score()).replace(/>Voice</g, ">Part 2<"), "application/xml");
    expect(unknownParts(doc).map((s) => s.name)).toEqual(["Part 2"]);
  });

  it("renames the part and its sound", () => {
    const doc = score();
    setInstrument(doc, "P1", "Cello");
    expect(doc.querySelector("part-name")!.textContent).toBe("Cello");
    expect(doc.querySelector("instrument-sound")!.textContent).toBe("strings.cello");
    expect(doc.querySelector("midi-program")!.textContent).toBe("43");
    expect(warnings(doc)).toEqual(["Cello starts in treble clef, which is unusual for it. If the PDF shows another clef, change the clef below (the notes move with it)."]);
  });

  it("changes a misread treble clef to bass up to the next real clef change, moving the notes with it", () => {
    const doc = score();
    const to = setClef(doc, "P1", 1, 1, "F4");
    expect(to).toBe(2);
    // same lines and spaces: E4 (bottom line in treble) is G2 in bass; the key's B flat becomes D, which is natural
    expect(pitches(doc, 1)).toEqual(["G2", "D3"]);
    // a printed sharp carries through the measure, now on the note's new name
    expect(pitches(doc, 2)).toEqual(["B#2", "B#2"]);
    expect(pitches(doc, 3)).toEqual(["A3", "D4"]); // tenor clef section untouched
    const clefs = Array.from(doc.querySelectorAll("clef")).map((c) => c.textContent);
    expect(clefs).toEqual(["F4", "C4"]); // the repeated treble clef in measure 2 is gone
    expect(staves(doc)[0].clef).toBe("F4");
  });

  it("can change only the clef, leaving the notes as they are", () => {
    const doc = score();
    setClef(doc, "P1", 1, 2, "C3", false);
    expect(pitches(doc, 2)).toEqual(["G#4", "G#4"]);
    expect(Array.from(doc.querySelectorAll("clef")).map((c) => c.textContent)).toEqual(["G2", "C3", "C4"]);
  });

  it("changes the key and spells notes without accidentals again", () => {
    const doc = score();
    setKey(doc, 1, 0);
    expect(pitches(doc, 1)).toEqual(["E4", "B4"]);
    expect(doc.querySelectorAll("key").length).toBe(1);
    setKey(doc, 1, 2);
    expect(pitches(doc, 3)).toEqual(["A3", "D4"]);
    expect(pitches(doc, 2)).toEqual(["G#4", "G#4"]);
  });

  it("changes the time signature from a measure on, in MusicXML's order", () => {
    const doc = score();
    setTime(doc, 2, 3, 4);
    const attrs = doc.querySelector("measure:nth-of-type(2) attributes")!;
    expect(Array.from(attrs.children).map((c) => c.localName)).toEqual(["time", "clef"]);
    expect(doc.querySelector("measure:nth-of-type(1) time")!.textContent).toBe("24");
    const out = serialize(doc);
    expect(out.startsWith("<?xml")).toBe(true);
    expect(new DOMParser().parseFromString(out, "application/xml").querySelectorAll("time").length).toBe(2);
  });
});

describe("barPage", () => {
  it("splits a long score into pages of bars", () => {
    expect(barPage(1748, 24, 0)).toEqual({ page: 0, pages: 73, first: 1, last: 24 });
    expect(barPage(1748, 24, 1)).toMatchObject({ first: 25, last: 48 });
    expect(barPage(1748, 24, 99)).toMatchObject({ page: 72, first: 1729, last: 1748 });
  });
  it("is one page for a short score", () => {
    expect(barPage(20, 24, 3)).toEqual({ page: 0, pages: 1, first: 1, last: 20 });
  });
});

describe("pageXml", () => {
  const bar = (n: number, attrs = "") => `<measure number="${n}">${attrs}${note("C", 3)}</measure>`;
  const score = (bars: string) =>
    `<score-partwise version="4.0"><work><work-title>T</work-title></work><part-list><score-part id="P1"><part-name>Cello</part-name></score-part></part-list><part id="P1">${bars}</part></score-partwise>`;
  const parse = (x: string) => new DOMParser().parseFromString(x, "application/xml");
  const start = `<attributes><divisions>2</divisions><key><fifths>-2</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>`;

  it("keeps only the page's bars, with the title and parts list", () => {
    const d = parse(pageXml(parse(score(bar(1, start) + bar(2) + bar(3) + bar(4))), 2, 3));
    expect([...d.querySelectorAll("measure")].map((m) => m.getAttribute("number"))).toEqual(["2", "3"]);
    expect(d.querySelector("work-title")?.textContent).toBe("T");
    expect(d.querySelector("score-part")?.getAttribute("id")).toBe("P1");
  });

  it("carries the key, time, clef and divisions in force onto the page's first bar", () => {
    const tenor = `<attributes><clef><sign>C</sign><line>4</line></clef></attributes>`;
    const d = parse(pageXml(parse(score(bar(1, start) + bar(2, tenor) + bar(3) + bar(4))), 3, 4));
    const a = d.querySelector("measure attributes")!;
    expect([...a.children].map((c) => c.localName)).toEqual(["divisions", "key", "time", "clef"]);
    expect(a.querySelector("divisions")?.textContent).toBe("2");
    expect(a.querySelector("fifths")?.textContent).toBe("-2");
    expect(a.querySelector("clef sign")?.textContent).toBe("C"); // the latest clef, not the first
    expect(d.querySelectorAll("measure")[1].querySelector("attributes")).toBeNull();
  });

  it("adds nothing to a page that starts at the first bar", () => {
    const d = parse(pageXml(parse(score(bar(1, start) + bar(2))), 1, 1));
    expect(d.querySelectorAll("attributes")).toHaveLength(1);
  });
});
