/** The Library screen: browse the score library in Google Drive and open a score into Practice. */
import { $, requestOpenScore } from "../core/app";
import { cache, library as connect, libraryChanged, onLibraryChanged, requestedHere as requests } from "../core/library/connection";
import { fileKey, type DriveLibrary } from "../core/library/library";
import { allTags, musicxmlOf, requestName, search, type LibraryFile, type LibraryIndex, type Piece } from "../core/library/model";

const SHOWN = 150;

const ui = {
  search: $<HTMLInputElement>("lib-search"),
  tag: $<HTMLSelectElement>("lib-tag"),
  refresh: $<HTMLButtonElement>("lib-refresh"),
  status: $("lib-status"),
  list: $<HTMLUListElement>("lib-list"),
  setupHint: $("lib-setup-hint"),
};

let index: LibraryIndex | null = null;
let offlineKeys = new Set<string>();

const needsXml = (f: LibraryFile) => f.kind === "pdf" && !f.musicxml;
const isRequested = (f: LibraryFile) => !!f.requested || requests.all().has(requestName(f));

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function setup(): DriveLibrary | null {
  const lib = connect();
  ui.setupHint.hidden = !!lib;
  if (!lib) status("Your library isn't connected yet.");
  return lib;
}

async function refresh(): Promise<void> {
  const lib = setup();
  if (!lib) return;
  ui.refresh.disabled = true;
  status("Loading the library from Google Drive…");
  try {
    index = await lib.loadIndex();
    offlineKeys = new Set(await cache.keys());
    const stillWaiting = new Set(index.pieces.flatMap((p) => p.files.filter(needsXml).map(requestName)));
    const mine = requests.all();
    for (const r of [...mine]) if (!stillWaiting.has(r)) mine.delete(r);
    requests.save(mine);
    render();
    libraryChanged();
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.refresh.disabled = false;
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
}

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
      if (xml.from === "musescore") {
        const q = el("span", "MuseScore", "quality ok");
        q.title = "Exported from a MuseScore file, so the notes are exact";
        row.append(q);
      } else if (xml.quality && QUALITY[xml.quality]) {
        const q = el("span", xml.quality === "REVIEW" ? "check" : "unreliable", `quality ${xml.quality.toLowerCase()}`);
        q.title = QUALITY[xml.quality];
        row.append(q);
      }
    }
    if (f.kind === "pdf") row.append(button("PDF", undefined, (b) => void openFile(p, f, b)));
    if (needsXml(f)) {
      if (isRequested(f)) {
        row.append(el("span", "MusicXML requested", "requested"));
      } else {
        if (f.convert_failed) row.append(el("span", "last conversion failed", "requested"));
        row.append(
          button(f.convert_failed ? "Try again" : "Make MusicXML", undefined, (b) => void request([{ piece: p, file: f }], b), "Ask your PC to make MusicXML from this PDF with homr"),
        );
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
    requestOpenScore({ name: f.name, data: got.data!, pieceId: p.id });
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
  status(`Asking for MusicXML for ${items[0].piece.title}…`);
  try {
    await lib.requestConversion(items);
    const mine = requests.all();
    for (const it of items) mine.add(requestName(it.file));
    requests.save(mine);
    render();
    libraryChanged();
    status('Queued. On your PC, run "lento-library convert" in the library folder; the MusicXML appears here after the next Refresh.');
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

let typing = 0;
ui.search.addEventListener("input", () => {
  clearTimeout(typing);
  typing = window.setTimeout(render, 120);
});
ui.tag.addEventListener("change", render);
ui.refresh.addEventListener("click", () => void refresh());
onLibraryChanged(() => {
  if (!$("view-library").hidden) return; // this screen caused it
  started = false; // reload the saved index next time it opens
});

let started = false;

/** Called when the user opens the tab: show the saved library straight away, even offline. */
export async function enterLibrary(): Promise<void> {
  if (started) return;
  started = true;
  const lib = setup();
  if (!lib) {
    started = false;
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
