/**
 * The Review window: a converted score's PDF and MusicXML side by side (or one at a time on a phone), with quick
 * fixes for the clef, key, time signature and instrument, a Play button to listen to it (see review-play.ts), then
 * Approve or Reject.
 *
 * Loaded only when a review is opened, with the score renderer, so it costs nothing at startup. The PDF is shown
 * by Google Drive's own viewer, so it isn't downloaded or drawn here.
 */
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { $ } from "../core/app";
import { library, reviewedHere } from "../core/library/connection";
import { openPieceFolder } from "../core/library/library";
import type { LibraryFile, Piece } from "../core/library/model";
import { guardRenderer, skippedNote, takeSkipped } from "../core/osmd-safety";
import { timed } from "../core/perf";
import { beatAt, beatPlaces, type BeatPlace } from "../core/tap";
import { scoreText } from "../core/score";
import { isFlagged, setSplit } from "./split-list";
import { changeSplit, currentSplit, onSplitChanged } from "./split-store";
import { barPage, CLEFS, INSTRUMENTS, KEYS, measureCount, measureNumber, pageXml, serialize, setClef, setInstrument, setKey, setTime, staves, unknownParts, warnings, type Clef } from "./fixes";

export interface ReviewItem {
  piece: Piece;
  pdf: LibraryFile | null; // null for MusicXML with no PDF beside it
  xml: LibraryFile;
}

const ui = {
  dialog: $<HTMLDialogElement>("rv"),
  prev: $<HTMLButtonElement>("rv-prev"),
  next: $<HTMLButtonElement>("rv-next"),
  close: $<HTMLButtonElement>("rv-close"),
  name: $("rv-name"),
  sub: $("rv-sub"),
  found: $("rv-found"), // what the converter found or repaired, from its quality report
  panes: $("rv-panes"),
  pdf: $<HTMLIFrameElement>("rv-pdf"), // replaced by a fresh frame for each PDF: see pdfFrame()
  pdfMsg: $("rv-pdf-msg"),
  xml: $("rv-xml"),
  xmlMsg: $("rv-xml-msg"),
  bars: $("rv-bars"),
  barsLabel: $("rv-bars-label"),
  barsPrev: $<HTMLButtonElement>("rv-bars-prev"),
  barsNext: $<HTMLButtonElement>("rv-bars-next"),
  fix: $<HTMLDetailsElement>("rv-fix"),
  fixCount: $("rv-fix-count"),
  warn: $<HTMLUListElement>("rv-warn"),
  ask: $("rv-ask"),
  staff: $<HTMLSelectElement>("rv-staff"),
  from: $<HTMLInputElement>("rv-from"),
  inst: $<HTMLSelectElement>("rv-inst"),
  clef: $<HTMLSelectElement>("rv-clef"),
  move: $<HTMLInputElement>("rv-move"),
  key: $<HTMLSelectElement>("rv-key"),
  beats: $<HTMLInputElement>("rv-beats"),
  beatType: $<HTMLSelectElement>("rv-beat-type"),
  undo: $<HTMLButtonElement>("rv-undo"),
  changes: $<HTMLUListElement>("rv-changes"),
  note: $<HTMLInputElement>("rv-note"),
  edit: $<HTMLButtonElement>("rv-edit"),
  drive: $<HTMLButtonElement>("rv-drive"),
  split: $<HTMLButtonElement>("rv-split"),
  reject: $<HTMLButtonElement>("rv-reject"),
  approve: $<HTMLButtonElement>("rv-approve"),
  status: $("rv-status"),
  play: $<HTMLButtonElement>("rv-play"),
  playFrom: $<HTMLInputElement>("rv-play-from"),
  speed: $<HTMLSelectElement>("rv-speed"),
  playAt: $("rv-play-at"),
};

