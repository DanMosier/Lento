/**
 * The Convert PDF screen: pick PDFs in the library that have no MusicXML yet and queue them for your PC.
 * The conversion itself (homr, which needs the PC's graphics card) runs there with `lento-library convert`;
 * this screen writes the small request files it picks up and shows what is waiting and what is done.
 */
import { $ } from "../core/app";
import { library, libraryChanged, onLibraryChanged, requestedHere, reviewedHere } from "../core/library/connection";
import type { LibraryFile, LibraryIndex, Piece } from "../core/library/model";
import { fold, musicxmlOf, pcOnline, requestName, requestNameOf, type PcStatus } from "../core/library/model";
import { buildQueue, duration, item, namesOf, type Names, type QueueItem } from "./queue";
import type { ReviewItem } from "./review";
import { flagged, isFlagged, recentlyDone, setSplit, type SplitEntry } from "./split-list";
import { changeSplit, currentSplit, onSplitChanged, splitSyncNote, syncSplit } from "./split-store";

const SHOWN = 200;

const ui = {
  refresh: $<HTMLButtonElement>("cv-refresh"),
  search: $<HTMLInputElement>("cv-search"),
  status: $("cv-status"),
  pc: $("cv-pc"),
  setupHint: $("cv-setup-hint"),
  counts: $("cv-counts"),
  all: $<HTMLButtonElement>("cv-all"),
  none: $<HTMLButtonElement>("cv-none"),
  go: $<HTMLButtonElement>("cv-go"),
  todo: $<HTMLUListElement>("cv-todo"),
  tabPick: $<HTMLButtonElement>("cv-tab-pick"),
  tabQueue: $<HTMLButtonElement>("cv-tab-queue"),
  tabReview: $<HTMLButtonElement>("cv-tab-review"),
  reviews: $("cv-reviews"),
  rvFilter: $<HTMLSelectElement>("cv-rv-filter"),
  rvList: $<HTMLUListElement>("cv-rv-list"),
  splitOpen: $<HTMLButtonElement>("cv-split-open"),
  split: $<HTMLDialogElement>("cv-split"),
  splitTitle: $("cv-split-title"),
  splitList: $<HTMLUListElement>("cv-split-list"),
  splitNote: $("cv-split-note"),
  splitFile: $<HTMLInputElement>("cv-split-file"),
  pick: $("cv-pick"),
  queue: $("cv-queue"),
  qBatch: $("cv-q-batch"),
  qBatchText: $("cv-q-batch-text"),
  qEta: $("cv-q-eta"),
  qBatchBar: $<HTMLProgressElement>("cv-q-batch-bar"),
  qNow: $<HTMLUListElement>("cv-q-now"),
  qNext: $<HTMLOListElement>("cv-q-next"),
  qPickupBox: $("cv-q-pickup-box"),
  qPickup: $<HTMLUListElement>("cv-q-pickup"),
  qRecent: $<HTMLUListElement>("cv-q-recent"),
  qAll: $<HTMLButtonElement>("cv-q-all"),
  qNone: $<HTMLButtonElement>("cv-q-none"),
  qRemove: $<HTMLButtonElement>("cv-q-remove"),
  failedBox: $<HTMLDetailsElement>("cv-failed-box"),
  failedTitle: $("cv-failed-title"),
  failed: $<HTMLUListElement>("cv-failed"),
  failedAll: $<HTMLButtonElement>("cv-failed-all"),
  retry: $<HTMLButtonElement>("cv-retry"),
};

type Item = { piece: Piece; file: LibraryFile };
let index: LibraryIndex | null = null;
let names: Names = new Map();
let pc: PcStatus | null = null; // the watcher's last status
const removedHere = new Set<string>(); // PDF names taken off the queue on this device (until the index says so too)
const qSelected = new Set<string>(); // PDF names ticked in the Queue tab
let removable: string[] = []; // the PDF names that have a checkbox right now
const selected = new Map<string, Item>(); // by request file name
const retrySel = new Map<string, Item>(); // failed ones ticked for "Try again", kept apart from the main selection

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function li(text: string, sub?: string): HTMLLIElement {
  const li = document.createElement("li");
  const b = document.createElement("span");
  b.textContent = text;
  li.append(b);
  if (sub) {
    const s = document.createElement("small");
    s.textContent = sub;
    li.append(s);
  }
  return li;
}

