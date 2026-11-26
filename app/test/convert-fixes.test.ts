import { describe, expect, it } from "vitest";
import { serialize, setClef, setInstrument, setKey, setTime, staves, warnings } from "../src/convert/fixes";

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
  it("finds the staves and warns about a cello line read as Voice in treble clef", () => {
    const doc = score();
    expect(staves(doc)).toEqual([{ part: "P1", name: "Voice", staff: 1, staves: 1, clef: "G2" }]);
    expect(warnings(doc).length).toBe(2);
  });

  it("renames the part and its sound", () => {
    const doc = score();
    setInstrument(doc, "P1", "Cello");
    expect(doc.querySelector("part-name")!.textContent).toBe("Cello");
    expect(doc.querySelector("instrument-sound")!.textContent).toBe("strings.cello");
    expect(doc.querySelector("midi-program")!.textContent).toBe("43");
    expect(warnings(doc)).toEqual(["Cello starts in treble clef. If the PDF shows bass or tenor clef, change the clef below (the notes move with it)."]);
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
