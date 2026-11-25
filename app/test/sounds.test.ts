import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { instrumentFor } from "../src/core/sounds";

describe("instrumentFor", () => {
  it("names the Rachmaninoff concerto's parts", () => {
    const names = ["Flauti", "Oboi", "Clarinetti in B", "Fagotti", "Corni in F I II", "Trombe in B", "Tromboni I II", "Trombono III", "Tuba",
      "Timpani in G.As.C", "Piano", "Violino I", "Viola", "Violoncello", "Violoncello II", "Basso"];
    expect(names.map((n) => instrumentFor(n))).toEqual(["flute", "oboe", "clarinet", "bassoon", "horn", "trumpet", "trombone", "trombone", "tuba",
      "timpani", "piano", "violin", "viola", "cello", "cello", "contrabass"]);
  });
  it("handles English names, abbreviations and MIDI programs", () => {
    expect(instrumentFor("Cello")).toBe("cello");
    expect(instrumentFor("Double Bass")).toBe("contrabass");
    expect(instrumentFor("Vln. 1")).toBe("violin");
    expect(instrumentFor("Vla.")).toBe("viola");
    expect(instrumentFor("Alto Saxophone")).toBe(null);
    expect(instrumentFor("Solo", 43)).toBe("cello");
    expect(instrumentFor("Part 1", 1)).toBe("piano");
    expect(instrumentFor("Theremin")).toBe(null);
  });
});

describe("sound packs", () => {
  const index = JSON.parse(readFileSync(join(__dirname, "../public/sounds/index.json"), "utf8"));
  it("has every instrument the name matcher can return, with notes in order and loops inside them", () => {
    for (const id of ["cello", "violin", "viola", "contrabass", "flute", "oboe", "clarinet", "bassoon", "horn", "trumpet", "trombone", "tuba", "piano", "harp", "timpani"]) {
      const inst = index.instruments[id];
      expect(inst, id).toBeTruthy();
      for (const layer of Object.values<{ notes: { lo: number; hi: number; key: number; start: number; end: number; loopStart?: number; loopEnd?: number }[] }>(inst.layers)) {
        let last = -1;
        for (const n of layer.notes) {
          expect(n.lo).toBeLessThanOrEqual(n.key);
          expect(n.key).toBeLessThanOrEqual(n.hi);
          expect(n.start).toBeGreaterThan(last);
          last = n.end;
          if (inst.loop) {
            expect(n.loopStart!).toBeGreaterThan(n.start);
            expect(n.loopEnd!).toBeLessThanOrEqual(n.end);
          }
        }
      }
    }
  });
});