function label(it: Item): [string, string] {
  const ed = it.file.edition || it.file.variant;
  return [it.piece.title, [it.piece.composer, ed].filter(Boolean).join(" · ")];
}

/** Why the PC's last try failed, if it said: from library.json, or from the watcher's recent results. */
function reason(it: Item): string {
  if (it.file.convert_error) return it.file.convert_error;
  const r = pc?.results ? [...pc.results].reverse().find((x) => x.pdf === it.file.name && !x.ok) : undefined;
  return r?.error ?? "";
}

/** A row with a checkbox that adds the item to `sel` (by request file name). */
function checkRow(it: Item, sel: Map<string, Item>, sub: string, onChange: () => void, warn = ""): HTMLLIElement {
  const [t] = label(it);
  const row = li(t, sub);
  if (warn) row.append(Object.assign(document.createElement("small"), { className: "cv-reason", textContent: warn }));
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = sel.has(requestName(it.file));
  box.setAttribute("aria-label", `Convert ${t}`);
  box.addEventListener("change", () => {
    if (box.checked) sel.set(requestName(it.file), it);
    else sel.delete(requestName(it.file));
    onChange();
  });
  const lab = document.createElement("label");
  lab.className = "cv-row";
  lab.append(box, ...Array.from(row.childNodes));
  row.replaceChildren(lab);
  return row;
}

/** Keeps only the selected items still on offer, matched by file name (rows are rebuilt on every render). */
function prune(sel: Map<string, Item>, offer: Item[]): void {
  const open = new Map(offer.map((it) => [requestName(it.file), it] as const));
  for (const k of [...sel.keys()]) {
    const it = open.get(k);
    if (it) sel.set(k, it);
    else sel.delete(k);
  }
}

function render(): void {
  if (!index) return;
  const mine = requestedHere.all();
  const todo: Item[] = [];
  const failed: Item[] = [];
  const waiting: Item[] = [];
  let done = 0;
  for (const piece of index.pieces)
    for (const file of piece.files) {
      if (file.kind !== "pdf") continue;
      const xml = musicxmlOf(file);
      if (xml) done++;
      else if ((file.requested || mine.has(requestName(file))) && !removedHere.has(file.name)) waiting.push({ piece, file });
      else if (file.convert_failed) failed.push({ piece, file }); // set apart, so "Select all shown" can't pick them
      else todo.push({ piece, file });
    }
  const q = fold(ui.search.value.trim());
  const match = (it: Item) => !q || fold(`${it.piece.title} ${it.piece.composer}`).includes(q);
  const shown = todo.filter(match);
  // set first, so "Select all shown" works even if drawing below were to fail
  allVisible = shown.slice(0, SHOWN); // the rows on screen, not every match
  prune(selected, todo);
  prune(retrySel, failed);
  updateGo();

  ui.counts.textContent =
    `${todo.length} PDFs without MusicXML · ${waiting.length} waiting for your PC · ${done} converted` + (failed.length ? ` · ${failed.length} failed` : "");
  ui.todo.replaceChildren(...allVisible.map((it) => checkRow(it, selected, label(it)[1], updateGo)));
  if (shown.length > SHOWN) ui.todo.append(li(`…and ${shown.length - SHOWN} more. Search to narrow the list.`));
  if (!todo.length) ui.todo.append(li(failed.length ? "Every other PDF has MusicXML." : "Every PDF in the library has MusicXML."));

  const failedShown = failed.filter(match);
  ui.failedBox.hidden = !failed.length;
  ui.failedTitle.textContent = `Failed on your PC (${failed.length})`;
  allFailed = failedShown.slice(0, SHOWN);
  ui.failed.replaceChildren(
    ...allFailed.map((it) => checkRow(it, retrySel, label(it)[1], updateGo, reason(it) ? `Failed: ${reason(it)}` : "Failed (no reason given)")),
  );
  if (failed.length && !failedShown.length) ui.failed.append(li("None match the search."));
  if (failedShown.length > SHOWN) ui.failed.append(li(`…and ${failedShown.length - SHOWN} more. Search to narrow the list.`));

  ui.tabQueue.textContent = waiting.length ? `Queue (${waiting.length})` : "Queue";
  renderReviews();
}

// ---- the Review tab ----

