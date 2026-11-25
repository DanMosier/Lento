/**
 * The Convert PDF screen: pick PDFs in the library that have no MusicXML yet and queue them for your PC.
 * The conversion itself (homr, which needs the PC's graphics card) runs there with `lento-library convert`;
 * this screen writes the small request files it picks up and shows what is waiting and what is done.
 */
import { $ } from "../core/app";
import { library, libraryChanged, onLibraryChanged, requestedHere } from "../core/library/connection";
import type { LibraryFile, LibraryIndex, Piece } from "../core/library/model";
import { fold, musicxmlOf, pcOnline, requestName, requestNameOf, type PcStatus } from "../core/library/model";
import { buildQueue, duration, item, namesOf, type Names, type QueueItem } from "./queue";

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
  review: $<HTMLUListElement>("cv-review"),
  reviewBox: $<HTMLDetailsElement>("cv-review-box"),
};

type Item = { piece: Piece; file: LibraryFile };
let index: LibraryIndex | null = null;
let names: Names = new Map();
let pc: PcStatus | null = null; // the watcher's last status
const removedHere = new Set<string>(); // PDF names taken off the queue on this device (until the index says so too)
const qSelected = new Set<string>(); // PDF names ticked in the Queue tab
let removable: string[] = []; // the PDF names that have a checkbox right now
const selected = new Map<string, Item>(); // by request file name

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

function render(): void {
  if (!index) return;
  const mine = requestedHere.all();
  const todo: Item[] = [];
  const waiting: Item[] = [];
  const review: Item[] = [];
  let done = 0;
  for (const piece of index.pieces)
    for (const file of piece.files) {
      if (file.kind !== "pdf") continue;
      const xml = musicxmlOf(file);
      if (xml) {
        done++;
        if (xml.quality === "REVIEW" || xml.quality === "UNRELIABLE") review.push({ piece, file: xml });
      } else if ((file.requested || mine.has(requestName(file))) && !removedHere.has(file.name)) waiting.push({ piece, file });
      else todo.push({ piece, file }); // includes ones whose last conversion failed, so they can be queued again
    }
  ui.counts.textContent = `${todo.length} PDFs without MusicXML · ${waiting.length} waiting for your PC · ${done} converted`;

  const q = fold(ui.search.value.trim());
  const shown = q ? todo.filter((it) => fold(`${it.piece.title} ${it.piece.composer}`).includes(q)) : todo;
  ui.todo.replaceChildren(
    ...shown.slice(0, SHOWN).map((it) => {
      const [t, sub] = label(it);
      const row = li(t, it.file.convert_failed ? `${sub ? `${sub} · ` : ""}last try failed on your PC` : sub);
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selected.has(requestName(it.file));
      box.setAttribute("aria-label", `Convert ${t}`);
      box.addEventListener("change", () => {
        if (box.checked) selected.set(requestName(it.file), it);
        else selected.delete(requestName(it.file));
        updateGo();
      });
      const lab = document.createElement("label");
      lab.className = "cv-row";
      lab.append(box, ...Array.from(row.childNodes));
      row.replaceChildren(lab);
      return row;
    }),
  );
  if (shown.length > SHOWN) ui.todo.append(li(`…and ${shown.length - SHOWN} more. Search to narrow the list.`));
  if (!todo.length) ui.todo.append(li("Every PDF in the library has MusicXML."));
  ui.tabQueue.textContent = waiting.length ? `Queue (${waiting.length})` : "Queue";
  ui.reviewBox.hidden = !review.length;
  ui.review.replaceChildren(
    ...review.map((it) => li(label(it)[0], it.file.quality === "REVIEW" ? "some measures may be wrong" : "probably wrong in many places")),
  );
  // rows are rebuilt on every render, so match the selection by file name, not by object
  const open = new Map(todo.map((it) => [requestName(it.file), it] as const));
  for (const k of [...selected.keys()]) {
    const it = open.get(k);
    if (it) selected.set(k, it);
    else selected.delete(k);
  }
  updateGo();
  allVisible = shown.slice(0, SHOWN); // "Select all shown" means the rows on screen, not every match
}

let allVisible: Item[] = [];

function updateGo(): void {
  ui.go.textContent = selected.size ? `Queue ${selected.size} for my PC` : "Queue for my PC";
  ui.go.disabled = selected.size === 0;
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

async function queue(): Promise<void> {
  const lib = library();
  if (!lib || !selected.size) return;
  const items = [...selected.values()];
  ui.go.disabled = true;
  status(`Queueing ${items.length} PDF${items.length > 1 ? "s" : ""}…`);
  try {
    await lib.requestConversion(items);
    const mine = requestedHere.all();
    for (const it of items) {
      mine.add(requestName(it.file));
      removedHere.delete(it.file.name); // queued again after being removed
    }
    requestedHere.save(mine);
    selected.clear();
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

function showTab(queue: boolean): void {
  ui.pick.hidden = queue;
  ui.queue.hidden = !queue;
  ui.search.hidden = queue;
  ui.tabPick.setAttribute("aria-selected", String(!queue));
  ui.tabQueue.setAttribute("aria-selected", String(queue));
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
ui.tabPick.addEventListener("click", () => showTab(false));
ui.tabQueue.addEventListener("click", () => showTab(true));
document.addEventListener("visibilitychange", () => {
  updateTimers();
  if (queueVisible()) void loadPc();
});

ui.refresh.addEventListener("click", () => void load(true));
ui.go.addEventListener("click", () => void queue());
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
  if (!stale) return;
  stale = false;
  void load(false);
}
