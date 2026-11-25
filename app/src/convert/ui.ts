/**
 * The Convert PDF screen: pick PDFs in the library that have no MusicXML yet and queue them for your PC.
 * The conversion itself (homr, which needs the PC's graphics card) runs there with `lento-library convert`;
 * this screen writes the small request files it picks up and shows what is waiting and what is done.
 */
import { $ } from "../core/app";
import { library, libraryChanged, onLibraryChanged, requestedHere } from "../core/library/connection";
import type { LibraryFile, LibraryIndex, Piece } from "../core/library/model";
import { fold, musicxmlOf, pcOnline, requestName, type PcStatus } from "../core/library/model";

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
  waiting: $<HTMLUListElement>("cv-waiting"),
  waitingBox: $<HTMLDetailsElement>("cv-waiting-box"),
  review: $<HTMLUListElement>("cv-review"),
  reviewBox: $<HTMLDetailsElement>("cv-review-box"),
};

type Item = { piece: Piece; file: LibraryFile };
let index: LibraryIndex | null = null;
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
      } else if (file.requested || mine.has(requestName(file))) waiting.push({ piece, file });
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
  ui.waitingBox.hidden = !waiting.length;
  ui.waiting.replaceChildren(...waiting.map((it) => li(...label(it))));
  ui.reviewBox.hidden = !review.length;
  ui.review.replaceChildren(
    ...review.map((it) => li(label(it)[0], it.file.quality === "REVIEW" ? "some measures may be wrong" : "probably wrong in many places")),
  );
  for (const [k, it] of selected) if (!todo.includes(it)) selected.delete(k);
  updateGo();
  allVisible = shown;
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
  else if (s.state === "converting") line(`${s.pc || "Your PC"} is converting ${s.current}${s.queue.length ? `, ${s.queue.length} more after that` : ""}.`);
  else if (s.state === "exporting") line(`${s.pc || "Your PC"} is exporting ${s.current} from MuseScore.`);
  else line(`${s.pc || "Your PC"} is on and watching (checked ${ago(s.heartbeat)}). New requests start within ${Math.round(s.interval_s || 30)} s.`);
  if (s.musescore === false) line("There are MuseScore files in the library, but MuseScore isn't installed on the PC. Install MuseScore 4 there and they'll be exported.", "hint");
  const recent = [...s.results].reverse().slice(0, 5);
  if (recent.length) line("Recent: " + recent.map((r) => `${r.pdf.replace(/\.(pdf|mscz|mscx)$/, "")} ${r.ok ? "✓" : "failed"}`).join(" · "), "hint");
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
    for (const it of items) mine.add(requestName(it.file));
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
  if (!stale) return;
  stale = false;
  void load(false);
}