/** Every converted score, with the PDF it came from. MuseScore exports are exact, so they aren't listed. */
function conversions(): ReviewItem[] {
  const out: ReviewItem[] = [];
  for (const piece of index?.pieces ?? [])
    for (const file of piece.files) {
      if (file.from === "musescore") continue;
      if (file.kind === "pdf" && file.musicxml) out.push({ piece, pdf: file, xml: musicxmlOf(file)! });
      else if (file.kind === "musicxml") out.push({ piece, pdf: null, xml: file });
    }
  return out;
}

const verdict = (it: ReviewItem, mine: Record<string, string>) => mine[it.xml.name] ?? it.xml.review ?? "";
const QUALITY_ORDER: Record<string, number> = { UNRELIABLE: 0, REVIEW: 1 };

function renderReviews(): void {
  const mine = reviewedHere.all();
  const all = conversions();
  // forget local verdicts once the index has them too
  let tidy = false;
  for (const it of all)
    if (mine[it.xml.name] && mine[it.xml.name] === it.xml.review) {
      delete mine[it.xml.name];
      tidy = true;
    }
  if (tidy) reviewedHere.save(mine);
  const todo = all.filter((it) => !verdict(it, mine)).length;
  ui.tabReview.textContent = todo ? `Review (${todo})` : "Review";
  renderSplitButton();
  if (ui.reviews.hidden) return;
  const want = ui.rvFilter.value;
  const q = fold(ui.search.value.trim());
  const l = currentSplit();
  const toSplit = (it: ReviewItem) => !!it.pdf && isFlagged(l, it.piece.id, it.pdf.name);
  const list = all
    .filter((it) => (want === "all" ? true : want === "todo" ? !verdict(it, mine) : verdict(it, mine) === want))
    .filter((it) => !q || fold(`${it.piece.title} ${it.piece.composer}`).includes(q))
    .sort((a, b) => Number(toSplit(a)) - Number(toSplit(b)) || (QUALITY_ORDER[a.xml.quality ?? ""] ?? 2) - (QUALITY_ORDER[b.xml.quality ?? ""] ?? 2) || a.piece.title.localeCompare(b.piece.title));
  const rows = list.slice(0, SHOWN).map((it, i) => {
    const row = li(it.piece.title, [it.piece.composer, it.xml.edition || it.xml.variant].filter(Boolean).join(" · "));
    const v = verdict(it, mine);
    const badge = v || (it.xml.quality === "UNRELIABLE" ? "unreliable" : it.xml.quality === "REVIEW" ? "review" : "");
    if (toSplit(it))
      row.firstElementChild?.append(Object.assign(document.createElement("span"), { className: "rv-badge split", textContent: "To split" }));
    if (badge) {
      const b = Object.assign(document.createElement("span"), { className: `rv-badge ${badge}`, textContent: { approved: "Approved", rejected: "Rejected", unreliable: "Likely wrong", review: "Check" }[badge] ?? badge });
      row.firstElementChild?.append(b);
    }
    const open = Object.assign(document.createElement("button"), { type: "button", className: "cv-rv-open", textContent: "Review" });
    open.setAttribute("aria-label", `Review ${it.piece.title}`);
    open.addEventListener("click", () => void openAt(list, i));
    row.append(open);
    return row;
  });
  ui.rvList.replaceChildren(...rows);
  if (list.length > SHOWN) ui.rvList.append(li(`…and ${list.length - SHOWN} more. Search to narrow the list.`));
  if (!list.length) ui.rvList.append(li(want === "todo" ? (all.length ? "Nothing left to review." : "No conversions yet.") : "None."));
}

// ---- the To split list (in the Review tab) ----

