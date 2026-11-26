/** The Library screen: browse the score library in Google Drive and open a score into Practice. */
import { $, requestOpenScore } from "../core/app";
import { cache, findLibrary, library as connect, libraryChanged, onLibraryChanged, requestedHere as requests } from "../core/library/connection";
import { fileKey, type DriveLibrary } from "../core/library/library";
import { store } from "../core/app";
import { allTags, musicxmlOf, requestName, type LibraryFile, type LibraryIndex, type Piece } from "../core/library/model";
import { timed } from "../core/perf";
import { cell, choices, COLUMNS, rows, type ColumnId, type Filters, type Sort } from "./table";

const ROW = 48; // px, matches --row in style.css
const OVERSCAN = 8;

const ui = {
  search: $<HTMLInputElement>("lib-search"),
  genre: $<HTMLSelectElement>("lib-genre"),
  instr: $<HTMLSelectElement>("lib-instr"),
  level: $<HTMLSelectElement>("lib-level"),
  tag: $<HTMLSelectElement>("lib-tag"),
  xml: $<HTMLSelectElement>("lib-xml"),
  clear: $<HTMLButtonElement>("lib-clear"),
  refresh: $<HTMLButtonElement>("lib-refresh"),
  status: $("lib-status"),
  table: $("lib-table"),
  head: $("lib-head"),
  body: $("lib-body"),
  detail: $<HTMLDialogElement>("lib-detail"),
  detailBody: $("lib-detail-body"),
  detailClose: $<HTMLButtonElement>("lib-detail-close"),
  setupHint: $("lib-setup-hint"),
  connect: $<HTMLButtonElement>("lib-connect"),
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
  ui.table.hidden = !lib;
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
    menus();
    render();
    fitTable();
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

// the title column shrinks on a phone so some of the next column shows, which says "scroll sideways"
ui.table.style.setProperty("--cols", COLUMNS.map((c, i) => (i ? `${c.width}px` : `min(${c.width}px, 44vw)`)).join(" "));
// a fixed row size lets the browser lay out each row on its own (see contain in style.css)
ui.table.style.setProperty("--roww", `calc(min(${COLUMNS[0].width}px, 44vw) + ${COLUMNS.slice(1).reduce((s, c) => s + c.width, 0)}px)`);
let sort: Sort = store.get<Sort>("library.sort") ?? { by: "composer", desc: false };
let shown: Piece[] = [];
let open: Piece | null = null; // the piece in the details window

function fill(sel: HTMLSelectElement, all: string, values: string[]): void {
  const chosen = sel.value;
  sel.replaceChildren(new Option(all, ""), ...values.map((v) => new Option(v, v, false, v === chosen)));
  sel.hidden = values.length === 0;
  if (!values.includes(chosen)) sel.value = "";
}

function filters(): Filters {
  return { query: ui.search.value, genre: ui.genre.value, instrumentation: ui.instr.value, level: ui.level.value, tag: ui.tag.value, musicxml: ui.xml.value };
}

/** Rebuilds the filter menus (after a new index). */
function menus(): void {
  if (!index) return;
  fill(ui.genre, "Every genre / era", choices(index.pieces, "genre"));
  fill(ui.instr, "Any instrumentation", choices(index.pieces, "instrumentation"));
  fill(ui.level, "Every level", choices(index.pieces, "level"));
  fill(ui.tag, "Every technique", allTags(index.pieces));
}

function header(): void {
  ui.head.replaceChildren(
    ...COLUMNS.map((c) => {
      const h = el("div", undefined, "lib-cell");
      h.setAttribute("role", "columnheader");
      if (sort.by === c.id) h.setAttribute("aria-sort", sort.desc ? "descending" : "ascending");
      const b = el("button", c.label);
      b.type = "button";
      b.title = `Sort by ${c.label.toLowerCase()}`;
      b.addEventListener("click", () => sortBy(c.id));
      h.append(b);
      return h;
    }),
  );
}

function sortBy(id: ColumnId): void {
  sort = sort.by === id ? { by: id, desc: !sort.desc } : { by: id, desc: false };
  store.set("library.sort", sort);
  render();
}

function render(): void {
  if (!index) return;
  void timed("library-render", renderNow);
}

function renderNow(): void {
  if (!index) return;
  const f = filters();
  shown = rows(index.pieces, f, sort);
  ui.clear.hidden = !(f.genre || f.instrumentation || f.level || f.tag || f.musicxml);
  const when = index.generated ? ` · index from ${new Date(index.generated).toLocaleDateString()}` : "";
  status(shown.length === index.pieces.length ? `${index.pieces.length} pieces${when}` : `${shown.length} of ${index.pieces.length} pieces`);
  header();
  ui.table.setAttribute("aria-rowcount", String(shown.length + 1));
  ui.body.style.height = `${shown.length * ROW}px`;
  drawn = "";
  clearRows();
  if (!shown.length) {
    ui.body.replaceChildren(el("div", index.pieces.length ? "No pieces match. Try fewer words or clear the filters." : "The library is empty.", "lib-empty"));
    ui.body.style.height = "";
  } else draw();
  if (open) showDetail(open); // its buttons may have changed
}

let drawn = ""; // the first and last row drawn, so scrolling within them does nothing

/** Draws only the rows in view (plus a few either side): 2,000 pieces cost the same as 30. */
function draw(): void {
  const top = ui.table.scrollTop;
  const h = ui.table.clientHeight || 600;
  const from = Math.max(0, Math.floor(top / ROW) - OVERSCAN);
  const to = Math.min(shown.length, Math.ceil((top + h) / ROW) + OVERSCAN);
  const key = `${from}:${to}`;
  if (key === drawn) return;
  drawn = key;
  // rows that scrolled out are reused for the ones scrolling in: only their text and position change
  const free: HTMLElement[] = [];
  for (const [i, r] of live) if (i < from || i >= to) (free.push(r), live.delete(i));
  for (let i = from; i < to; i++) {
    if (live.has(i)) continue;
    let r = free.pop();
    if (!r) ui.body.append((r = newRow()));
    fillRow(r, shown[i], i);
    live.set(i, r);
  }
  for (const r of free) r.remove();
}

const live = new Map<number, HTMLElement>(); // row index -> its element

function clearRows(): void {
  live.clear();
  ui.body.replaceChildren();
}

function newRow(): HTMLElement {
  const r = el("div", undefined, "lib-row");
  r.setAttribute("role", "row");
  r.tabIndex = 0;
  COLUMNS.forEach((c, k) => {
    // plain text cells (fewer elements to lay out while scrolling); only the title has a span, for two lines
    const d = el("div", undefined, `lib-c${c.numeric ? " num" : ""}${c.id === "composer" || c.id === "year" ? " muted" : ""}`);
    d.setAttribute("role", "cell");
    if (k === 0) d.append(el("span"));
    r.append(d);
  });
  return r;
}

function fillRow(r: HTMLElement, p: Piece, i: number): void {
  r.setAttribute("aria-rowindex", String(i + 2));
  r.style.transform = `translateY(${i * ROW}px)`;
  r.dataset.i = String(i);
  COLUMNS.forEach((c, k) => {
    const v = cell(p, c.id);
    const d = (k === 0 ? r.children[0].firstElementChild : r.children[k]) as HTMLElement;
    if (d.textContent !== v) d.textContent = v;
    if (c.id === "musicxml") d.dataset.xml = v;
    if ((d.title !== "") !== v.length > 18) d.title = v.length > 18 ? v : "";
  });
}

function fitTable(): void {
  if ($("view-library").hidden) return;
  const top = ui.table.getBoundingClientRect().top;
  ui.table.style.height = `${Math.max(240, window.innerHeight - top - 12)}px`;
  drawn = "";
  if (shown.length) draw();
}

function showDetail(p: Piece): void {
  open = p;
  const facts = el("dl", undefined, "lib-facts");
  for (const c of COLUMNS) {
    if (c.id === "title" || c.id === "composer" || c.id === "musicxml" || c.id === "editions") continue;
    const v = cell(p, c.id);
    if (v) facts.append(el("dt", c.label), el("dd", v));
  }
  if (p.catalog_no) facts.append(el("dt", "Catalogue"), el("dd", p.catalog_no));
  if (p.notes) facts.append(el("dt", "Notes"), el("dd", p.notes));
  const it = item(p);
  it.querySelector(".piece-head")?.after(facts);
  ui.detailBody.replaceChildren(it);
  if (!ui.detail.open) ui.detail.showModal();
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
      } else if (xml.review === "approved" || xml.review === "rejected") {
        const q = el("span", xml.review === "approved" ? "approved" : "rejected", `rv-badge ${xml.review}`);
        q.title = xml.review === "approved" ? "You checked this against the PDF and approved it" : "You rejected this conversion in Convert PDF's Review tab";
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
  typing = window.setTimeout(() => {
    ui.table.scrollTop = 0;
    render();
  }, 120);
});
for (const sel of [ui.genre, ui.instr, ui.level, ui.tag, ui.xml])
  sel.addEventListener("change", () => {
    ui.table.scrollTop = 0;
    render();
  });