let items: ReviewItem[] = [];
let at = 0;
let doc: Document | null = null; // the MusicXML being reviewed, with any fixes made so far
let history: string[] = []; // the score before each fix, for Undo
let changes: string[] = [];
let discardArmed = false; // a second press of Close/Next/Previous throws unsaved fixes away
let onDone: (name: string, status: string) => void = () => {};
let osmd: OpenSheetMusicDisplay | null = null;
let shown = 0; // which score is on screen, so a slow load of an earlier one can't replace it
let page = 0; // which group of bars is drawn
let pageFirst = 0; // index of the first bar drawn
let tapPlaces: BeatPlace[] | null = null; // where the drawn notes are, found on the first tap after a draw
let drawing = 0; // bumped by each draw, so a slower earlier one can't replace a newer one

/**
 * Shows a PDF in a new frame rather than changing the old frame's address: changing it would add entries to the
 * app's history, and the Home button and the phone's Back button would then step through the PDF viewer instead.
 */
function pdfFrame(src: string | null): void {
  const frame = ui.pdf.cloneNode(false) as HTMLIFrameElement;
  frame.removeAttribute("src");
  if (src) frame.src = src;
  ui.pdf.replaceWith(frame);
  ui.pdf = frame;
}

const phone = () => window.matchMedia("(max-width: 760px)").matches;

/**
 * Bars drawn at a time. Drawing is slow and blocks the page: a 1,700-bar sonata took 92 s to draw whole on a desktop,
 * well under a second for 24 of its bars given to the renderer on their own (see pageXml).
 */
const pageBars = () => (phone() ? 12 : 24);

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function show(mode: string): void {
  ui.panes.dataset.show = mode;
  for (const b of ui.dialog.querySelectorAll<HTMLButtonElement>(".rv-switch button")) b.setAttribute("aria-pressed", String(b.dataset.show === mode));
  if (mode !== "pdf") void draw();
}

async function renderer(): Promise<OpenSheetMusicDisplay> {
  if (osmd) return osmd;
  const m = await import("opensheetmusicdisplay");
  guardRenderer(m as unknown as Record<string, unknown>);
  osmd = new m.OpenSheetMusicDisplay(ui.xml, { autoResize: false, backend: "svg", drawTitle: true, drawPartNames: true, drawingParameters: "compacttight", disableCursor: true });
  return osmd;
}

/** Draws the MusicXML (as fixed so far) into its pane: the whole score, or one page of bars of a long one. */
async function draw(): Promise<void> {
  if (!doc || ui.panes.dataset.show === "pdf") return;
  const mine = ++drawing;
  const score = shown;
  const d = doc;
  const o = await renderer();
  try {
    const count = measureCount(d);
    const p = barPage(count, pageBars(), page);
    page = p.page;
    ui.bars.hidden = p.pages === 1;
    ui.barsPrev.disabled = page === 0;
    ui.barsNext.disabled = page === p.pages - 1;
    ui.barsLabel.textContent = `Bars ${measureNumber(d, p.first)}–${measureNumber(d, p.last)} of ${measureNumber(d, count)}`;
    const drew = await timed("review-draw", async () => {
      await o.load(p.pages === 1 ? serialize(d) : pageXml(d, p.first, p.last));
      if (mine !== drawing || score !== shown) return false; // a newer page, fix or score is on its way
      o.setOptions({ drawTitle: page === 0 }); // the title only on the first page, to leave room for the bars
      o.zoom = phone() ? 0.55 : ui.panes.dataset.show === "both" ? 0.65 : 0.85;
      takeSkipped();
      o.render();
      return true;
    });
    if (!drew) return;
    pageFirst = p.pages === 1 ? 0 : p.first;
    tapPlaces = null; // drawn again: notes have moved
    ui.xml.parentElement?.scrollTo({ top: 0 });
    const left = skippedNote();
    ui.xmlMsg.hidden = !left;
    ui.xmlMsg.textContent = left ? `Drawn without some marks:${left}` : "";
  } catch (e) {
    ui.xmlMsg.hidden = false;
    ui.xmlMsg.textContent = `Couldn't draw this MusicXML: ${(e as Error).message}`;
  }
}

