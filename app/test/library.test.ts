import { describe, expect, it } from "vitest";
import { Drive, MemoryCache, type DriveFile } from "../src/core/library/drive";
import { DriveLibrary } from "../src/core/library/library";
import { folderIdFromLink, musicxmlOf, parseIndex, requestName, search, type Piece } from "../src/core/library/model";

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
  let next = 0;
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    calls.push((init?.method ?? "GET") + " " + url.pathname + url.search);
    if (!online) throw new TypeError("Failed to fetch");
    if (init?.method === "POST") {
      const text = String(init.body);
      const meta = JSON.parse(text.includes("--lento") ? text.split("\r\n\r\n")[1].split("\r\n")[0] : text) as { name: string; parents: string[] };
      const parent = meta.parents[0] === "ROOT" ? "" : byId.get(meta.parents[0])!.path + "/";
      const content = text.includes("--lento") ? text.split("\r\n\r\n")[2]?.split("\r\n--")[0] : undefined;
      const f = { id: `NEW${next++}`, body: content ?? text, modifiedTime: `m${next}` };
      files[parent + meta.name] = f;
      byId.set(f.id, { ...f, path: parent + meta.name });
      return new Response(JSON.stringify({ id: f.id, name: meta.name, mimeType: "x" }), { status: 200 });
    }
    if (init?.method === "PATCH") {
      const f = byId.get(decodeURIComponent(url.pathname.split("/").pop()!))!;
      if (String(init.body) === JSON.stringify({ trashed: true })) {
        if (f.id.startsWith("HAND")) return new Response(JSON.stringify({ error: { message: "insufficient permissions" } }), { status: 403 });
        delete files[f.path];
        byId.delete(f.id);
        return new Response("{}", { status: 200 });
      }
      f.body = files[f.path].body = String(init.body);
      f.modifiedTime = files[f.path].modifiedTime = `m${next++}`;
      return new Response(JSON.stringify({ id: f.id, name: f.path, mimeType: "x", modifiedTime: f.modifiedTime }), { status: 200 });
    }
    if (url.searchParams.get("alt") === "media") {
      const f = byId.get(decodeURIComponent(url.pathname.split("/").pop()!));
      return new Response((f && files[f.path]?.body) ?? f?.body ?? "", { status: f ? 200 : 404 }); // files may be changed by a test
    }
    const m = url.searchParams.get("q")!.match(/^'(.+)' in parents and name = '(.+)' and trashed = false$/)!;
    const parent = m[1] === "ROOT" ? "" : byId.get(m[1])!.path + "/";
    const f = files[parent + m[2].replace(/\\'/g, "'")];
    const out: DriveFile[] = f ? [{ id: f.id, name: m[2], mimeType: "x", modifiedTime: f.modifiedTime, webViewLink: `https://drive/${f.id}` }] : [];
    return new Response(JSON.stringify({ files: out }), { status: 200 });
  }) as typeof fetch;
  return { fetcher, calls, files, setOnline: (v: boolean) => (online = v) };
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

describe("MusicXML beside the PDF, and conversion requests", () => {
  it("practises from the MusicXML of the same name, and queues PDFs without one", async () => {
    const pdfWithXml = { name: "a_b__ed.pdf", kind: "pdf" as const, variant: "ed", musicxml: "a_b__ed.musicxml", quality: "REVIEW" };
    expect(musicxmlOf(pdfWithXml)).toEqual({ name: "a_b__ed.musicxml", kind: "musicxml", variant: "ed", quality: "REVIEW" });
    expect(musicxmlOf({ name: "a_b__x.pdf", kind: "pdf", variant: "x" })).toBeNull();
    expect(requestName({ name: "faure_elegie_op24__imslp.pdf", kind: "pdf", variant: "imslp" })).toBe("convert__faure_elegie_op24__imslp.json");

    const d = fakeDrive({ "library.json": { id: "IDX", body: JSON.stringify(INDEX) } });
    const lib = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    const idx = await lib.loadIndex();
    const bach = idx.pieces.find((p) => p.id.startsWith("bach"))!;
    expect(await lib.requestConversion([{ piece: bach, file: bach.files[0] }], new Date("2026-11-25T00:00:00Z"))).toBe(1);
    expect(d.files["requests"]).toBeDefined(); // the folder was made
    const req = d.files["requests/convert__bach_cello-suite-1-prelude_bwv1007__barenreiter.json"];
    expect(req.body).toContain('"pdf":"bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf"');
    // asking again does not make a second file
    expect(await lib.requestConversion([{ piece: bach, file: bach.files[0] }])).toBe(0);
  });
});

