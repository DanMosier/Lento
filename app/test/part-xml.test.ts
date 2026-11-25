import { describe, expect, it } from "vitest";
import { parseScore, partXml } from "../src/core/score";

const two = `<?xml version="1.0"?><score-partwise version="3.1"><work><work-title>Duo</work-title></work>
<part-list><score-part id="P1"><part-name>Violin</part-name></score-part><score-part id="P2"><part-name>Cello</part-name></score-part></part-list>
${["P1", "P2"].map((id, k) => `<part id="${id}"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>${k ? "F" : "G"}</sign><line>${k ? 4 : 2}</line></clef></attributes><note><pitch><step>${k ? "C" : "A"}</step><octave>${k ? 3 : 4}</octave></pitch><duration>4</duration><type>whole</type></note></measure></part>`).join("")}
</score-partwise>`;

describe("partXml", () => {
  it("keeps only the chosen part and the header", () => {
    const s = parseScore(two, "P2");
    const out = partXml(s.doc, "P2");
    expect(out).toContain("<work-title>Duo</work-title>");
    expect(out).toContain('id="P2"');
    expect(out).not.toContain('id="P1"');
    const again = parseScore(out);
    expect(again.parts.map((p) => p.name)).toEqual(["Cello"]);
    expect(again.notes.map((n) => n.midi)).toEqual(s.notes.map((n) => n.midi));
  });
});

import { quickPartList } from "../src/core/score";
import { choiceLabel, cleanChoice } from "../src/practice/parts";

describe("part choice", () => {
  const parts = [
    { id: "P1", name: "Violin" },
    { id: "P2", name: "Cello" },
    { id: "P3", name: "Piano" },
  ];
  it("reads the part list without parsing the parts", () => {
    expect(quickPartList(two)).toEqual([
      { id: "P1", name: "Violin" },
      { id: "P2", name: "Cello" },
    ]);
  });
  it("keeps several parts in score order", () => {
    const s = parseScore(two, "P2");
    const out = partXml(s.doc, ["P2", "P1"]);
    expect(parseScore(out).parts.map((p) => p.name)).toEqual(["Violin", "Cello"]);
  });
  it("cleans a saved choice against the score", () => {
    expect(cleanChoice(parts, { practise: "P2", shown: ["P3", "P9"] })).toEqual({ practise: "P2", shown: ["P2", "P3"] });
    expect(cleanChoice(parts, { practise: "P9", shown: [] })).toBeNull();
    expect(choiceLabel(parts, { practise: "P2", shown: ["P2", "P3"] })).toBe("Cello + 1");
  });
});