function fillStaffs(): void {
  if (!doc) return;
  const list = staves(doc);
  const before = ui.staff.value;
  ui.staff.replaceChildren(
    ...list.map((s) => {
      const clef = CLEFS.find((c) => c.id === s.clef)?.name ?? s.clef;
      return new Option(`${s.name}${s.staves > 1 ? ` (staff ${s.staff})` : ""}, ${clef.toLowerCase()} clef`, `${s.part}:${s.staff}`);
    }),
  );
  if (list.some((s) => `${s.part}:${s.staff}` === before)) ui.staff.value = before;
  ui.from.max = String(measureCount(doc));
  ui.warn.replaceChildren(...warnings(doc).map((w) => Object.assign(document.createElement("li"), { textContent: w })));
  ui.ask.replaceChildren(...unknownParts(doc).map((s) => askInstrument(s.part, s.name)));
  ui.changes.replaceChildren(...changes.map((c) => Object.assign(document.createElement("li"), { textContent: c })));
  ui.fixCount.textContent = changes.length ? ` (${changes.length} unsaved)` : "";
  ui.undo.disabled = !history.length;
}

/** Applies one fix to the score, keeping the previous version for Undo, and redraws. */
function fix(what: (d: Document, from: number) => string): void {
  if (!doc) return;
  const from = Math.max(1, Math.min(measureCount(doc), Math.round(Number(ui.from.value) || 1)));
  const saved = serialize(doc);
  try {
    changes.push(what(doc, from));
    history.push(saved);
    discardArmed = false;
    stopPlay();
    fillStaffs();
    status("");
    void draw();
  } catch (e) {
    doc = new DOMParser().parseFromString(saved, "application/xml");
    status((e as Error).message, "error");
  }
}

const QUICK = ["Violin", "Viola", "Cello", "Double Bass"]; // offered as buttons; the rest in a list

/** "Which instrument is Part 2?": the converter found no instrument name for this part, so it asks, not guesses. */
function askInstrument(part: string, name: string): HTMLElement {
  const box = document.createElement("div");
  box.className = "rv-q";
  const q = document.createElement("p");
  q.append("Which instrument is ", Object.assign(document.createElement("b"), { textContent: name }), "? No name was printed beside it.");
  const set = (to: string) =>
    fix((d) => {
      setInstrument(d, part, to);
      return `${name} is now ${to}`;
    });
  const buttons = QUICK.map((i) => {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: i });
    b.addEventListener("click", () => set(i));
    return b;
  });
  const other = document.createElement("select");
  other.setAttribute("aria-label", `Other instrument for ${name}`);
  other.append(new Option("Other…", ""), ...INSTRUMENTS.filter((i) => !QUICK.includes(i.name)).map((i) => new Option(i.name, i.name)));
  other.addEventListener("change", () => other.value && set(other.value));
  const row = document.createElement("div");
  row.className = "rv-q-row";
  row.append(...buttons, other);
  box.append(q, row);
  return box;
}

function staffChoice(): [string, number] {
  const [part, staff] = ui.staff.value.split(":");
  return [part, Number(staff)];
}

ui.inst.replaceChildren(...INSTRUMENTS.map((i) => new Option(i.name, i.name)));
ui.clef.replaceChildren(...CLEFS.map((c) => new Option(c.name, c.id)));
ui.key.replaceChildren(...KEYS.map((k) => new Option(k.name, String(k.fifths))));
ui.key.value = "0";

