/** The Library tab: browse the score library in Google Drive and open a score into Practice. */
import { $, requestOpenScore, store } from "../core/app";
import { GoogleAuth } from "./auth";
import { Drive, IdbCache } from "./drive";
import { DriveLibrary, fileKey } from "./library";
import { allTags, folderIdFromLink, musicxmlOf, requestName, search, type LibraryFile, type LibraryIndex, type Piece } from "./model";

const SHOWN = 150;

const ui = {
  search: $<HTMLInputElement>("lib-search"),
  tag: $<HTMLSelectElement>("lib-tag"),
  refresh: $<HTMLButtonElement>("lib-refresh"),
  batch: $<HTMLButtonElement>("lib-batch"),
  batchBar: $("lib-batch-bar"),
  batchAll: $<HTMLButtonElement>("lib-batch-all"),
  batchNone: $<HTMLButtonElement>("lib-batch-none"),
  batchGo: $<HTMLButtonElement>("lib-batch-go"),
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
let batch = false;
const selected = new Map<string, { piece: Piece; file: LibraryFile }>(); // by request file name
const requestedHere = new Set<string>(store.get<string[]>("library.requested") ?? []); // asked from this device, not yet in the index

const needsXml = (f: LibraryFile) => f.kind === "pdf" && !f.musicxml;
const isRequested = (f: LibraryFile) => !!f.requested || requestedHere.has(requestName(f));

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
    const stillWaiting = new Set(index.pieces.flatMap((p) => p.files.filter(needsXml).map(requestName)));
    for (const r of [...requestedHere]) if (!stillWaiting.has(r)) requestedHere.delete(r);
    store.set("library.requested", [...requestedHere]);
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

function edition(f: LibraryFile): string {
  return f.edition || f.variant;
}

function button(text: string, cls: string | undefined, onClick: (b: HTMLButtonElement) => void, title?: string): HTMLButtonElement {
  const b = el("button", text, cls);
  b.type = "button";
  if (title) b.title = title;
  b.addEventListener("click", () => onClick(b));
  return b;
}

const QUALITY: Record<string, string> = {
  REVIEW: "Converted automatically: some measures may be wrong",
  UNRELIABLE: "Converted automatically and probably wrong in many places",
};

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
  lastFound = found;
  updateBatchBar();
}

let lastFound: Piece[] = [];

function item(p: Piece): HTMLLIElement {
  const li = el("li", undefined, "piece");
  const head = el("div", undefined, "piece-head");
  head.append(el("strong", p.title), el("span", [p.composer, p.catalog_no, p.key].filter(Boolean).join(" · "), "piece-meta"));
  li.append(head);
  if (p.tags?.length) li.append(el("div", p.tags.join(" · "), "piece-tags"));
  const files = el("div", undefined, "piece-files");
  for (const f of p.files) {
    const row = el("div", undefined, "edition");
    const name = edition(f);
    if (p.files.length > 1 && name) row.append(el("span", name, "edition-name"));
    const xml = musicxmlOf(f);
    if (xml) {
      const key = fileKey(p, xml);
      const b = button("Practice", "primary", (b) => void openFile(p, xml, b), offlineKeys.has(key) ? "Saved on this device, opens offline" : undefined);
      if (offlineKeys.has(key)) b.append(el("span", " ✓", "saved"));
      row.append(b);
      if (xml.quality && QUALITY[xml.quality]) {
        const q = el("span", xml.quality === "REVIEW" ? "check" : "unreliable", `quality ${xml.quality.toLowerCase()}`);
        q.title = QUALITY[xml.quality];
        row.append(q);
      }
    }
    if (f.kind === "pdf") row.append(button("PDF", undefined, (b) => void openFile(p, f, b)));
    if (needsXml(f)) {
      if (batch && !isRequested(f)) {
        const box = el("label", undefined, "pick");
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = selected.has(requestName(f));
        cb.addEventListener("change", () => {
          if (cb.checked) selected.set(requestName(f), { piece: p, file: f });
          else selected.delete(requestName(f));
          updateBatchBar();
        });
        box.append(cb, " Convert");
        row.append(box);
      } else if (isRequested(f)) {
        row.append(el("span", "MusicXML requested", "requested"));
      } else {
        row.append(button("Make MusicXML", undefined, (b) => void request([{ piece: p, file: f }], b), "Ask your PC to make MusicXML from this PDF with homr"));
      }
    }
    files.append(row);
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

async function request(items: { piece: Piece; file: LibraryFile }[], button?: HTMLButtonElement): Promise<void> {
  const lib = setup();
  if (!lib || !items.length) return;
  if (button) button.disabled = true;
  ui.batchGo.disabled = true;
  status(`Asking for MusicXML for ${items.length} PDF${items.length > 1 ? "s" : ""}…`);
  try {
    const made = await lib.requestConversion(items);
    for (const it of items) {
      requestedHere.add(requestName(it.file));
      selected.delete(requestName(it.file));
    }
    store.set("library.requested", [...requestedHere]);
    render();
    status(
      `${made || items.length} PDF${items.length > 1 ? "s" : ""} queued. On your PC, run "lento-library convert" in the library folder; ` +
        "the MusicXML appears here after the next Refresh.",
    );
  } catch (e) {
    status(`${(e as Error).message} You can also run "lento-library convert --missing" on your PC.`, "error");
  } finally {
    if (button) button.disabled = false;
    updateBatchBar();
  }
}

function updateBatchBar(): void {
  ui.batchBar.hidden = !batch;
  ui.batch.setAttribute("aria-pressed", String(batch));
  ui.batchGo.textContent = `Request MusicXML for ${selected.size} PDF${selected.size === 1 ? "" : "s"}`;
  ui.batchGo.disabled = selected.size === 0;
}

ui.batch.addEventListener("click", () => {
  batch = !batch;
  if (!batch) selected.clear();
  render();
});
ui.batchAll.addEventListener("click", () => {
  for (const p of lastFound) for (const f of p.files) if (needsXml(f) && !isRequested(f)) selected.set(requestName(f), { piece: p, file: f });
  render();
});
ui.batchNone.addEventListener("click", () => {
  selected.clear();
  render();
});
ui.batchGo.addEventListener("click", () => void request([...selected.values()]));

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
