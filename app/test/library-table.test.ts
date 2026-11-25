import { describe, expect, it } from "vitest";
import type { Piece } from "../src/core/library/model";
import { cell, choices, rows, xmlState, type Filters } from "../src/library/table";

const pdf = (name: string, extra = {}) => ({ name, kind: "pdf" as const, variant: "x", ...extra });
const P: Piece[] = [
  { id: "a", title: "Elegie", composer: "Fauré, Gabriel", genre: "Romantic", year: "1880", instrumentation: "Duet (Cello & Piano)", files: [pdf("a.pdf", { musicxml: "a.musicxml" })] },
  { id: "b", title: "Suite 1", composer: "Bach, Johann Sebastian", genre: "Baroque", year: "c. 1720", instrumentation: "Solo Cello", tags: ["bariolage"], files: [pdf("b.pdf"), pdf("b2.pdf")] },
  { id: "c", title: "The Swan", composer: "Saint-Saëns, Camille", genre: "Romantic", files: [pdf("c.pdf", { musicxml: "c.musicxml", quality: "REVIEW" })] },
  { id: "d", title: "Concerto", composer: "Élgar, Edward", year: "1919", files: [pdf("d.pdf")] },
];
const none: Filters = { query: "", genre: "", instrumentation: "", level: "", tag: "", musicxml: "" };

describe("library table", () => {
  it("sorts by composer by default order, ignoring accents, and by year as numbers with blanks last", () => {
    expect(rows(P, none, { by: "composer", desc: false }).map((p) => p.id)).toEqual(["b", "d", "a", "c"]);
    expect(rows(P, none, { by: "year", desc: false }).map((p) => p.id)).toEqual(["b", "a", "d", "c"]);
    expect(rows(P, none, { by: "year", desc: true }).map((p) => p.id)).toEqual(["d", "a", "b", "c"]); // blanks stay last
  });

  it("filters by genre, instrumentation, technique, MusicXML and search words together", () => {
    expect(rows(P, { ...none, genre: "Romantic" }, { by: "title", desc: false }).map((p) => p.id)).toEqual(["a", "c"]);
    expect(rows(P, { ...none, musicxml: "no" }, { by: "title", desc: false }).map((p) => p.id)).toEqual(["d", "b"]);
    expect(rows(P, { ...none, tag: "bariolage" }, { by: "title", desc: false }).map((p) => p.id)).toEqual(["b"]);
    expect(rows(P, { ...none, query: "romantic swan" }, { by: "title", desc: false }).map((p) => p.id)).toEqual(["c"]);
    expect(rows(P, { ...none, query: "solo" }, { by: "title", desc: false }).map((p) => p.id)).toEqual(["b"]);
  });

  it("shows cells and filter choices", () => {
    expect(cell(P[1], "editions")).toBe("2");
    expect(cell(P[1], "tags")).toBe("bariolage");
    expect(xmlState(P[0])).toBe("Yes");
    expect(xmlState(P[2])).toBe("check");
    expect(xmlState(P[1])).toBe("");
    expect(choices(P, "genre")).toEqual(["Romantic", "Baroque"]); // most common first
    expect(choices(P, "level")).toEqual([]);
  });
});
