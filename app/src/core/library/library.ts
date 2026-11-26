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
   * Saves a corrected score as `<score>.fixed` beside it. The app can't change the PC's files, so the PC's watcher
   * puts it in place of the score (keeping the converter's version as `<score>.orig`).
   */
  async writeFixedScore(pieceId: string, scoreName: string, xml: string): Promise<void> {
    const folderId = await this.folder(["pieces", pieceId]);
    const name = `${scoreName}.fixed`;
    const f = await this.drive.child(folderId, name);
    await this.drive.putText(folderId, name, xml, "application/vnd.recordare.musicxml+xml", f?.id);
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
