/** A library folder in Google Drive: reads library.json and fetches files, keeping offline copies. */
import { Drive, type FileCache } from "./drive";
import { parseIndex, requestName, type LibraryFile, type LibraryIndex, type Piece } from "./model";

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