function splitRow(e: SplitEntry): HTMLLIElement {
  const done = e.state === "done";
  const when = new Date(done ? e.at : e.flagged).toLocaleDateString();
  const row = li(e.title, `${e.pdf} · ${done ? "split" : "flagged"} ${when}`);
  if (done) row.className = "done";
  const acts = Object.assign(document.createElement("span"), { className: "cv-split-acts" });
  const btn = (text: string, aria: string, fn: () => void) => {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: text });
    b.setAttribute("aria-label", `${aria} ${e.title}`);
    b.addEventListener("click", fn);
    acts.append(b);
  };
  const piece = index?.pieces.find((p) => p.id === e.piece);
  const file = piece?.files.find((f) => f.name === e.pdf);
  if (!done && piece && file) {
    btn("Split", "Split", () => void openSplit(piece, file, e));
    btn("PDF", "Open the PDF of", () => void openPdf(piece, file));
  }
  if (done) btn("Undo", "Put back on the list:", () => changeSplit((l) => setSplit(l, e.piece, e.pdf, e.title, "flagged")));
  else {
    btn("Done", "Mark as split:", () => changeSplit((l) => setSplit(l, e.piece, e.pdf, e.title, "done")));
    btn("Unflag", "Take off the list:", () => changeSplit((l) => setSplit(l, e.piece, e.pdf, e.title, "off")));
  }
  row.append(acts);
  return row;
}

/** Opens the splitter (its own module, loaded now) on a flagged PDF; saving marks it done. */
async function openSplit(piece: Piece, file: LibraryFile, e: SplitEntry): Promise<void> {
  const lib = library();
  if (!lib) return;
  try {
    const { openSplitter } = await import("../split/ui");
    await openSplitter({
      pdfName: file.name,
      title: piece.title || e.title,
      composer: piece.composer,
      load: () => lib.downloadPdf(piece, file),
      save: (folder, files, progress) => lib.saveSplit(folder, files, progress),
      saved: () => changeSplit((l) => setSplit(l, e.piece, e.pdf, e.title, "done")),
    });
  } catch (err) {
    status(`Couldn't open the splitter: ${(err as Error).message}`, "error");
  }
}

async function openPdf(piece: Piece, file: LibraryFile): Promise<void> {
  const lib = library();
  if (!lib) return;
  const w = window.open("", "_blank"); // opened during the tap, so the browser doesn't block it
  try {
    const { link } = await lib.open(piece, file, false);
    if (!link) throw new Error("no link");
    if (w) w.location.href = link;
    else window.open(link, "_blank");
  } catch {
    w?.close();
    status("Couldn't open the PDF (offline?).", "error");
  }
}

/** The button in the Review tab that opens the To split screen, with how many are waiting. */
function renderSplitButton(): void {
  const l = currentSplit();
  const n = flagged(l).length;
  ui.splitOpen.hidden = false; // always there: it also splits a PDF from this device
  ui.splitOpen.textContent = n ? `To split (${n})` : "To split";
}

/** The To split screen: drawn only while it's open. */
function renderSplit(): void {
  if (!ui.split.open) return;
  const l = currentSplit();
  const todo = flagged(l);
  const done = recentlyDone(l);
  ui.splitTitle.textContent = todo.length ? `To split (${todo.length})` : "To split";
  ui.splitList.replaceChildren(...todo.map(splitRow), ...done.map(splitRow));
  if (!todo.length) ui.splitList.prepend(li(done.length ? "Nothing left to split." : "Nothing flagged. Flag a PDF from its review window."));
  ui.splitNote.textContent = splitSyncNote();
}
onSplitChanged(() => {
  renderSplit();
  if (!ui.reviews.hidden) renderReviews();
  else renderSplitButton();
});
ui.splitOpen.addEventListener("click", () => {
  ui.split.showModal();
  renderSplit();
});
$("cv-split-close").addEventListener("click", () => ui.split.close());
ui.split.addEventListener("click", (e) => {
  if (e.target === ui.split) ui.split.close(); // a tap on the backdrop
});

async function openAt(list: ReviewItem[], i: number): Promise<void> {
  try {
    const { openReview } = await import("./review");
    openReview(list, i, () => renderReviews());
  } catch (e) {
    status(`Couldn't open the review window: ${(e as Error).message}`, "error");
  }
}

let allFailed: Item[] = [];
let allVisible: Item[] = [];

