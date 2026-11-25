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
