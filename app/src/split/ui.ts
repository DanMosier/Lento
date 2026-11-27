/**
 * The PDF splitter window: every page of the PDF as a small picture, tap the page where a piece starts, name the
 * pieces, then save them to the library in Drive (or download them). It works on a phone as well as the PC: the
 * splitting runs in the browser, nothing goes to the PC. Opened from the To split list in Convert PDF, or with a PDF
 * from this device.
 *
 * Its own module, loaded only when a splitter opens; pdf.js loads only then too (see pdf.ts).
 */
import { timed } from "../core/perf";
import { fileNames, fromBookmarks, pageRange, partsFor, splitFolder, stemOf, toggleStart, type Part } from "./plan";
import type { PdfDoc } from "./pdf";

export interface SplitSource {
  pdfName: string; // the PDF's file name, which names the folder the pieces go in
  title: string; // what the whole PDF is (the library's title, or the file name)
  composer?: string;
  load: () => Promise<ArrayBuffer>;
  /** Saves the pieces to the library; left out for a PDF from this device (download only). */
  save?: (folder: string, files: { name: string; bytes: Uint8Array }[], progress: (done: number) => void) => Promise<{ names: string[]; link?: string }>;
  /** Called after a save, so the PDF can be marked done on the To split list. */
  saved?: () => void;
}

const THUMB = 240; // CSS pixels the pages are drawn at; the grid shows them smaller or at this size

let dlg: HTMLDialogElement | null = null;
let ui: ReturnType<typeof build>;
let src: SplitSource | null = null;
let doc: PdfDoc | null = null;
let pages = 0;
let starts: number[] = [1];
let parts: Part[] = [];
let busy = false;
let saved = false; // saved to the library, and nothing changed since: a second press would only make copies
let opened = 0; // which PDF is showing, so a slow load of an earlier one is thrown away
let observer: IntersectionObserver | null = null;
const near = new Set<number>(); // pages in or close to view, not drawn yet
let drawing = false;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Partial<HTMLElementTagNameMap[K]> = {}, ...kids: (Node | string)[]): HTMLElementTagNameMap[K] {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids);
  return e;
}

function build() {
  const close = el("button", { type: "button", id: "sp-close", textContent: "✕", ariaLabel: "Close" });
  const name = el("strong", { id: "sp-name" });
  const sub = el("small", { id: "sp-sub" });
  const size = el("button", { type: "button", id: "sp-size", textContent: "Bigger pages", title: "Show the pages larger, to read titles" });
  size.setAttribute("aria-pressed", "false");
  const hint = el("p", { className: "hint sp-hint", textContent: "Tap the page where each piece starts. Tap it again to undo." });
  const grid = el("div", { id: "sp-grid", className: "sp-grid" });
  grid.setAttribute("role", "list");
  grid.setAttribute("aria-label", "Pages");
  const list = el("ol", { id: "sp-parts", className: "sp-parts" });
  const summary = el("summary", { id: "sp-parts-title", textContent: "Pieces" });
  const partsBox = el("details", { className: "sp-parts-box", open: true }, summary, list);
  const download = el("button", { type: "button", id: "sp-download", textContent: "Download" });
  const save = el("button", { type: "button", id: "sp-save", className: "primary", textContent: "Save to library" });
  const statusLine = el("p", { id: "sp-status", className: "status", role: "status" });
  statusLine.setAttribute("aria-live", "polite");
  const d = el(
    "dialog",
    { id: "sp", className: "sp rv", ariaLabel: "Split a PDF" },
    el("header", { className: "rv-top" }, el("div", { className: "rv-title" }, name, sub), size, close),
    hint,
    grid,
    partsBox,
    el("footer", { className: "rv-bottom sp-bottom" }, download, save, statusLine),
  );
  document.body.append(d);
  close.addEventListener("click", () => leave());
  d.addEventListener("cancel", (e) => {
    if (busy) e.preventDefault(); // don't close halfway through an upload
  });
  d.addEventListener("close", reset);
  size.addEventListener("click", () => {
    size.setAttribute("aria-pressed", String(grid.classList.toggle("big")));
  });
  grid.addEventListener("click", (e) => {
    const cell = (e.target as Element).closest<HTMLButtonElement>(".sp-page");
    if (!cell || busy) return;
    starts = toggleStart(starts, Number(cell.dataset.page), pages);
    saved = false;
    refresh();
    const kept = parts.filter((p) => p.keep).length;
    status(`${parts.length} piece${parts.length === 1 ? "" : "s"}${kept < parts.length ? ` (${kept} kept)` : ""}. Name them below, then save.`);
  });
  download.addEventListener("click", () => void downloadParts());
  save.addEventListener("click", () => void saveParts());
  return { dialog: d, name, sub, grid, list, summary, download, save, status: statusLine, size };
}

