import { describe, expect, it } from "vitest";
import { Drive, MemoryCache } from "../src/core/library/drive";
import { DriveLibrary } from "../src/core/library/library";

/** A pretend Drive holding folders and files by parent, answering the calls saveSplit makes. */
function fakeDrive(start: { id: string; name: string; parent: string; folder?: boolean }[]) {
  const items = [...start];
  const uploads: { name: string; parent: string; size: number; how: string }[] = [];
  let next = 0;
  const sessions = new Map<string, { name: string; parent: string }>();
  const json = (v: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(v), { status: 200, headers });
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    if (method === "GET") {
      const q = url.searchParams.get("q") ?? "";
      const parent = /'([^']+)' in parents/.exec(q)?.[1];
      const name = /name = '([^']+)'/.exec(q)?.[1];
      const files = items.filter((f) => f.parent === parent && (!name || f.name === name)).map((f) => ({ id: f.id, name: f.name, mimeType: "x", webViewLink: `https://drive/${f.id}` }));
      return json({ files });
    }
    if (url.searchParams.get("uploadType") === "resumable") {
      const meta = JSON.parse(String(init!.body)) as { name: string; parents: string[] };
      const s = `https://upload.example/session/${++next}`;
      sessions.set(s, { name: meta.name, parent: meta.parents[0] });
      return json({}, { Location: s });
    }
    if (method === "PUT") {
      const s = sessions.get(String(input))!;
      const size = (init!.body as Blob).size;
      uploads.push({ ...s, size, how: "resumable" });
      items.push({ id: `f${++next}`, name: s.name, parent: s.parent });
      return json({ id: `f${next}`, name: s.name });
    }
    if (url.searchParams.get("uploadType") === "multipart") {
      const text = await (init!.body as Blob).text();
      const meta = JSON.parse(/\r\n\r\n(\{.*?\})\r\n/.exec(text)![1]) as { name: string; parents: string[] };
      uploads.push({ name: meta.name, parent: meta.parents[0], size: text.length, how: "multipart" });
      items.push({ id: `f${++next}`, name: meta.name, parent: meta.parents[0] });
      return json({ id: `f${next}`, name: meta.name });
    }
    const meta = JSON.parse(String(init!.body)) as { name: string; parents: string[] }; // a new folder
    const id = `d${++next}`;
    items.push({ id, name: meta.name, parent: meta.parents[0], folder: true });
    return json({ id, name: meta.name, webViewLink: `https://drive/${id}` });
  }) as typeof fetch;
  return { fetcher, items, uploads };
}

const pdf = (n: number) => new Uint8Array(n).fill(37);

describe("saving the pieces of a split PDF to Drive", () => {
  it("makes inbox/<PDF> (split)/ and uploads each piece there", async () => {
    const d = fakeDrive([{ id: "P", name: "pieces", parent: "ROOT", folder: true }]);
    const lib = new DriveLibrary("ROOT", new Drive(async () => "t", d.fetcher), new MemoryCache());
    const seen: number[] = [];
    const out = await lib.saveSplit("book (split)", [
      { name: "01 - A.pdf", bytes: pdf(10) },
      { name: "02 - B.pdf", bytes: pdf(20) },
    ], (n) => seen.push(n));
    const inbox = d.items.find((f) => f.name === "inbox" && f.parent === "ROOT")!;
    const dir = d.items.find((f) => f.name === "book (split)")!;
    expect(dir.parent).toBe(inbox.id);
    expect(d.uploads.map((u) => [u.name, u.parent, u.how])).toEqual([
      ["01 - A.pdf", dir.id, "multipart"],
      ["02 - B.pdf", dir.id, "multipart"],
    ]);
    expect(out).toEqual({ names: ["01 - A.pdf", "02 - B.pdf"], link: `https://drive/${dir.id}` });
    expect(seen).toEqual([1, 2]);
  });

  it("uses the inbox and folder already there, and never replaces a file in it", async () => {
    const d = fakeDrive([
      { id: "I", name: "inbox", parent: "ROOT", folder: true },
      { id: "S", name: "book (split)", parent: "I", folder: true },
      { id: "x", name: "01 - A.pdf", parent: "S" },
    ]);
    const lib = new DriveLibrary("ROOT", new Drive(async () => "t", d.fetcher), new MemoryCache());
    const out = await lib.saveSplit("book (split)", [{ name: "01 - A.pdf", bytes: pdf(5) }]);
    expect(out.names).toEqual(["01 - A (2).pdf"]);
    expect(d.items.filter((f) => f.folder).length).toBe(2); // made no new folders
  });

  it("sends a piece over 5 MB as a resumable upload", async () => {
    const d = fakeDrive([{ id: "I", name: "inbox", parent: "ROOT", folder: true }]);
    const lib = new DriveLibrary("ROOT", new Drive(async () => "t", d.fetcher), new MemoryCache());
    await lib.saveSplit("big (split)", [{ name: "01 - Big.pdf", bytes: pdf(6 * 1024 * 1024) }]);
    expect(d.uploads).toEqual([expect.objectContaining({ name: "01 - Big.pdf", how: "resumable", size: 6 * 1024 * 1024 })]);
  });
});