function updateGo(): void {
  ui.go.textContent = selected.size ? `Queue ${selected.size} for my PC` : "Queue for my PC";
  ui.go.disabled = selected.size === 0;
  ui.retry.textContent = retrySel.size ? `Try ${retrySel.size} again on my PC` : "Try again on my PC";
  ui.retry.disabled = retrySel.size === 0;
}

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function showPc(s: PcStatus | null): void {
  pc = s;
  renderQueue();
  ui.pc.replaceChildren();
  const line = (text: string, cls = "") => {
    const p = document.createElement("p");
    p.textContent = text;
    if (cls) p.className = cls;
    ui.pc.append(p);
  };
  if (!s) {
    ui.pc.dataset.state = "none";
    line("Your PC's watcher hasn't run yet, so queued PDFs wait until you run \"lento-library convert\" there.");
    line('To convert automatically whenever the PC is on, run "lento-library watch --install" once in the library folder.', "hint");
    return;
  }
  const online = pcOnline(s);
  ui.pc.dataset.state = online ? s.state : "offline";
  if (!online) line(`${s.pc || "Your PC"} is off or not watching (last seen ${ago(s.heartbeat)}). Queued PDFs convert when it's back.`);
  else if (s.state === "converting") {
    const now = (s.current_files ?? (s.current ? s.current.split(", ") : [])).map((n) => item(n, names).title).join(", ");
    line(`${s.pc || "Your PC"} is converting ${now}${s.queue.length ? `, ${s.queue.length} more after that` : ""}.`);
  }
  else if (s.state === "exporting") line(`${s.pc || "Your PC"} is exporting ${s.current} from MuseScore.`);
  else line(`${s.pc || "Your PC"} is on and watching (checked ${ago(s.heartbeat)}). New requests start within ${Math.round(s.interval_s || 30)} s.`);
  if (s.musescore === false) line("There are MuseScore files in the library, but MuseScore isn't installed on the PC. Install MuseScore 4 there and they'll be exported.", "hint");
  const recent = [...s.results].reverse().slice(0, 5);
  if (recent.length && ui.queue.hidden) line("Recent: " + recent.map((r) => `${item(r.pdf, names).title} ${r.ok ? "✓" : "failed"}`).join(" · "), "hint");
}

async function loadPc(): Promise<void> {
  const lib = library();
  if (!lib) return;
  try {
    showPc(await lib.pcStatus());
  } catch {
    ui.pc.dataset.state = "unknown";
    ui.pc.textContent = "Couldn't check on your PC (offline, or not signed in to Drive yet).";
  }
}

async function load(fromDrive: boolean): Promise<void> {
  const lib = library();
  ui.setupHint.hidden = !!lib;
  if (!lib) {
    status("Your library isn't connected yet.");
    return;
  }
  ui.refresh.disabled = true;
  try {
    if (fromDrive) status("Loading the library from Google Drive…");
    index = fromDrive ? await lib.loadIndex() : await lib.cachedIndex();
    names = namesOf(index);
    if (!index) status("Press Refresh to load your library from Google Drive.");
    else {
      status(index.generated ? `Library index from ${new Date(index.generated).toLocaleString()}.` : "");
      render();
      if (fromDrive) {
        void syncSplit(true);
        libraryChanged();
        void loadPc();
      }
    }
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.refresh.disabled = false;
  }
}

async function queue(sel: Map<string, Item> = selected): Promise<void> {
  const lib = library();
  if (!lib || !sel.size) return;
  const items = [...sel.values()];
  ui.go.disabled = ui.retry.disabled = true;
  status(`Queueing ${items.length} PDF${items.length > 1 ? "s" : ""}…`);
  try {
    await lib.requestConversion(items);
    const mine = requestedHere.all();
    for (const it of items) {
      mine.add(requestName(it.file));
      removedHere.delete(it.file.name); // queued again after being removed
    }
    requestedHere.save(mine);
    sel.clear();
    render();
    libraryChanged();
    status(`Queued ${items.length}. Your PC converts them when its watcher next looks (or run "lento-library convert" there). Press Refresh to see progress.`);
    void loadPc();
  } catch (e) {
    status((e as Error).message, "error");
    updateGo();
  }
}

// ---- the Queue tab ----

function queueRow(it: QueueItem, extra?: string): HTMLLIElement {
  return li(it.title, [it.sub, extra].filter(Boolean).join(" · "));
}

/** A queued piece with a checkbox, for "Remove from queue". */
function pickRow(it: QueueItem, prefix = ""): HTMLLIElement {
  const row = queueRow({ ...it, title: prefix + it.title });
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = qSelected.has(it.name);
  box.setAttribute("aria-label", `Select ${it.title}`);
  box.addEventListener("change", () => {
    if (box.checked) qSelected.add(it.name);
    else qSelected.delete(it.name);
    updateRemove();
  });
  const lab = document.createElement("label");
  lab.className = "cv-row";
  lab.append(box, ...Array.from(row.childNodes));
  row.replaceChildren(lab);
  return row;
}

