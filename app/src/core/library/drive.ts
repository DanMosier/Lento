/** The few Google Drive calls the Library needs, plus an offline copy of what was opened. */

export interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
  modifiedTime?: string;
  webViewLink?: string;
}

/** Gets an OAuth access token; `fresh` asks for a new one after a 401. */
export type TokenSource = (fresh?: boolean) => Promise<string>;

const API = "https://www.googleapis.com/drive/v3/files";
const FIELDS = "id,name,mimeType,modifiedTime,webViewLink";

export class Drive {
  constructor(
    private readonly token: TokenSource,
    private readonly fetcher: typeof fetch = (...a) => fetch(...a),
  ) {}

  private async request(url: string, init: RequestInit = {}): Promise<Response> {
    const go = async (fresh: boolean) =>
      this.fetcher(url, { ...init, headers: { ...(init.headers as Record<string, string>), Authorization: `Bearer ${await this.token(fresh)}` } });
    let res = await go(false);
    if (res.status === 401) res = await go(true);
    if (!res.ok) {
      let why = `${res.status}`;
      try {
        why = ((await res.json()) as { error?: { message?: string } }).error?.message ?? why;
      } catch {
        /* not JSON */
      }
      throw new Error(`Google Drive said: ${why}`);
    }
    return res;
  }

  /** The file or folder called `name` directly inside `folderId`, or null. */
  async child(folderId: string, name: string): Promise<DriveFile | null> {
    const q = `'${quote(folderId)}' in parents and name = '${quote(name)}' and trashed = false`;
    const url = `${API}?${new URLSearchParams({ q, fields: `files(${FIELDS})`, pageSize: "10", supportsAllDrives: "true", includeItemsFromAllDrives: "true" })}`;
    const { files } = (await (await this.request(url)).json()) as { files: DriveFile[] };
    return files[0] ?? null;
  }

  /** Creates a folder, or a small JSON file, inside `parentId`. */
  async create(parentId: string, name: string, content?: object): Promise<DriveFile> {
    const meta = { name, parents: [parentId], mimeType: content ? "application/json" : "application/vnd.google-apps.folder" };
    if (!content) {
      const res = await this.request(`${API}?fields=${FIELDS}&supportsAllDrives=true`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(meta),
      });
      return (await res.json()) as DriveFile;
    }
    const boundary = "lento" + Math.random().toString(36).slice(2);
    const body =
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n` +
      `--${boundary}\r\nContent-Type: application/json\r\n\r\n${JSON.stringify(content)}\r\n--${boundary}--`;
    const res = await this.request(`https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=${FIELDS}&supportsAllDrives=true`, {
      method: "POST",
      headers: { "Content-Type": `multipart/related; boundary=${boundary}` },
      body,
    });
    return (await res.json()) as DriveFile;
  }

  /** Replaces the contents of a JSON file this app created. */
  async update(id: string, content: object): Promise<DriveFile> {
    const res = await this.request(`https://www.googleapis.com/upload/drive/v3/files/${encodeURIComponent(id)}?uploadType=media&fields=${FIELDS}&supportsAllDrives=true`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(content),
    });
    return (await res.json()) as DriveFile;
  }

  async download(id: string): Promise<ArrayBuffer> {
    return (await this.request(`${API}/${encodeURIComponent(id)}?alt=media&supportsAllDrives=true`)).arrayBuffer();
  }
}

function quote(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// ---- offline copies ----

export interface Saved {
  data: ArrayBuffer;
  modifiedTime?: string;
  webViewLink?: string;
}

export interface FileCache {
  get(key: string): Promise<Saved | undefined>;
  put(key: string, value: Saved): Promise<void>;
  keys(): Promise<string[]>;
}

export class MemoryCache implements FileCache {
  readonly map = new Map<string, Saved>();
  async get(key: string) {
    return this.map.get(key);
  }
  async put(key: string, value: Saved) {
    this.map.set(key, value);
  }
  async keys() {
    return [...this.map.keys()];
  }
}

/** IndexedDB, so scores opened once still open with no connection. Falls back to memory if blocked. */
export class IdbCache implements FileCache {
  private db: Promise<IDBDatabase | null>;
  private fallback = new MemoryCache();

  constructor(name = "lento-library") {
    this.db = new Promise((resolve) => {
      try {
        const req = indexedDB.open(name, 1);
        req.onupgradeneeded = () => req.result.createObjectStore("files");
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }

  private async run<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
    const db = await this.db;
    if (!db) return undefined;
    return new Promise((resolve) => {
      const req = fn(db.transaction("files", mode).objectStore("files"));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(undefined);
    });
  }

  async get(key: string) {
    if (!(await this.db)) return this.fallback.get(key);
    return this.run<Saved>("readonly", (s) => s.get(key));
  }
  async put(key: string, value: Saved) {
    if (!(await this.db)) return this.fallback.put(key, value);
    await this.run("readwrite", (s) => s.put(value, key));
  }
  async keys() {
    if (!(await this.db)) return this.fallback.keys();
    return ((await this.run<IDBValidKey[]>("readonly", (s) => s.getAllKeys())) ?? []).map(String);
  }
}