function status(text: string, kind: "info" | "error" | "ok" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function leave(): void {
  if (busy) return status("Still saving. It closes by itself when done, or wait a moment.");
  ui.dialog.close();
}

function reset(): void {
  opened++;
  observer?.disconnect();
  observer = null;
  near.clear();
  void doc?.destroy();
  doc = null;
  ui.grid.replaceChildren();
  ui.list.replaceChildren();
}

let bookmarkTitles = new Map<number, string>(); // start page -> title, from the PDF's bookmarks
const titleFor = (n: number, start: number) => bookmarkTitles.get(start) || `${src?.title ?? "Piece"} - Piece ${n}`;

export async function openSplitter(source: SplitSource): Promise<void> {
  dlg ??= (ui = build()).dialog;
  if (ui.dialog.open) ui.dialog.close();
  src = source;
  const mine = ++opened;
  pages = 0;
  starts = [1];
  parts = [];
  bookmarkTitles = new Map();
  saved = false;
  ui.name.textContent = source.title;
  ui.sub.textContent = source.pdfName;
  ui.save.hidden = !source.save;
  ui.download.classList.toggle("primary", !source.save);
  ui.save.disabled = ui.download.disabled = true;
  ui.grid.replaceChildren();
  ui.list.replaceChildren();
  status("Loading the PDF…");
  ui.dialog.showModal();
  try {
    await timed("split-open", async () => {
      const [{ openPdf, bookmarks }, data] = await Promise.all([import("./pdf"), source.load()]);
      if (mine !== opened) return;
      const d = await openPdf(new Uint8Array(data));
      if (mine !== opened) return void d.destroy();
      doc = d;
      pages = d.numPages;
      const marks = fromBookmarks(await bookmarks(d), pages);
      starts = marks?.starts ?? [1];
      bookmarkTitles = marks?.titles ?? new Map();
      parts = partsFor(starts, pages, [], titleFor);
      fillGrid();
      refresh();
      status(
        marks
          ? `${pages} pages. The PDF's bookmarks suggest ${parts.length} pieces: check where each starts, then save.`
          : `${pages} pages. Tap the first page of each piece after the first.`,
      );
    });
  } catch (e) {
    if (mine === opened) status((e as Error).message || "Couldn't open this PDF.", "error");
  }
}

function fillGrid(): void {
  observer = new IntersectionObserver(
    (seen) => {
      for (const s of seen) {
        const n = Number((s.target as HTMLElement).dataset.page);
        if (s.isIntersecting) near.add(n);
        else near.delete(n); // scrolled past before its turn: skip it for now
      }
      void drawNext();
    },
    { root: ui.grid, rootMargin: "300px 0px" },
  );
  const cells: HTMLElement[] = [];
  for (let n = 1; n <= pages; n++) {
    const canvas = el("canvas", { width: 85, height: 110 });
    const cell = el(
      "button",
      { type: "button", className: "sp-page" },
      el("span", { className: "sp-thumb" }, canvas),
      el("span", { className: "sp-mark" }),
      el("span", { className: "sp-num", textContent: String(n) }),
    );
    cell.dataset.page = String(n);
    cell.setAttribute("role", "listitem");
    cells.push(cell);
  }
  ui.grid.replaceChildren(...cells);
  for (const c of cells) observer.observe(c);
}

/** Draws the pages near the visible part of the grid, one at a time and in page order, so the page stays responsive. */
async function drawNext(): Promise<void> {
  if (drawing) return;
  drawing = true;
  const mine = opened;
  try {
    while (near.size && doc && mine === opened) {
      const n = Math.min(...near);
      near.delete(n);
      const cell = ui.grid.querySelector<HTMLElement>(`.sp-page[data-page="${n}"]`);
      if (!cell) continue;
      observer?.unobserve(cell);
      try {
        await drawPage(doc, n, cell.querySelector("canvas")!);
      } catch {
        cell.classList.add("sp-broken");
      }
    }
  } finally {
    drawing = false;
  }
}

async function drawPage(d: PdfDoc, n: number, canvas: HTMLCanvasElement): Promise<void> {
  const { drawPage: draw } = await import("./pdf");
  await draw(d, n, canvas, THUMB);
}

/** Redraws the markers on the pages and the list of pieces after a change. */
function refresh(): void {
  parts = partsFor(starts, pages, parts, titleFor);
  const partOf = (page: number) => parts.findIndex((p) => page >= p.start && page <= p.end);
  for (const cell of ui.grid.querySelectorAll<HTMLButtonElement>(".sp-page")) {
    const page = Number(cell.dataset.page);
    const i = partOf(page);
    const p = parts[i];
    const isStart = p?.start === page;
    cell.classList.toggle("start", isStart);
    cell.classList.toggle("odd", i % 2 === 1);
    cell.classList.toggle("off", !p?.keep);
    cell.querySelector(".sp-mark")!.textContent = isStart ? `Piece ${i + 1}` : "";
    cell.setAttribute("aria-label", `Page ${page}${isStart ? `, piece ${i + 1} starts here` : ""}`);
    cell.setAttribute("aria-pressed", String(isStart));
  }
  ui.list.replaceChildren(
    ...parts.map((p, i) => {
      const keep = el("input", { type: "checkbox", checked: p.keep, ariaLabel: `Keep piece ${i + 1}` });
      const title = el("input", { type: "text", value: p.title, ariaLabel: `Title of piece ${i + 1}` });
      const go = el("button", { type: "button", className: "sp-range", textContent: pageRange(p), title: "Show its first page" });
      const file = el("small", { className: "sp-file" });
      keep.addEventListener("change", () => {
        p.keep = keep.checked;
        saved = false;
        refresh();
      });
      title.addEventListener("input", () => {
        p.title = title.value.trim();
        p.named = !!p.title; // emptied: back to the suggested name
        saved = false;
        ui.save.disabled = busy;
        showNames(); // not a full redraw, which would take the keyboard away
      });
      go.addEventListener("click", () => ui.grid.querySelector(`.sp-page[data-page="${p.start}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
      return el("li", { className: p.keep ? "" : "off" }, el("div", { className: "sp-row" }, keep, title, go), file);
    }),
  );
  showNames();
  const kept = parts.filter((p) => p.keep).length;
  ui.summary.textContent = `Pieces (${parts.length})`;
  const ready = !!doc && kept > 0 && !busy;
  ui.download.disabled = !ready;
  ui.save.disabled = !ready || saved;
  ui.save.textContent = saved ? "Saved ✓" : kept === 1 ? "Save 1 PDF to library" : `Save ${kept} PDFs to library`;
  ui.download.textContent = kept > 1 ? `Download ${kept} PDFs` : "Download";
}

/** Under each piece, the file it will be saved as. */
function showNames(): void {
  const names = fileNames(parts, src?.composer);
  let k = 0;
  ui.list.querySelectorAll(".sp-file").forEach((f, i) => (f.textContent = parts[i]?.keep ? names[k++] : "Left out"));
}

/** The new PDFs, one per kept piece, made one after another. */
async function makeParts(): Promise<{ name: string; bytes: Uint8Array }[]> {
  const { extract } = await import("./pdf");
  const kept = parts.filter((p) => p.keep);
  const names = fileNames(parts, src?.composer);
  const out: { name: string; bytes: Uint8Array }[] = [];
  for (const [i, p] of kept.entries()) {
    status(`Making ${i + 1} of ${kept.length}…`);
    out.push({ name: names[i], bytes: await extract(doc!, p.start, p.end) });
  }
  return out;
}

async function run(fn: () => Promise<void>): Promise<void> {
  if (!doc || busy) return;
  busy = true;
  refresh();
  ui.dialog.classList.add("busy");
  try {
    await fn();
  } catch (e) {
    status(`Didn't finish: ${(e as Error).message}`, "error");
  } finally {
    busy = false;
    ui.dialog.classList.remove("busy");
    if (ui.dialog.open) refresh();
  }
}

function saveParts(): Promise<void> {
  return run(async () => {
    const s = src!;
    const files = await makeParts();
    const folder = splitFolder(s.pdfName);
    status(`Saving 1 of ${files.length} to Google Drive…`);
    const { names, link } = await s.save!(folder, files, (done) => status(`Saving ${Math.min(done + 1, files.length)} of ${files.length} to Google Drive…`));
    s.saved?.();
    saved = true;
    ui.status.replaceChildren(
      `Saved ${names.length} PDF${names.length === 1 ? "" : "s"} to inbox/${folder} in your library, ready to file.${s.saved ? " Marked done on the To split list." : ""} `,
      ...(link ? [el("a", { href: link, target: "_blank", rel: "noopener", textContent: "Open the folder" })] : []),
    );
    ui.status.dataset.kind = "ok";
  });
}

function downloadParts(): Promise<void> {
  return run(async () => {
    const s = src!;
    const files = await makeParts();
    let blob: Blob;
    let name: string;
    if (files.length === 1) {
      blob = new Blob([files[0].bytes as Uint8Array<ArrayBuffer>], { type: "application/pdf" });
      name = files[0].name;
    } else {
      const { zipSync } = await import("fflate");
      const zip = zipSync(Object.fromEntries(files.map((f) => [f.name, [f.bytes, { level: 0 }]])));
      blob = new Blob([zip as Uint8Array<ArrayBuffer>], { type: "application/zip" });
      name = `${splitFolder(s.pdfName)}.zip`;
    }
    const a = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
    status(files.length === 1 ? `Downloaded ${name}.` : `Downloaded ${name} with ${files.length} PDFs.`, "ok");
  });
}

/** Opens the splitter on a PDF chosen from this device. Download only: it isn't in the library. */
export function splitLocalFile(file: File): Promise<void> {
  return openSplitter({ pdfName: file.name, title: stemOf(file.name), load: () => file.arrayBuffer() });
}