function updateRemove(): void {
  ui.qRemove.textContent = qSelected.size ? `Remove ${qSelected.size} from queue` : "Remove from queue";
  ui.qRemove.disabled = qSelected.size === 0;
  ui.qAll.disabled = removable.length === 0;
  ui.qNone.disabled = qSelected.size === 0;
}

async function removeSelected(): Promise<void> {
  const lib = library();
  const names = [...qSelected];
  if (!lib || !names.length) return;
  ui.qRemove.disabled = true;
  status(`Removing ${names.length} from the queue…`);
  try {
    const { removed, failed } = await lib.cancelConversion(names);
    const mine = requestedHere.all();
    for (const n of removed) {
      removedHere.add(n);
      qSelected.delete(n);
      mine.delete(requestNameOf(n));
    }
    requestedHere.save(mine);
    render();
    renderQueue();
    libraryChanged();
    status(
      (removed.length ? `Removed ${removed.length} from the queue. They're back in the list under Choose PDFs.` : "") +
        (failed.length
          ? ` ${failed.length} couldn't be removed from here (queued on the PC itself): delete their files in the library's requests folder there.`
          : ""),
      failed.length ? "error" : "info",
    );
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    updateRemove();
  }
}

let nowBars: { bar: HTMLProgressElement; time: HTMLElement; base: number; avg: number | null; at: number }[] = [];

function renderQueue(): void {
  if (ui.queue.hidden) return; // nothing to draw while the list tab is showing
  const v = buildQueue(pc, index, names, requestedHere.all(), Date.now(), removedHere);
  const online = !!pc && pcOnline(pc);
  ui.qBatch.hidden = !v.batch;
  if (v.batch) {
    ui.qBatchText.textContent = `${v.batch.done} of ${v.batch.total} done`;
    ui.qEta.textContent = v.batch.left_s != null ? `${duration(v.batch.left_s)} left` : "";
    ui.qBatchBar.value = v.batch.total ? v.batch.done / v.batch.total : 0;
  }
  nowBars = [];
  const t = performance.now();
  ui.qNow.replaceChildren(
    ...v.now.map((it, i) => {
      const row = queueRow(it);
      if (i === 0) {
        const bar = document.createElement("progress");
        bar.max = 1;
        bar.setAttribute("aria-label", `Converting ${it.title}`);
        const time = document.createElement("small");
        time.className = "cv-now-time";
        row.append(bar, time);
        if (it.page && it.page.pages > 1) row.append(Object.assign(document.createElement("small"), { className: "cv-now-page", textContent: ` · page ${it.page.page} of ${it.page.pages}` }));
        nowBars.push({ bar, time, base: it.elapsed_s, avg: it.left_s != null ? it.elapsed_s + it.left_s : null, at: t });
      } else row.append(Object.assign(document.createElement("small"), { textContent: "next, same folder" }));
      return row;
    }),
  );
  if (!v.now.length) ui.qNow.append(li(online ? "Nothing right now." : "Nothing: your PC is off or not watching."));
  tick();
  ui.qNext.replaceChildren(...v.next.map((it, i) => pickRow(it, `${i + 1}. `)));
  if (!v.next.length) ui.qNext.append(Object.assign(li("Nothing else in this batch."), { className: "hint" }));
  ui.qPickupBox.hidden = !v.pickup.length;
  ui.qPickup.replaceChildren(...v.pickup.map((it) => pickRow(it)));
  // the one converting now can't be stopped half way, so only what's waiting has a checkbox
  removable = [...v.next, ...v.pickup].map((it) => it.name);
  const keep = new Set(removable);
  for (const n of [...qSelected]) if (!keep.has(n)) qSelected.delete(n);
  updateRemove();
  ui.qRecent.replaceChildren(
    ...v.recent.map((r) => {
      const row = queueRow(r, `${ago(r.at)}${r.seconds ? `, took ${duration(r.seconds).replace("about ", "")}` : ""}`);
      const mark = document.createElement("span");
      mark.className = r.ok ? "cv-ok" : "cv-bad";
      mark.textContent = r.ok ? " ✓" : " failed";
      row.firstElementChild?.append(mark);
      return row;
    }),
  );
  if (!v.recent.length) ui.qRecent.append(li("Nothing yet."));
}