$("rv-inst-go").addEventListener("click", () =>
  fix((d) => {
    const [part] = staffChoice();
    const old = staves(d).find((s) => s.part === part)?.name ?? part;
    setInstrument(d, part, ui.inst.value);
    return `${old} is now ${ui.inst.value}`;
  }),
);
$("rv-clef-go").addEventListener("click", () =>
  fix((d, from) => {
    const [part, staff] = staffChoice();
    const name = staves(d).find((s) => s.part === part && s.staff === staff)?.name ?? part;
    const to = setClef(d, part, staff, from, ui.clef.value as Clef, ui.move.checked);
    const clef = CLEFS.find((c) => c.id === ui.clef.value)!.name.toLowerCase();
    return `${name}: ${clef} clef in measures ${measureNumber(d, from)}–${measureNumber(d, to)}${ui.move.checked ? ", notes moved with it" : ""}`;
  }),
);
$("rv-key-go").addEventListener("click", () =>
  fix((d, from) => {
    const to = setKey(d, from, Number(ui.key.value));
    return `${ui.key.selectedOptions[0].text} in measures ${measureNumber(d, from)}–${measureNumber(d, to)}`;
  }),
);
$("rv-time-go").addEventListener("click", () =>
  fix((d, from) => {
    const beats = Math.max(1, Math.min(32, Math.round(Number(ui.beats.value) || 4)));
    const to = setTime(d, from, beats, Number(ui.beatType.value));
    return `${beats}/${ui.beatType.value} time in measures ${measureNumber(d, from)}–${measureNumber(d, to)}`;
  }),
);
ui.undo.addEventListener("click", () => {
  const last = history.pop();
  if (last == null) return;
  doc = new DOMParser().parseFromString(last, "application/xml");
  changes.pop();
  stopPlay();
  fillStaffs();
  void draw();
});

/** Shows whether the score on screen is flagged for splitting (only a PDF can be split). */
function showSplit(): void {
  const it = items[at];
  const on = !!it?.pdf && isFlagged(currentSplit(), it.piece.id, it.pdf.name);
  ui.split.disabled = !it?.pdf;
  ui.split.setAttribute("aria-pressed", String(on));
  ui.split.textContent = on ? "To split ✓" : "Flag for splitting";
}

function toggleSplit(): void {
  const it = items[at];
  if (!it?.pdf) return;
  const pdf = it.pdf;
  const on = isFlagged(currentSplit(), it.piece.id, pdf.name);
  changeSplit((l) => setSplit(l, it.piece.id, pdf.name, it.piece.title, on ? "off" : "flagged"));
  status(on ? "Taken off the To split list." : "Added to the To split list (its button is in the Review tab). Split it from there, or on your PC.");
}
onSplitChanged(() => {
  if (ui.dialog.open) showSplit();
});

const stem = (name: string) => name.replace(/\.(musicxml|mxl|xml)$/i, "");
const canFix = (it: ReviewItem) => !/\.mxl$/i.test(it.xml.name); // the PC replaces the score with plain MusicXML

