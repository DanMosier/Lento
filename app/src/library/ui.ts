/** The Library tab: browse the score library in Google Drive and open a score into Practice. */
import { $, requestOpenScore, store } from "../core/app";
import { GoogleAuth } from "./auth";
import { Drive, IdbCache } from "./drive";
import { DriveLibrary, fileKey } from "./library";
import { allTags, folderIdFromLink, search, type LibraryFile, type LibraryIndex, type Piece } from "./model";

const SHOWN = 150;

const ui = {
  search: $<HTMLInputElement>("lib-search"),
  tag: $<HTMLSelectElement>("lib-tag"),
  refresh: $<HTMLButtonElement>("lib-refresh"),
  status: $("lib-status"),
  list: $<HTMLUListElement>("lib-list"),
  setup: $<HTMLDetailsElement>("lib-setup"),
  folder: $<HTMLInputElement>("lib-folder"),
  client: $<HTMLInputElement>("lib-client"),
  connect: $<HTMLButtonElement>("lib-connect"),
  signOut: $<HTMLButtonElement>("lib-signout"),
};

const auth = new GoogleAuth();
const cache = new IdbCache();
let library: DriveLibrary | null = null;
let index: LibraryIndex | null = null;
let offlineKeys = new Set<string>();

ui.folder.value = store.get<string>("library.folder") ?? "";
ui.client.value = store.get<string>("library.client") ?? (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function setup(): DriveLibrary | null {
  const id = folderIdFromLink(ui.folder.value);
  if (!id) {
    ui.setup.open = true;
    status("Paste the link to your library folder in Google Drive, then connect.", "error");
    return null;
  }
  if (library?.rootId !== id) {
    const drive = new Drive((fresh) => auth.getToken(ui.client.value.trim(), fresh));
    library = new DriveLibrary(id, drive, cache);
  }
  return library;
}

async function refresh(): Promise<void> {
  const lib = setup();
  if (!lib) return;
  ui.refresh.disabled = ui.connect.disabled = true;
  status("Loading the library from Google Drive…");
  try {
    index = await lib.loadIndex();
    offlineKeys = new Set(await cache.keys());
    ui.setup.open = false;
    render();
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.refresh.disabled = ui.connect.disabled = false;
    ui.signOut.hidden = !auth.signedIn;
  }
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function label(f: LibraryFile): string {
  const what = f.kind === "musicxml" ? "Practice" : "PDF";
  const v = f.edition || f.variant;
  return v ? `${what} · ${v}` : what;
}

function render(): void {
  if (!index) return;
  const tags = allTags(index.pieces);
  const chosen = ui.tag.value;
  ui.tag.replaceChildren(new Option("All techniques", ""), ...tags.map((t) => new Option(t, t, false, t === chosen)));
  ui.tag.hidden = tags.length === 0;
  const found = search(index.pieces, ui.search.value, ui.tag.value);
  const when = index.generated ? ` · index from ${new Date(index.generated).toLocaleDateString()}` : "";
  status(
    found.length === index.pieces.length
      ? `${index.pieces.length} pieces${when}`
      : `${found.length} of ${index.pieces.length} pieces${found.length > SHOWN ? `, showing the first ${SHOWN}` : ""}`,
  );
  ui.list.replaceChildren(...found.slice(0, SHOWN).map(item));
}

function item(p: Piece): HTMLLIElement {
  const li = el("li", undefined, "piece");
  const head = el("div", undefined, "piece-head");
  head.append(el("strong", p.title), el("span", [p.composer, p.catalog_no, p.key].filter(Boolean).join(" · "), "piece-meta"));
  li.append(head);
  if (p.tags?.length) li.append(el("div", p.tags.join(" · "), "piece-tags"));
  const files = el("div", undefined, "piece-files");
  const ordered = [...p.files].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "musicxml" ? -1 : 1));
  for (const f of ordered) {
    const b = el("button", label(f), f.kind === "musicxml" ? "primary" : undefined);
    b.type = "button";
    if (offlineKeys.has(fileKey(p, f))) b.title = "Saved on this device, opens offline";
    if (offlineKeys.has(fileKey(p, f))) b.append(el("span", " ✓", "saved"));
    b.addEventListener("click", () => void openFile(p, f, b));
    files.append(b);
  }
  li.append(files);
  return li;
}

async function openFile(p: Piece, f: LibraryFile, button: HTMLButtonElement): Promise<void> {
  const lib = setup();
  if (!lib) return;
  // Open the window now, while we still have the click, so the PDF isn't blocked as a popup.
  const win = f.kind === "pdf" ? window.open("", "_blank") : null;
  button.disabled = true;
  status(`Opening ${p.title}…`);
  try {
    const got = await lib.open(p, f);
    if (f.kind === "pdf") {
      if (got.link && win) win.location.href = got.link;
      else win?.close();
      status(got.link ? `${p.title}: PDF opened in a new tab.` : "Could not get a link to that PDF.");
      return;
    }
    offlineKeys.add(fileKey(p, f));
    requestOpenScore({ name: f.name, data: got.data! });
    status(got.offline ? `${p.title}: opened the copy saved on this device (Drive not reachable).` : `${p.title}: opened in Practice.`);
    render();
  } catch (e) {
    win?.close();
    status((e as Error).message, "error");
  } finally {
    button.disabled = false;
  }
}

let typing = 0;
ui.search.addEventListener("input", () => {
  clearTimeout(typing);
  typing = window.setTimeout(render, 120);
});
ui.tag.addEventListener("change", render);
ui.refresh.addEventListener("click", () => void refresh());
ui.connect.addEventListener("click", () => {
  store.set("library.folder", ui.folder.value.trim());
  store.set("library.client", ui.client.value.trim());
  void refresh();
});
ui.signOut.addEventListener("click", () => {
  auth.signOut();
  ui.signOut.hidden = true;
  status("Signed out. Saved scores still open on this device.");
});

let started = false;

/** Called when the user opens the tab: show the saved library straight away, even offline. */
export async function enterLibrary(): Promise<void> {
  if (started) return;
  started = true;
  const lib = setup();
  if (!lib) {
    status("Connect your Google Drive library folder to browse your scores here.");
    ui.status.dataset.kind = "info";
    return;
  }
  try {
    index = await lib.cachedIndex();
    offlineKeys = new Set(await cache.keys());
  } catch {
    index = null;
  }
  if (index) render();
  else status("Press Refresh to load your library from Google Drive.");
}
