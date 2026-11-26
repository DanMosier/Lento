/** A library folder in Google Drive: reads library.json and fetches files, keeping offline copies. */
import { Drive, type FileCache } from "./drive";
import { parseIndex, requestName, requestNameOf, type LibraryFile, type LibraryIndex, type PcStatus, type Piece } from "./model";

export const INDEX_KEY = "library.json";

export function fileKey(piece: Piece, file: LibraryFile): string {
  return `pieces/${piece.id}/${file.name}`;
}

export class DriveLibrary {
  private ids = new Map<string, string>(); // path -> Drive folder id, for this session

  constructor(
    readonly rootId: string,
    private readonly drive: Drive,
    private readonly cache: FileCache,
  ) {}

  /** The saved index, if this device has loaded the library before. Works offline. */
  async cachedIndex(): Promise<LibraryIndex | null> {
    const saved = await this.cache.get(INDEX_KEY);
    return saved ? parseIndex(new TextDecoder().decode(saved.data)) : null;
  }

  /**
   * The index from Drive only if it is newer than this device's copy (one small metadata call when it isn't), else
   * null. For checking quietly in the background.
   */
  async newerIndex(): Promise<LibraryIndex | null> {
    const f = await this.drive.child(this.rootId, INDEX_KEY);
    if (!f) return null;
    const saved = await this.cache.get(INDEX_KEY);
    if (saved && saved.modifiedTime && saved.modifiedTime === f.modifiedTime) return null;
    return this.loadIndex();
  }

  /** Fetches library.json from Drive and saves it for offline use. */
  async loadIndex(): Promise<LibraryIndex> {
    const f = await this.drive.child(this.rootId, INDEX_KEY);
    if (!f) throw new Error("There is no library.json in that folder yet. Run lento-library build on your PC first.");
    const saved = await this.cache.get(INDEX_KEY);
    if (saved && saved.modifiedTime && saved.modifiedTime === f.modifiedTime) return parseIndex(new TextDecoder().decode(saved.data));
    const data = await this.drive.download(f.id);
    const index = parseIndex(new TextDecoder().decode(data)); // check before saving over a good copy
    await this.cache.put(INDEX_KEY, { data, modifiedTime: f.modifiedTime });
    return index;
  }

  /**
   * Asks the PC to make MusicXML for these PDFs: one small file each in requests/, which
   * `lento-library convert` picks up. Returns how many were newly requested.
   */
  async requestConversion(items: { piece: Piece; file: LibraryFile }[], when = new Date()): Promise<number> {
    let requests = this.ids.get("requests") ?? (await this.drive.child(this.rootId, "requests"))?.id;
    if (!requests) requests = (await this.drive.create(this.rootId, "requests")).id;
    this.ids.set("requests", requests);
    let made = 0;
    for (const { piece, file } of items) {
      const name = requestName(file);
      if (await this.drive.child(requests, name)) continue;
      await this.drive.create(requests, name, { piece_id: piece.id, pdf: file.name, requested: when.toISOString() });
      made++;
    }
    return made;
  }

  /**
   * Takes PDFs off the PC's queue by binning their request files. The PC skips a PDF whose request is gone, unless
   * it is already converting it. Returns the PDF names removed, and those whose request this app can't remove
   * (made by hand on the PC: Drive lets the app change only files it created).
   */
  async cancelConversion(pdfNames: string[]): Promise<{ removed: string[]; failed: string[] }> {
    const removed: string[] = [];
    const failed: string[] = [];
    const requests = this.ids.get("requests") ?? (await this.drive.child(this.rootId, "requests"))?.id;
    if (!requests) return { removed: pdfNames, failed };
    this.ids.set("requests", requests);
    for (const name of pdfNames) {
      const f = await this.drive.child(requests, requestNameOf(name));
      if (!f) {
        removed.push(name); // already gone (converted, or removed on another device)
        continue;
      }
      try {
        await this.drive.trash(f.id);
        removed.push(name);
      } catch {
        failed.push(name);
      }
    }
    return { removed, failed };
  }

  /** What the PC's watcher last reported, or null if it has never run. Always fetched fresh. */
  async pcStatus(): Promise<PcStatus | null> {
    const requests = this.ids.get("requests") ?? (await this.drive.child(this.rootId, "requests"))?.id;
    if (!requests) return null;
    this.ids.set("requests", requests);
    const f = await this.drive.child(requests, "_status.json");
    if (!f) return null;
    return JSON.parse(new TextDecoder().decode(await this.drive.download(f.id))) as PcStatus;
  }

  /**
   * A small JSON file kept beside a piece's scores (for example score marks: `<score>.marks.json`). Returns null
   * if there isn't one yet. Uses the offline copy when Drive can't be reached.
   */
  async readSidecar(pieceId: string, name: string): Promise<unknown | null> {
    const key = `pieces/${pieceId}/${name}`;
    const saved = await this.cache.get(key);
    const parse = (d: ArrayBuffer) => JSON.parse(new TextDecoder().decode(d)) as unknown;
    try {
      const f = await this.drive.child(await this.folder(["pieces", pieceId]), name);
      if (!f) return null;
      if (saved && saved.modifiedTime === f.modifiedTime) return parse(saved.data);
      const data = await this.drive.download(f.id);
      await this.cache.put(key, { data, modifiedTime: f.modifiedTime });
      return parse(data);
    } catch (e) {
      if (saved) return parse(saved.data);
      throw e;
    }
  }