async function load(i: number): Promise<void> {
  at = i;
  const it = items[i];
  const mine = ++shown;
  stopPlay();
  ui.playFrom.value = "1";
  doc = null;
  history = [];
  changes = [];
  discardArmed = false;
  page = 0;
  ui.bars.hidden = true;
  ui.prev.disabled = i === 0;
  ui.next.disabled = i === items.length - 1;
  ui.name.textContent = it.piece.title;
  ui.sub.textContent = [it.piece.composer, it.xml.edition || it.xml.variant, `${i + 1} of ${items.length}`].filter(Boolean).join(" · ");
  ui.note.value = "";
  ui.found.textContent = it.xml.quality_note ? `The converter says: ${it.xml.quality_note}` : "";
  ui.found.hidden = !it.xml.quality_note;
  ui.fix.hidden = !canFix(it);
  showSplit();
  status("Loading…");
  osmd?.clear();
  fillStaffs();
  const lib = library();
  if (!lib) return status("Your library isn't connected.", "error");

  pdfFrame(null);
  ui.pdfMsg.hidden = true;
  if (!it.pdf) {
    ui.pdfMsg.hidden = false;
    ui.pdfMsg.textContent = "There's no PDF beside this score.";
  } else
    lib
      .open(it.piece, it.pdf, false)
      .then(({ link }) => {
        if (mine !== shown) return;
        if (!link) throw new Error("no link");
        pdfFrame(link.replace(/\/view(\?.*)?$/, "/preview"));
      })
      .catch(() => {
        if (mine !== shown) return;
        ui.pdfMsg.hidden = false;
        ui.pdfMsg.textContent = "Couldn't show the PDF (offline?).";
      });

  try {
    const { data } = await lib.open(it.piece, it.xml);
    if (mine !== shown) return;
    if (!data) throw new Error("the file couldn't be downloaded");
    doc = new DOMParser().parseFromString(scoreText(it.xml.name, data), "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("it isn't valid MusicXML");
    fillStaffs();
    const review = reviewedHere.all()[it.xml.name] ?? it.xml.review;
    status(review ? `You ${review} this before.` : "");
    await draw();
  } catch (e) {
    if (mine !== shown) return;
    ui.xmlMsg.hidden = false;
    ui.xmlMsg.textContent = `Couldn't load the MusicXML: ${(e as Error).message}`;
    status("");
  }
}

// ---- Listening: the player and its sounds load the first time Play is pressed ----
type Playback = typeof import("./review-play");
let playback: Playback | null = null;
let playTimer: number | null = null;

function setPlaying(on: boolean): void {
  ui.play.textContent = on ? "■ Stop" : "▶ Play";
  ui.play.setAttribute("aria-pressed", String(on));
  if (playTimer !== null) window.clearInterval(playTimer);
  playTimer = null;
  ui.playAt.textContent = "";
  if (on)
    playTimer = window.setInterval(() => {
      const m = playback?.nowMeasure();
      ui.playAt.textContent = m ? `m. ${m}` : "";
    }, 250);
}

function stopPlay(): void {
  playback?.stop();
  setPlaying(false);
}

/** Plays the score as fixed so far, from the chosen measure, or stops it. A tapped note plays from that note. */
async function togglePlay(tapped?: { pageFirst: number; beat: number }): Promise<void> {
  if (playback?.isPlaying() && !tapped) return stopPlay();
  if (!doc) return;
  const mine = shown;
  const xml = serialize(doc);
  ui.play.disabled = true;
  try {
    playback ??= await import("./review-play");
    if (mine !== shown) return;
    const measures = await playback.play(xml, Number(ui.playFrom.value) || 1, Number(ui.speed.value) / 100, () => setPlaying(false), tapped);
    if (mine !== shown) return playback.stop();
    ui.playFrom.max = String(measures);
    setPlaying(true);
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.play.disabled = false;
  }
}

/** Unsaved fixes are only thrown away on a second press. Returns whether it's fine to leave this score. */
function mayLeave(): boolean {
  if (!changes.length || discardArmed) return true;
  discardArmed = true;
  status(`You have ${changes.length} unsaved fix${changes.length > 1 ? "es" : ""}. Approve to save them, or press again to discard.`, "error");
  return false;
}

async function decide(verdict: "approved" | "rejected"): Promise<void> {
  const it = items[at];
  const lib = library();
  if (!lib || !doc) return;
  ui.approve.disabled = ui.reject.disabled = true;
  status(verdict === "approved" ? "Saving…" : "Saving the rejection…");
  try {
    const fixes = verdict === "approved" ? changes : [];
    if (fixes.length) await lib.writeFixedScore(it.piece.id, it.xml.name, serialize(doc));
    const record: Record<string, unknown> = { status: verdict, at: new Date().toISOString() };
    if (ui.note.value.trim()) record.note = ui.note.value.trim();
    if (fixes.length) record.fixes = fixes;
    if (it.xml.quality) record.quality = it.xml.quality;
    await lib.writeSidecar(it.piece.id, `${stem(it.xml.name)}.review.json`, record);
    const mine = reviewedHere.all();
    mine[it.xml.name] = verdict;
    reviewedHere.save(mine);
    onDone(it.xml.name, verdict);
    changes = [];
    history = [];
    const saved = verdict === "approved" ? (fixes.length ? `Approved with ${fixes.length} fix${fixes.length > 1 ? "es" : ""}; your PC puts them into the MusicXML.` : "Approved.") : "Rejected.";
    if (at < items.length - 1) {
      await load(at + 1);
      status(`${saved} Here's the next one.`);
    } else {
      fillStaffs();
      status(`${saved} That was the last one.`);
    }
  } catch (e) {
    status((e as Error).message, "error");
  } finally {
    ui.approve.disabled = ui.reject.disabled = false;
  }
}

/** Hands the MusicXML (with any fixes) to the device: the share sheet on a phone, a download on a computer. */
async function edit(): Promise<void> {
  const it = items[at];
  if (!doc) return;
  const file = new File([serialize(doc)], it.xml.name.replace(/\.mxl$/i, ".musicxml"), { type: "application/vnd.recordare.musicxml+xml" });
  const mobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
  try {
    if (mobile && navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], title: it.piece.title });
      status("Sent to the app you picked.");
      return;
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
  }
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(file), download: file.name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  status(`Downloaded ${file.name}: open it from your downloads. To keep your edits, save it as MusicXML over pieces/${it.piece.id}/${it.xml.name} in the library folder.`);
}