describe("files kept beside a score (score marks)", () => {
  it("creates, updates, reads back, and works offline from the saved copy", async () => {
    const d = fakeDrive({ pieces: { id: "P" }, "pieces/swan": { id: "S" } });
    const lib = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    expect(await lib.readSidecar("swan", "swan.marks.json")).toBeNull();
    await lib.writeSidecar("swan", "swan.marks.json", { marks: [1] });
    expect(JSON.parse(d.files["pieces/swan/swan.marks.json"].body!)).toEqual({ marks: [1] });
    await lib.writeSidecar("swan", "swan.marks.json", { marks: [1, 2] });
    expect(d.calls.filter((c) => c.startsWith("PATCH"))).toHaveLength(1); // the second save updates the same file
    expect(await lib.readSidecar("swan", "swan.marks.json")).toEqual({ marks: [1, 2] });
    d.setOnline(false);
    expect(await lib.readSidecar("swan", "swan.marks.json")).toEqual({ marks: [1, 2] });
  });
});

describe("checking for a newer index", () => {
  it("downloads library.json again only when Drive's copy changed", async () => {
    const d = fakeDrive({ "library.json": { id: "IDX", body: JSON.stringify(INDEX), modifiedTime: "t1" } });
    const lib = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    await lib.loadIndex();
    const downloads = () => d.calls.filter((c) => c.includes("alt=media")).length;
    expect(await lib.newerIndex()).toBeNull();
    expect(downloads()).toBe(1);
    d.files["library.json"].modifiedTime = "t2";
    d.files["library.json"].body = JSON.stringify({ ...INDEX, pieces: INDEX.pieces.slice(0, 1) });
    expect((await lib.newerIndex())?.pieces).toHaveLength(1);
    expect(downloads()).toBe(2);
  });
});

describe("favorites and setlists file", () => {
  it("lives beside library.json, created once and then updated, and merges two devices' changes", async () => {
    const { mergeLists, parseLists, setFavorite, emptyLists, favoriteIds } = await import("../src/library/lists");
    const d = fakeDrive({});
    const phone = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    const pc = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    expect(await phone.readRootJson("lento-lists.json")).toBeNull();
    await phone.writeRootJson("lento-lists.json", setFavorite(emptyLists(), "swan", true, 10));
    expect(d.files["lento-lists.json"]).toBeTruthy();
    // the PC starred something else meanwhile: it reads, merges, writes back the same file
    const remote = parseLists(await pc.readRootJson("lento-lists.json"));
    await pc.writeRootJson("lento-lists.json", mergeLists(setFavorite(emptyLists(), "bach", true, 20), remote));
    expect(d.calls.filter((c) => c.startsWith("PATCH"))).toHaveLength(1);
    expect(favoriteIds(parseLists(await phone.readRootJson("lento-lists.json")))).toEqual(new Set(["swan", "bach"]));
  });
});

describe("removing PDFs from the queue", () => {
  it("bins the app's own request files and reports ones made on the PC", async () => {
    const d = fakeDrive({
      requests: { id: "R" },
      "requests/convert__a_b__x.json": { id: "NEWa", body: "{}" },
      "requests/convert__c_d__x.json": { id: "HAND1", body: "{}" },
    });
    const lib = new DriveLibrary("ROOT", new Drive(async () => "token", d.fetcher), new MemoryCache());
    const r = await lib.cancelConversion(["a_b__x.pdf", "c_d__x.pdf", "gone__x.pdf"]);
    expect(r).toEqual({ removed: ["a_b__x.pdf", "gone__x.pdf"], failed: ["c_d__x.pdf"] });
    expect(d.files["requests/convert__a_b__x.json"]).toBeUndefined();
    expect(d.files["requests/convert__c_d__x.json"]).toBeDefined();
  });
});

describe("finding the library by itself", () => {
  it("picks the folder whose library.json sits beside pieces/, and saves it on this device", async () => {
    const { findLibrary, libraryFolder } = await import("../src/core/library/connection");
    const found = [
      { id: "J1", name: "library.json", mimeType: "application/json", parents: ["OLDCOPY"] }, // newest, but no pieces/
      { id: "J2", name: "library.json", mimeType: "application/json", parents: ["LIB"] },
    ];
    const fetcher = (async (input: RequestInfo | URL) => {
      const q = new URL(String(input)).searchParams.get("q")!;
      if (q.startsWith("name = 'library.json'")) return new Response(JSON.stringify({ files: found }), { status: 200 });
      const has = q.startsWith("'LIB' in parents and name = 'pieces'");
      return new Response(JSON.stringify({ files: has ? [{ id: "P", name: "pieces", mimeType: "folder" }] : [] }), { status: 200 });
    }) as typeof fetch;
    expect(await findLibrary(new Drive(async () => "token", fetcher))).toBe("LIB");
    expect(libraryFolder()).toBe("https://drive.google.com/drive/folders/LIB");
    const none = (async () => new Response(JSON.stringify({ files: [] }), { status: 200 })) as typeof fetch;
    expect(await findLibrary(new Drive(async () => "token", none))).toBeNull();
  });
});