/** Moves the progress bar of the PDF converting now along; touches only that bar and one line of text. */
function tick(): void {
  for (const b of nowBars) {
    const e = b.base + (performance.now() - b.at) / 1000;
    if (b.avg) {
      b.bar.value = Math.min(0.95, e / b.avg);
      b.time.textContent = e < b.avg ? `${duration(e).replace("about ", "")} in, ${duration(b.avg - e)} left` : `${duration(e).replace("about ", "")} in, taking longer than usual`;
    } else {
      b.bar.removeAttribute("value"); // no timings yet: an animated bar
      b.time.textContent = `${duration(e).replace("about ", "")} in`;
    }
  }
}

let poll = 0;
let ticker = 0;
function queueVisible(): boolean {
  return !ui.queue.hidden && !$("view-convert").hidden && document.visibilityState === "visible";
}
/** While the Queue tab is on screen: check the PC every 15 s and move the bar every second. Otherwise nothing runs. */
function updateTimers(): void {
  const on = queueVisible();
  if (on && !poll) {
    poll = window.setInterval(() => void loadPc(), 15_000);
    ticker = window.setInterval(() => (queueVisible() ? tick() : updateTimers()), 1000);
  } else if (!on && poll) {
    clearInterval(poll);
    clearInterval(ticker);
    poll = ticker = 0;
  }
}

function showTab(tab: "pick" | "queue" | "review"): void {
  const queue = tab === "queue";
  ui.pick.hidden = tab !== "pick";
  ui.queue.hidden = !queue;
  ui.reviews.hidden = tab !== "review";
  ui.search.hidden = queue;
  ui.tabPick.setAttribute("aria-selected", String(tab === "pick"));
  ui.tabQueue.setAttribute("aria-selected", String(queue));
  ui.tabReview.setAttribute("aria-selected", String(tab === "review"));
  ui.search.placeholder = tab === "review" ? "Search conversions" : "Search PDFs without MusicXML";
  if (tab === "review") renderReviews();
  if (queue) {
    renderQueue();
    void loadPc();
  }
  updateTimers();
}
ui.qAll.addEventListener("click", () => {
  for (const n of removable) qSelected.add(n);
  renderQueue();
});
ui.qNone.addEventListener("click", () => {
  qSelected.clear();
  renderQueue();
});
ui.qRemove.addEventListener("click", () => void removeSelected());
ui.tabPick.addEventListener("click", () => showTab("pick"));
ui.tabQueue.addEventListener("click", () => showTab("queue"));
ui.tabReview.addEventListener("click", () => showTab("review"));
ui.rvFilter.addEventListener("change", renderReviews);
ui.splitFile.addEventListener("change", async () => {
  const f = ui.splitFile.files?.[0];
  ui.splitFile.value = ""; // the same file can be picked again
  if (!f) return;
  try {
    const { splitLocalFile } = await import("../split/ui");
    await splitLocalFile(f);
  } catch (err) {
    status(`Couldn't open the splitter: ${(err as Error).message}`, "error");
  }
});
document.addEventListener("visibilitychange", () => {
  updateTimers();
  if (queueVisible()) void loadPc();
});

ui.refresh.addEventListener("click", () => void load(true));
ui.go.addEventListener("click", () => void queue());
ui.retry.addEventListener("click", () => void queue(retrySel));
ui.failedAll.addEventListener("click", () => {
  for (const it of allFailed) retrySel.set(requestName(it.file), it);
  render();
});
ui.all.addEventListener("click", () => {
  for (const it of allVisible) selected.set(requestName(it.file), it);
  render();
});
ui.none.addEventListener("click", () => {
  selected.clear();
  render();
});
let typing = 0;
ui.search.addEventListener("input", () => {
  clearTimeout(typing);
  typing = window.setTimeout(render, 120);
});
onLibraryChanged(() => {
  if ($("view-convert").hidden) stale = true;
});

let stale = true;
/** Called when the screen opens: show the saved index straight away (works offline). */
export function enterConvert(): void {
  updateTimers();
  if (queueVisible() && !stale) void loadPc();
  window.setTimeout(() => void syncSplit(false), 300); // picks up flags made on another device, if signed in
  if (!stale) return;
  stale = false;
  void load(false);
}