  /** Writes that file to Drive (creating it the first time) and keeps a copy for offline use. */
  async writeSidecar(pieceId: string, name: string, content: object): Promise<void> {
    const folderId = await this.folder(["pieces", pieceId]);
    const f = await this.drive.child(folderId, name);
    const saved = f ? await this.drive.update(f.id, content) : await this.drive.create(folderId, name, content);
    await this.cache.put(`pieces/${pieceId}/${name}`, { data: new TextEncoder().encode(JSON.stringify(content)).buffer as ArrayBuffer, modifiedTime: saved.modifiedTime });
  }

  /**
   * A small JSON file this app keeps in the library folder itself, beside library.json (for example favorites and
   * setlists). Null if there isn't one yet. Always fetched fresh: it is how other devices' changes arrive.
   */
  async readRootJson(name: string): Promise<unknown | null> {
    const f = await this.drive.child(this.rootId, name);
    if (!f) return null;
    this.ids.set(`root:${name}`, f.id);
    return JSON.parse(new TextDecoder().decode(await this.drive.download(f.id))) as unknown;
  }

  /** Writes that file (creating it the first time). The PC's watcher ignores it: it isn't a score. */
  async writeRootJson(name: string, content: object): Promise<void> {
    const id = this.ids.get(`root:${name}`) ?? (await this.drive.child(this.rootId, name))?.id;
    const saved = id ? await this.drive.update(id, content) : await this.drive.create(this.rootId, name, content);
    this.ids.set(`root:${name}`, saved.id ?? id);
  }

  /**
   * Saves a corrected score as `<score>.fixed` beside it. The app can't change the PC's files, so the PC's watcher
   * puts it in place of the score (keeping the converter's version as `<score>.orig`).
   */
  async writeFixedScore(pieceId: string, scoreName: string, xml: string): Promise<void> {
    const folderId = await this.folder(["pieces", pieceId]);
    const name = `${scoreName}.fixed`;
    const f = await this.drive.child(folderId, name);
    await this.drive.putText(folderId, name, xml, "application/vnd.recordare.musicxml+xml", f?.id);
  }

  /** A PDF's bytes, fetched fresh and not kept for offline use (for splitting, which needs Drive anyway). */
  async downloadPdf(piece: Piece, file: LibraryFile): Promise<ArrayBuffer> {
    const f = await this.drive.child(await this.folder(["pieces", piece.id]), file.name);
    if (!f) throw new Error(`${file.name} is missing from Drive. Run lento-library build again.`);
    return this.drive.download(f.id);
  }

  /**
   * Saves the pieces of a split PDF in inbox/<folder>/ (made if needed), where the PC's splitter puts them too, to
   * be filed into pieces/ like any new download. Never replaces a file already there: a clash gets " (2)" added.
   * Returns the names used and the folder's Drive link.
   */
  async saveSplit(folder: string, files: { name: string; bytes: Uint8Array }[], progress: (done: number) => void = () => {}): Promise<{ names: string[]; link?: string }> {
    const inbox = this.ids.get("inbox") ?? (await this.drive.child(this.rootId, "inbox"))?.id ?? (await this.drive.create(this.rootId, "inbox")).id;
    this.ids.set("inbox", inbox);
    const dir = (await this.drive.child(inbox, folder)) ?? (await this.drive.create(inbox, folder));
    const taken = new Set((await this.drive.names(dir.id)).map((n) => n.toLowerCase()));
    const names: string[] = [];
    for (const f of files) {
      let name = f.name;
      for (let k = 2; taken.has(name.toLowerCase()); k++) name = f.name.replace(/(\.pdf)?$/i, ` (${k})$1`);
      await this.drive.putBytes(dir.id, name, f.bytes, "application/pdf");
      taken.add(name.toLowerCase());
      names.push(name);
      progress(names.length);
    }
    return { names, link: dir.webViewLink };
  }

  private async folder(path: string[]): Promise<string> {
    let id = this.rootId;
    for (let i = 0; i < path.length; i++) {
      const key = path.slice(0, i + 1).join("/");
      const known = this.ids.get(key);
      if (known) {
        id = known;
        continue;
      }
      const f = await this.drive.child(id, path[i]);
      if (!f) throw new Error(`The folder ${key} is missing from Drive. Run lento-library build again.`);
      this.ids.set(key, (id = f.id));
    }
    return id;
  }

  /**
   * The file's bytes (and its Drive link). Uses the offline copy when it is current, or when Drive can't be reached.
   * PDFs are only looked up, not downloaded, unless `download` is set.
   */
  async open(piece: Piece, file: LibraryFile, download = file.kind === "musicxml"): Promise<{ data?: ArrayBuffer; link?: string; offline: boolean }> {
    const key = fileKey(piece, file);
    const saved = await this.cache.get(key);
    try {
      const folderId = await this.folder(["pieces", piece.id]);
      const f = await this.drive.child(folderId, file.name);
      if (!f) throw new Error(`${file.name} is missing from Drive. Run lento-library build again.`);
      if (!download) return { link: f.webViewLink, offline: false };
      if (saved && saved.modifiedTime === f.modifiedTime) return { data: saved.data, link: f.webViewLink, offline: false };
      const data = await this.drive.download(f.id);
      await this.cache.put(key, { data, modifiedTime: f.modifiedTime, webViewLink: f.webViewLink });
      return { data, link: f.webViewLink, offline: false };
    } catch (e) {
      if (saved) return { data: saved.data, link: saved.webViewLink, offline: true };
      throw e;
    }
  }
}
