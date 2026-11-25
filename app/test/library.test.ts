import { describe, expect, it } from "vitest";
import { Drive, MemoryCache, type DriveFile } from "../src/library/drive";
import { DriveLibrary } from "../src/library/library";
import { folderIdFromLink, parseIndex, search, type Piece } from "../src/library/model";

const INDEX = {
  format: "lento-library",
  version: 1,
  generated: "2026-11-25T00:00:00+00:00",
  pieces: [
    {
      id: "saint-saens_the-swan",
      title: "The Swan",
      composer: "Saint-Saëns",
      tags: ["legato", "vibrato"],
      files: [
        { name: "saint-saens_the-swan.musicxml", kind: "musicxml", variant: "" },
        { name: "saint-saens_the-swan__imslp.pdf", kind: "pdf", variant: "imslp" },
      ],
    },
    {
      id: "bach_cello-suite-1-prelude_bwv1007",
      title: "Cello Suite No. 1: Prelude",
      composer: "J. S. Bach",
      catalog_no: "BWV 1007",
      tags: ["string-crossings"],
      files: [{ name: "bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf", kind: "pdf", variant: "barenreiter" }],
    },
  ],
};

describe("library index", () => {
  it("parses and searches with accents, ids and tags", () => {
    const idx = parseIndex(JSON.stringify(INDEX));
    const ids = (q: string, tag = "") => search(idx.pieces, q, tag).map((p: Piece) => p.id);
    expect(ids("")).toEqual(["bach_cello-suite-1-prelude_bwv1007", "saint-saens_the-swan"]);
    expect(ids("saint saens")).toEqual(["saint-saens_the-swan"]);
    expect(ids("bwv 1007")).toEqual(["bach_cello-suite-1-prelude_bwv1007"]);
    expect(ids("", "vibrato")).toEqual(["saint-saens_the-swan"]);
    expect(ids("swan", "string-crossings")).toEqual([]);
    expect(() => parseIndex('{"pieces": []}')).toThrow(/lento-library/);
  });

  it("reads Drive folder links", () => {
    expect(folderIdFromLink("https://drive.google.com/drive/folders/115MmUhbWr_w2TI0TBJ1fr7ZOYV5V8OTx?usp=sharing")).toBe("115MmUhbWr_w2TI0TBJ1fr7ZOYV5V8OTx");
    expect(folderIdFromLink("https://drive.google.com/open?id=115MmUhbWr_w2TI0TBJ1fr7ZOYV5V8OTx")).toBe("115MmUhbWr_w2TI0TBJ1fr7ZOYV5V8OTx");
    expect(folderIdFromLink("not a link")).toBeNull();
  });
});

/** A pretend Drive: path -> file, answering the two calls the library makes. */
function fakeDrive(files: Record<string, { id: string; body?: string; modifiedTime?: string }>) {
  const byId = new Map(Object.entries(files).map(([path, f]) => [f.id, { ...f, path }]));
  const calls: string[] = [];
  let online = true;
  const fetcher = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    calls.push(url.pathname + url.search);
    if (!online) throw new TypeError("Failed to fetch");
    if (url.searchParams.get("alt") === "media") {
      const f = byId.get(decodeURIComponent(url.pathname.split("/").pop()!));
      return new Response(f?.body ?? "", { status: f ? 200 : 404 });
    }
    const m = url.searchParams.get("q")!.match(/^'(.+)' in parents and name = '(.+)' and trashed = false$/)!;
    const parent = m[1] === "ROOT" ? "" : byId.get(m[1])!.path + "/";
    const f = files[parent + m[2].replace(/\\'/g, "'")];
    const out: DriveFile[] = f ? [{ id: f.id, name: m[2], mimeType: "x", modifiedTime: f.modifiedTime, webViewLink: `https://drive/${f.id}` }] : [];
    return new Response(JSON.stringify({ files: out }), { status: 200 });
  }) as typeof fetch;
  return { fetcher, calls, setOnline: (v: boolean) => (online = v) };
}

describe("Drive library", () => {
  it("loads the index, opens scores, and falls back to the saved copy offline", async () => {
    const d = fakeDrive({
      "library.json": { id: "IDX", body: JSON.stringify(INDEX), modifiedTime: "t1" },
      pieces: { id: "P" },
      "pieces/saint-saens_the-swan": { id: "S" },
      "pieces/saint-saens_the-swan/saint-saens_the-swan.musicxml": { id: "X", body: "<score-partwise/>", modifiedTime: "t1" },
      "pieces/saint-saens_the-swan/saint-saens_the-swan__imslp.pdf": { id: "PDF" },
    });
    const cache = new MemoryCache();
    const lib = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), cache);
    const idx = await lib.loadIndex();
    expect(idx.pieces).toHaveLength(2);
    const swan = idx.pieces.find((p) => p.id === "saint-saens_the-swan")!;

    const xml = await lib.open(swan, swan.files[0]);
    expect(new TextDecoder().decode(xml.data)).toBe("<score-partwise/>");
    const pdf = await lib.open(swan, swan.files[1]);
    expect(pdf.data).toBeUndefined();
    expect(pdf.link).toBe("https://drive/PDF");
    // folders are looked up once per session, and an unchanged file is not downloaded again
    const before = d.calls.length;
    await lib.open(swan, swan.files[0]);
    expect(d.calls.slice(before).filter((c) => c.includes("alt=media"))).toHaveLength(0);
    expect(d.calls.filter((c) => c.includes("name+%3D+%27pieces%27"))).toHaveLength(1);

    d.setOnline(false);
    const offline = await lib.open(swan, swan.files[0]);
    expect(offline.offline).toBe(true);
    expect(new TextDecoder().decode(offline.data)).toBe("<score-partwise/>");
    expect((await lib.cachedIndex())!.pieces).toHaveLength(2);
    await expect(lib.open(swan, swan.files[1], true)).rejects.toThrow();
  });
});