ui.clear.addEventListener("click", () => {
  for (const sel of [ui.genre, ui.instr, ui.level, ui.tag, ui.xml]) sel.value = "";
  ui.table.scrollTop = 0;
  render();
});
let frame = 0;
ui.table.addEventListener(
  "scroll",
  () => {
    if (!frame)
      frame = requestAnimationFrame(() => {
        frame = 0;
        draw();
      });
  },
  { passive: true },
);
const pick = (e: Event) => {
  const r = (e.target as HTMLElement).closest<HTMLElement>(".lib-body .lib-row");
  if (r?.dataset.i) showDetail(shown[Number(r.dataset.i)]);
};
ui.body.addEventListener("click", pick);
ui.body.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    pick(e);
  }
});
ui.detailClose.addEventListener("click", () => ui.detail.close());
ui.detail.addEventListener("click", (e) => {
  if (e.target === ui.detail) ui.detail.close(); // a tap on the backdrop
});
ui.detail.addEventListener("close", () => (open = null));
window.addEventListener("resize", fitTable, { passive: true });
ui.refresh.addEventListener("click", () => void refresh());
ui.connect.addEventListener("click", async () => {
  ui.connect.disabled = true;
  status("Looking for your library in Google Drive…");
  try {
    if (await findLibrary()) await refresh();
    else status("Couldn't find a library (a folder with library.json) in your Drive. Choose its folder in Settings.", "error");
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.connect.disabled = false;
  }
});
onLibraryChanged(() => {
  if (!$("view-library").hidden) return; // this screen caused it
  started = false; // reload the saved index next time it opens
});

let started = false;

/** Called when the user opens the tab: show the saved library straight away, even offline. */
export async function enterLibrary(): Promise<void> {
  requestAnimationFrame(fitTable);
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
  if (index) {
    menus();
    render();
    requestAnimationFrame(fitTable);
  } else status("Press Refresh to load your library from Google Drive.");
}
