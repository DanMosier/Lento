// @vitest-environment node
import { describe, expect, it } from "vitest";
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";
import { sheetPdf } from "../perf/fixtures.mjs";
import { bookmarks, extract, type PdfDoc } from "../src/split/pdf";
import { fileName, fileNames, fromBookmarks, normalizeStarts, pageRange, partsFor, sanitize, splitFolder, toggleStart } from "../src/split/plan";

const title = (n: number) => `Book - Piece ${n}`;

describe("choosing where pieces start", () => {
  it("always starts a piece on page 1, and keeps starts in order and on real pages", () => {
    expect(normalizeStarts([9, 3, 3, 0, 40, 2.5], 12)).toEqual([1, 3, 9]);
  });

  it("toggles a start on and off, but never page 1's", () => {
    let s = toggleStart([1], 5, 10);
    expect(s).toEqual([1, 5]);
    s = toggleStart(s, 3, 10);
    expect(s).toEqual([1, 3, 5]);
    expect(toggleStart(s, 5, 10)).toEqual([1, 3]);
    expect(toggleStart(s, 1, 10)).toEqual([1, 3, 5]);
  });

  it("makes parts that cover every page once", () => {
    const parts = partsFor([1, 4, 9], 12, [], title);
    expect(parts.map((p) => [p.start, p.end])).toEqual([
      [1, 3],
      [4, 8],
      [9, 12],
    ]);
    expect(parts.map(pageRange)).toEqual(["p. 1–3", "p. 4–8", "p. 9–12"]);
    expect(pageRange(partsFor([1, 12], 12, [], title)[1])).toBe("p. 12");
  });

  it("keeps a typed title and a left-out piece when another start is added", () => {
    let parts = partsFor([1, 6], 10, [], title);
    parts[1] = { ...parts[1], title: "Sonata in G", keep: false, named: true };
    parts = partsFor([1, 3, 6, 8], 10, parts, title);
    expect(parts.map((p) => [p.start, p.end, p.title, p.keep])).toEqual([
      [1, 2, "Book - Piece 1", true],
      [3, 5, "Book - Piece 2", true],
      [6, 7, "Sonata in G", false],
      [8, 10, "Book - Piece 4", true], // suggested names follow the numbering
    ]);
  });

  it("suggests starts from the PDF's bookmarks, only when there are at least two pieces", () => {
    const got = fromBookmarks(
      [
        { title: " Allemande ", page: 3 },
        { title: "Courante", page: 7 },
        { title: "Also page 7", page: 7 },
        { title: "Past the end", page: 99 },
      ],
      10,
    );
    expect(got?.starts).toEqual([1, 3, 7]);
    expect(got?.titles.get(3)).toBe("Allemande");
    expect(got?.titles.get(7)).toBe("Courante");
    expect(fromBookmarks([{ title: "Only one", page: 1 }], 10)).toBeNull();
  });
});

describe("naming the new PDFs like the PC's splitter", () => {
  it("cleans titles the same way", () => {
    expect(sanitize('  Suite No. 1: "Prelude" / Allemande?  ')).toBe("Suite No. 1 Prelude Allemande");
    expect(sanitize(" -- ")).toBe("Untitled Piece");
    expect(sanitize("x".repeat(200))).toHaveLength(110);
  });

  it("numbers them, with the composer in front", () => {
    expect(fileName(1, "Hungarian Dance No. 1", "Brahms, Johannes")).toBe("01 - Brahms, Johannes - Hungarian Dance No. 1.pdf");
    expect(fileName(12, "Gavotte")).toBe("12 - Gavotte.pdf");
    expect(fileName(2, "03 - Already numbered")).toBe("03 - Already numbered.pdf");
    expect(fileName(1, "Bach - Suite", "Bach")).toBe("01 - Bach - Suite.pdf"); // composer not added twice
    expect(fileName(3, "")).toBe("03 - Piece 3.pdf");
  });

  it("numbers by place in the PDF, skips left-out parts, and never repeats a name", () => {
    const parts = partsFor([1, 3, 5, 7], 8, [], () => "Dance");
    parts[1].keep = false;
    expect(fileNames(parts)).toEqual(["01 - Dance.pdf", "03 - Dance.pdf", "04 - Dance.pdf"]);
    parts[1].keep = true;
    for (const p of parts) p.title = "01 - Same";
    expect(fileNames(parts)).toEqual(["01 - Same.pdf", "01 - Same (2).pdf", "01 - Same (3).pdf", "01 - Same (4).pdf"]);
  });

  it("puts them in a folder named after the PDF", () => {
    expect(splitFolder("brahms_hungarian-dances__score.pdf")).toBe("brahms_hungarian-dances__score (split)");
    expect(splitFolder("Etudes.PDF")).toBe("Etudes (split)");
  });
});

describe("splitting a real PDF file", () => {
  const open = (bytes: Uint8Array) => pdfjs.getDocument({ data: bytes, isEvalSupported: false }).promise as unknown as Promise<PdfDoc>;
  const text = async (doc: PdfDoc, n: number) =>
    ((await (await doc.getPage(n)).getTextContent()).items as { str: string }[]).map((i) => i.str).join(" ");

  it("reads the bookmarks and copies each piece's pages into a PDF of its own", async () => {
    const doc = await open(new Uint8Array(sheetPdf(12, [1, 5, 9])));
    expect(doc.numPages).toBe(12);
    const marks = fromBookmarks(await bookmarks(doc), doc.numPages);
    expect(marks?.starts).toEqual([1, 5, 9]);
    const parts = partsFor(marks!.starts, doc.numPages, [], (n, s) => marks!.titles.get(s) || title(n));
    expect(fileNames(parts)).toEqual(["01 - Piece 1.pdf", "02 - Piece 2.pdf", "03 - Piece 3.pdf"]);

    const second = await open(await extract(doc, parts[1].start, parts[1].end));
    expect(second.numPages).toBe(4);
    expect(await text(second, 1)).toContain("Piece 2");
    expect(await text(second, 4)).toContain("8"); // its last page is page 8 of the book
    const one = await open(await extract(doc, 12, 12));
    expect(one.numPages).toBe(1);
  });

  it("has no bookmarks to suggest for a PDF without them", async () => {
    const doc = await open(new Uint8Array(sheetPdf(3)));
    expect(await bookmarks(doc)).toEqual([]);
  });
});