ui.prev.addEventListener("click", () => mayLeave() && void load(at - 1));
ui.next.addEventListener("click", () => mayLeave() && void load(at + 1));
ui.close.addEventListener("click", () => mayLeave() && ui.dialog.close());
ui.dialog.addEventListener("cancel", (e) => {
  if (!mayLeave()) e.preventDefault();
});
ui.dialog.addEventListener("close", () => {
  stopPlay();
  pdfFrame(null);
  osmd?.clear();
  doc = null;
  shown++;
});
ui.barsPrev.addEventListener("click", () => {
  page = Math.max(0, page - 1);
  void draw();
});
ui.barsNext.addEventListener("click", () => {
  page++;
  void draw();
});
for (const b of ui.dialog.querySelectorAll<HTMLButtonElement>(".rv-switch button")) b.addEventListener("click", () => show(b.dataset.show ?? "both"));
ui.approve.addEventListener("click", () => void decide("approved"));
ui.reject.addEventListener("click", () => void decide("rejected"));
ui.edit.addEventListener("click", () => void edit());
ui.drive.addEventListener("click", () => void openDrive());
ui.split.addEventListener("click", toggleSplit);
ui.play.addEventListener("click", () => void togglePlay());

// Tap a note in the drawn MusicXML to listen from there (tapping again while it plays jumps)
ui.xml.addEventListener("click", (e) => {
  if (!osmd || !doc || drawing === 0) return;
  tapPlaces ??= beatPlaces(osmd, ui.xml);
  const c = ui.xml.getBoundingClientRect();
  const beat = beatAt(tapPlaces, e.clientX - c.left + ui.xml.scrollLeft, e.clientY - c.top + ui.xml.scrollTop);
  if (beat === null) return;
  void togglePlay({ pageFirst, beat });
});

/** Opens this piece's folder in Google Drive, where its PDF and MusicXML can be changed. */
async function openDrive(): Promise<void> {
  const it = items[at];
  const lib = library();
  if (!it || !lib) return status("Your library isn't connected.", "error");
  if (await openPieceFolder(lib, it.piece.id)) status(`Opened the folder for ${it.piece.title} in Google Drive.`);
  else status("Couldn't find this piece's folder in Drive (offline?).", "error");
}

/** Opens the window on items[start]; Previous and Next go through the rest. */
export function openReview(list: ReviewItem[], start: number, done: (name: string, status: string) => void): void {
  items = list;
  onDone = done;
  ui.dialog.showModal();
  show("both");
  void load(start);
}
