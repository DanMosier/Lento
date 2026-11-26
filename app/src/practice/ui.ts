/** The Practice tab: slowed playback, loops, metronome, recording and note-by-note feedback. */
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { $, sharedAudio, store, takeOpenScore } from "../core/app";
import { timed } from "../core/perf";
import { LiveMic, type MicFrame } from "../core/live-pitch";
import { defaultPart, listParts, midiName, parseScore, partXml, quickPartList, scoreText, type Score } from "../core/score";
import { customPitch, customTiming } from "../core/tolerance";
import { choiceLabel, cleanChoice, pickParts, type PartChoice } from "./parts";
import { analyze, DEFAULT_SETTINGS, PITCH_WINDOWS, TIMING_WINDOWS, type Analysis, type NoteResult, type Strictness } from "./analyze";
import { type PitchTrack } from "./pitch";
import { trackPitchAsync } from "./pitch-async";
import { roomOut } from "../core/room";
import { SoundBank } from "../core/sounds";
import { partInstrument, Player } from "../core/player";
import { reportedDelay, TapTest } from "./latency";
import { decodeFile, encodeWav, Recorder, toAnalysisRate } from "./recorder";
import { coloredScore, describe, LABELS, problemSpots, summarize, type Spot } from "./report";
import { celloWhere, stepName, WaitJudge, waitSteps } from "./wait";
import { clearNote, emptyMarks, marksIn, newer, parseMarks, toggleMark, type MarkKind, type MarkSet } from "./marks";
import { drawMarks, nearestNote, notePlaces, type NotePlace } from "./marks-view";
import { library } from "../core/library/connection";
import { DEFAULT_TRAINER, judgePass, SpeedTrainer, type TrainerConfig } from "./trainer";
import { pageLayout, parseScoreSize, phoneScreen, SCORE_SIZES } from "./layout";
import { setUpFocus } from "./focus";
import { guardRenderer, takeSkippedSlurs } from "./osmd-safety";
import { applyView, CLEF_LABELS, cleanView, isPlain, MAX_TRANSPOSE, PLAIN_VIEW, transposeLabel, type ClefChoice, type ScoreView } from "./view";

const ui = {
  scoreFile: $<HTMLInputElement>("score-file"),
  partsBtn: $<HTMLButtonElement>("parts-btn"),
  marksBtn: $<HTMLButtonElement>("marks-btn"),
  title: $("title"),
  controls: $("controls"),
  tempo: $<HTMLInputElement>("tempo"),
  tempoOut: $<HTMLOutputElement>("tempo-out"),
  from: $<HTMLSelectElement>("from"),
  to: $<HTMLSelectElement>("to"),
  loop: $<HTMLInputElement>("loop"),
  countIn: $<HTMLInputElement>("count-in"),
  click: $<HTMLSelectElement>("click"),
  accomp: $<HTMLInputElement>("accomp"),
  accompLabel: $("accomp-label"),
  play: $<HTMLButtonElement>("play"),
  record: $<HTMLButtonElement>("record"),
  wait: $<HTMLButtonElement>("wait"),
  audioFile: $<HTMLInputElement>("audio-file"),
  a4: $<HTMLInputElement>("a4"),
  pitchStrict: $<HTMLSelectElement>("pitch-strict"),
  timingStrict: $<HTMLSelectElement>("timing-strict"),
  transpose: $<HTMLSelectElement>("transpose"),
  clef: $<HTMLSelectElement>("clef"),
  playWhileRecording: $<HTMLInputElement>("play-while-recording"),
  delay: $<HTMLInputElement>("av-delay"),
  delayOut: $<HTMLOutputElement>("av-delay-out"),
  status: $("status"),
  welcome: $("welcome"),
  feedback: $("feedback"),
  sheet: $("sheet"),
  view: $("view-practice"),
  focusBtn: $<HTMLButtonElement>("focus-btn"),
  scoreSize: $<HTMLSelectElement>("score-size"),
  fitBtn: $<HTMLButtonElement>("fit-btn"),
  miniFit: $<HTMLButtonElement>("mini-fit"),
  loading: $("loading"),
  loadingText: $("loading-text"),
};

let xml = "";
let plainXml = ""; // the chosen parts only, as drawn
let fullDoc: Document | null = null; // the whole file, parsed once and reused when parts change
let choice: PartChoice | null = null;
let accompParts: Score[] | null = null; // the other shown parts, parsed the first time they are played
let fileName = "";
let pieceId: string | null = null; // the library piece the score came from, if any
let view: ScoreView = PLAIN_VIEW; // transposition and clef, saved per score
let score: Score | null = null;
let ctx: AudioContext | null = null;
let player: Player | null = null;
let sounds: SoundBank | null = null;
let recorder: Recorder | null = null;
let take: Float32Array | null = null; // last recording, at the analysis rate
let track: { take: Float32Array; a4: number; pitch: PitchTrack } | null = null; // its pitch, kept so re-checks are instant
let analysis: Analysis | null = null;
let showingColors = false;
// The score renderer is most of the app's code, so it loads only when needed (or once the app is idle).
let osmd: OpenSheetMusicDisplay | null = null;
let osmdLoading: Promise<OpenSheetMusicDisplay> | null = null;
function sheetRenderer(): Promise<OpenSheetMusicDisplay> {
  osmdLoading ??= import("opensheetmusicdisplay").then((m) => {
    guardRenderer(m as unknown as Record<string, unknown>);
    return (osmd = new m.OpenSheetMusicDisplay(ui.sheet, { autoResize: false, backend: "svg", drawTitle: true, drawPartNames: true, followCursor: true }));
  });
  return osmdLoading;
}

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function audio(): AudioContext {
  if (!ctx) {
    ctx = sharedAudio();
    sounds = new SoundBank(ctx);
    player = new Player(ctx, roomOut(ctx), sounds);
    player.onEnd = () => stopPlayback();
    recorder = new Recorder(ctx);
  }
  return ctx;
}

function writtenTempo(): number {
  if (!score) return 90;
  const start = score.measureStarts[+ui.from.value] ?? 0;
  return [...score.tempos].reverse().find((t) => t[0] <= start)?.[1] ?? score.tempos[0][1];
}

function updateTempoLabel(): void {
  const pct = +ui.tempo.value;
  ui.tempoOut.textContent = `${pct}% · ${Math.round((writtenTempo() * pct) / 100)} bpm`;
  store.set("tempo", pct);
}

/** The pitch and timing windows chosen: a preset, or "Custom" for the ones set in Settings. */
function windows(): { goodCents: number; okCents: number; timingMs: number } {
  const p = ui.pitchStrict.value === "custom" ? customPitch() : null;
  const [good, ok] = p ? [p.good, p.ok] : (PITCH_WINDOWS[ui.pitchStrict.value as Strictness] ?? PITCH_WINDOWS.standard);
  const timingMs = ui.timingStrict.value === "custom" ? customTiming() : (TIMING_WINDOWS[ui.timingStrict.value as Strictness] ?? TIMING_WINDOWS.standard);
  return { goodCents: good, okCents: ok, timingMs };
}

/** Shows the custom windows' current values in the Pitch and Timing menus. */
function labelCustom(): void {
  const p = customPitch();
  ui.pitchStrict.querySelector<HTMLOptionElement>('option[value="custom"]')!.textContent = `Custom (±${p.good} cents)`;
  ui.timingStrict.querySelector<HTMLOptionElement>('option[value="custom"]')!.textContent = `Custom (±${customTiming()} ms)`;
}

function settings() {
  return {
    ...DEFAULT_SETTINGS,
    a4: +ui.a4.value || 440,
    ...windows(),
    measures: [score!.measures[+ui.from.value], score!.measures[+ui.to.value]] as [string, string],
    strict: false,
  };
}

// ---- fitting the score to the screen ----

let drawnWidth = 0; // the score area's width when the score was last laid out
let rendering = false; // a score is being loaded and drawn; it measures the width itself
let layoutMs = 0; // how long the last layout took on this device

/** Sizes the page for the score area's width (smaller notes and margins on a phone) before a layout. */
function fitPage(sheet: OpenSheetMusicDisplay): void {
  drawnWidth = ui.sheet.clientWidth;
  const l = pageLayout(drawnWidth, parseScoreSize(ui.scoreSize.value), choice?.shown.length ?? 1, phoneScreen());
  sheet.Zoom = l.zoom;
  sheet.EngravingRules.PageLeftMargin = sheet.EngravingRules.PageRightMargin = l.margin;
  sheet.EngravingRules.RenderPartNames = l.partNames;
}

/** Runs one layout of the score and remembers how long it took. */
function layOut(sheet: OpenSheetMusicDisplay, name: string): void {
  const t = performance.now();
  timed(name, () => sheet.render());
  layoutMs = performance.now() - t;
  showFitOffer();
}

/**
 * Drawing a score holds the page (seconds for a long one, longer on a phone), so a loading panel covers the screen
 * first: buttons that don't answer then look busy, not broken. Its spinner is a CSS animation, which keeps turning
 * while the page is held.
 */
async function withLoading<T>(text: string, fn: () => Promise<T> | T): Promise<T> {
  ui.loadingText.textContent = text;
  ui.loading.hidden = false;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); // let the panel show first
  try {
    return await fn();
  } finally {
    ui.loading.hidden = true;
  }
}

async function render(text: string, label = "Loading score…"): Promise<void> {
  return withLoading(label, () => renderNow(text));
}

async function renderNow(text: string): Promise<void> {
  ui.sheet.hidden = false; // OSMD measures the container, so it must be visible first
  rendering = true;
  try {
    const sheet = await sheetRenderer();
    await timed("render-score", async () => {
      await timed("load-sheet", () => sheet.load(text));
      fitPage(sheet);
      layOut(sheet, "draw-sheet");
    });
  } finally {
    rendering = false;
  }
  drawScoreMarks();
}

/** Lays the loaded score out again (after the width or the size setting changed), keeping the scroll position. */
function relayout(): void {
  if (rendering || !osmd || !score || ui.sheet.hidden || ui.sheet.clientWidth <= 0 || !osmd.IsReadyToRender()) return;
  const at = window.scrollY / Math.max(1, document.body.scrollHeight);
  fitPage(osmd);
  layOut(osmd, "relayout-score");
  window.scrollTo({ top: document.body.scrollHeight * at, behavior: "instant" });
  drawScoreMarks();
}

/** Is the user playing, recording, in wait mode or training? A new layout then waits until they stop. */
const busy = (): boolean => !!player?.playing || !!recorder?.recording || waiting() || training();
const widthChanged = (): boolean =>
  !!score && !ui.sheet.hidden && ui.sheet.clientWidth > 0 && Math.abs(ui.sheet.clientWidth - drawnWidth) >= 2;

/**
 * Laying out a long score again holds the page for seconds on a phone (every tap waits), so it is never done
 * behind the user's back. A score that lays out quickly is refitted by itself once the width has settled (turning
 * the phone or full screen can resize the page several times) and the user isn't playing, recording, waiting or
 * training. A slower one keeps its layout (centred, or scrolling sideways) and a "Fit to screen" button appears, so
 * the pause comes only when the user asks for it.
 */
const AUTO_FIT_MS = 600;
let fitTimer = 0;
function scheduleFit(delay = 700): void {
  clearTimeout(fitTimer);
  showFitOffer();
  if (!widthChanged() || document.hidden || layoutMs > AUTO_FIT_MS) return;
  fitTimer = window.setTimeout(() => {
    if (!widthChanged() || document.hidden) return;
    if (busy() || rendering) return scheduleFit(1000);
    void refit();
  }, delay);
}

function showFitOffer(): void {
  const offer = widthChanged() && layoutMs > AUTO_FIT_MS;
  ui.fitBtn.hidden = ui.miniFit.hidden = !offer;
}

async function refit(): Promise<void> {
  const before = ui.status.textContent ?? "";
  const kind = (ui.status.dataset.kind as "info" | "error") ?? "info";
  const secs = Math.round(layoutMs / 1000);
  await withLoading(secs >= 2 ? `Fitting the score to the screen (about ${secs} seconds)…` : "Fitting the score to the screen…", () => {
    if (widthChanged() && !document.hidden) relayout();
  });
  status(before, kind);
  showFitOffer();
}

for (const b of [ui.fitBtn, ui.miniFit])
  b.addEventListener("click", () => {
    if (busy()) return status("Stop first, then fit the score to the screen.");
    void refit();
  });

// Only a change of width needs a new layout. (The renderer's own auto-resize redrew the whole score on every
// resize, including the phone's address bar sliding in and out while scrolling.)
new ResizeObserver(() => scheduleFit()).observe(ui.sheet);
document.addEventListener("visibilitychange", () => scheduleFit());

ui.scoreSize.replaceChildren(...SCORE_SIZES.map((v) => new Option(v === "auto" ? "Fit the screen" : `${v}%`, String(v))));
ui.scoreSize.value = String(parseScoreSize(store.get<string>("scoreSize")));
ui.scoreSize.addEventListener("change", () => {
  store.set("scoreSize", ui.scoreSize.value);
  relayout();
});

const scoreFocus = setUpFocus({
  view: ui.view,
  play: ui.play,
  record: ui.record,
  info: () => (score ? `${ui.tempo.value}% · m. ${score.measures[+ui.from.value]}–${score.measures[+ui.to.value]}` : ""),
});
for (const el of [ui.tempo, ui.from, ui.to]) el.addEventListener("change", scoreFocus.refresh);

async function openScore(name: string, text: string, picked?: PartChoice): Promise<void> {
  return timed("open-score", () => openScoreNow(name, text, picked));
}

/**
 * Starts downloading the recorded sounds for the parts that can play (cached after the first time). Playback
 * doesn't wait for them: it uses the synth until each one is ready.
 */
function loadSounds(): void {
  if (!score || !choice || !fullDoc) return;
  const insts = [partInstrument(score), ...choice.shown.filter((id) => id !== choice!.practise).map((id) => {
    const p = score!.parts.find((x) => x.id === id)!;
    return partInstrument({ ...score!, partId: id, partName: p.name });
  })];
  audio();
  setTimeout(() => void sounds?.want(insts), 0);
}

/** Opens a file the user just picked: for a score with several parts, asks which parts first. */
async function openFile(name: string, text: string, from: string | null = null): Promise<void> {
  const parts = quickPartList(text);
  let picked: PartChoice | undefined;
  if (parts.length > 1) {
    const first = defaultPart(parts).id;
    const saved = store.get<PartChoice>(`parts:${name}`);
    const c = await pickParts(parts, (saved && cleanChoice(parts, saved)) ?? { practise: first, shown: [first] });
    if (!c) {
      status(score ? "Kept the score you had open." : "Open a score to start.");
      return;
    }
    picked = c;
  }
  pieceId = from;
  await openScore(name, text, picked);
}

/**
 * Reads the practised part of `doc` as the score is to be shown. With the score as written that's the file
 * itself; transposed or in another clef, it's a changed copy of just the shown parts, so playback, wait mode and
 * the check of a recording all use the same pitches the sheet shows.
 */
function readScore(doc: Document, v: ScoreView, title: string, picked?: PartChoice): Score & { full: Document } {
  const parts = doc.documentElement?.localName === "score-partwise" && !doc.getElementsByTagName("parsererror").length ? listParts(doc) : [];
  if (isPlain(v) || !parts.length) return Object.assign(parseScore(doc, picked?.practise, title), { full: doc }); // explains a bad file
  const first = defaultPart(parts).id;
  const c = (picked && cleanChoice(parts, picked)) ?? { practise: first, shown: [first] };
  const copy = new DOMParser().parseFromString(partXml(doc, c.shown), "application/xml");
  applyView(copy, v, c.shown, c.practise);
  const s = parseScore(copy, c.practise, title);
  s.parts = parts; // the part picker still offers every part
  return Object.assign(s, { full: doc });
}

async function openScoreNow(name: string, text: string, picked?: PartChoice): Promise<void> {
  const title = name.replace(/\.[^.]+$/, "");
  const reuse = text === xml && fullDoc !== null;
  const keep = reuse && score ? [+ui.from.value, +ui.to.value] : null; // same score again: keep the chosen measures
  const v = cleanView(store.get<ScoreView>(`view:${name}`));
  const s = await timed("parse-score", () => readScore(reuse ? fullDoc! : new DOMParser().parseFromString(text, "application/xml"), v, title, picked));
  fullDoc = s.full;
  view = v;
  showView();
  choice = (picked && cleanChoice(s.parts, picked)) ?? { practise: s.partId, shown: [s.partId] };
  accompParts = null;
  xml = text;
  fileName = name;
  score = s;
  analysis = null;
  take = null;
  showingColors = false;
  ui.feedback.hidden = true;
  ui.welcome.hidden = true;
  ui.controls.hidden = false;
  ui.focusBtn.hidden = false;
  ui.title.textContent = s.title;
  ui.partsBtn.hidden = s.parts.length < 2;
  ui.marksBtn.hidden = false;
  ui.partsBtn.textContent = choiceLabel(s.parts, choice);
  ui.accompLabel.hidden = choice.shown.length < 2;
  const opts = () => s.measures.map((m, i) => new Option(m, String(i)));
  ui.from.replaceChildren(...opts());
  ui.to.replaceChildren(...opts());
  ui.to.value = String(s.measures.length - 1);
  if (keep && keep[1] < s.measures.length) [ui.from.value, ui.to.value] = keep.map(String);
  updateTempoLabel();
  plainXml = partXml(s.doc, choice.shown); // only the chosen parts are drawn
  await render(plainXml, `Loading ${s.title}…`);
  loadSounds();
  showBest();
  void loadMarks();
  const shown = isPlain(v) ? "" : ` Shown ${[v.transpose ? transposeLabel(v.transpose).toLowerCase() : "", v.clef !== "written" ? `in ${CLEF_LABELS[v.clef].toLowerCase()} clef` : ""].filter(Boolean).join(", ")}.`;
  const slurs = takeSkippedSlurs();
  const skippedNote = slurs ? ` ${slurs} slur${slurs > 1 ? "s" : ""} that couldn't be placed ${slurs > 1 ? "were" : "was"} left out.` : "";
  status(s.notes.length ? `${s.partName}: ${s.notes.length} notes in ${s.measures.length} measures.${shown}${skippedNote}` : "This part has no notes.");
  if (s.parts.length > 1) store.set(`parts:${name}`, choice);
}

ui.scoreFile.addEventListener("change", async () => {
  const f = ui.scoreFile.files?.[0];
  if (!f) return;
  if (waiting()) stopWait();
  if (training()) stopTrainer();
  try {
    status(`Opening ${f.name}…`);
    await openFile(f.name, scoreText(f.name, await f.arrayBuffer()));
  } catch (e) {
    status(`Could not open ${f.name}: ${(e as Error).message}`, "error");
  }
  ui.scoreFile.value = "";
});

takeOpenScore(async ({ name, data, pieceId: from }) => {
  if (training()) stopTrainer();
  if (player?.playing) stopPlayback();
  if (waiting()) stopWait();
  try {
    status(`Opening ${name}…`);
    await openFile(name, scoreText(name, data), from ?? null);
  } catch (e) {
    status(`Could not open ${name}: ${(e as Error).message}`, "error");
  }
});

ui.partsBtn.addEventListener("click", async () => {
  if (!score || !choice) return;
  if (training()) stopTrainer();
  if (player?.playing) stopPlayback();
  if (waiting()) stopWait();
  const c = await pickParts(score.parts, choice);
  if (c) await openScore(fileName, xml, c).catch((e) => status((e as Error).message, "error"));
});
ui.tempo.addEventListener("input", updateTempoLabel);
ui.from.addEventListener("change", () => {
  if (+ui.to.value < +ui.from.value) ui.to.value = ui.from.value;
  updateTempoLabel();
});
ui.to.addEventListener("change", () => {
  if (+ui.to.value < +ui.from.value) ui.from.value = ui.to.value;
});

// ---- playback and the moving cursor ----

let frame = 0;
let lastBeat = -1;

function moveCursorTo(beat: number): void {
  if (!osmd) return;
  const c = osmd.cursor;
  if (beat < lastBeat - 0.01) c.reset();
  lastBeat = beat;
  for (let guard = 0; guard < 10000; guard++) {
    const it = c.Iterator.clone();
    it.moveToNext();
    if (it.EndReached || it.currentTimeStamp.RealValue * 4 > beat + 1e-3) break;
    c.next();
  }
}

function follow(): void {
  const beat = player?.currentBeat(+ui.delay.value / 1000);
  if (beat !== null && beat !== undefined) moveCursorTo(beat);
  frame = requestAnimationFrame(follow);
}

/** The other shown parts, when "Play other shown parts" is ticked (parsed the first time). */
function accompaniment(): Score[] {
  if (!ui.accomp.checked || !choice || !fullDoc) return [];
  const doc = score?.doc ?? fullDoc; // transposed with the practised part when the view is
  accompParts ??= choice.shown.filter((id) => id !== choice!.practise).map((id) => parseScore(doc!, id));
  return accompParts;
}

async function startPlayback(mute = false): Promise<void> {
  return timed("start-playback", () => startPlaybackNow(mute));
}

async function startPlaybackNow(mute = false): Promise<void> {
  if (!score) return;
  audio();
  roomOut(ctx!); // picks up the Room sound setting
  const parts = [score, ...accompaniment()];
  await player!.play({
    parts,
    fromMeasure: +ui.from.value,
    toMeasure: +ui.to.value,
    tempoFactor: +ui.tempo.value / 100,
    countIn: ui.countIn.checked,
    loop: ui.loop.checked && !recorder!.recording,
    click: +ui.click.value,
    mute,
  });
  osmd?.cursor.show();
  osmd?.cursor.reset();
  lastBeat = -1;
  moveCursorTo(score.measureStarts[+ui.from.value] ?? 0);
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(follow);
  ui.play.textContent = "Stop";
}

function stopPlayback(): void {
  player?.stop();
  cancelAnimationFrame(frame);
  osmd?.cursor.hide();
  ui.play.textContent = "Play";
  if (recorder?.recording) void finishRecording();
}

ui.play.addEventListener("click", () => {
  if (player?.playing) stopPlayback();
  else startPlayback().catch((e) => status((e as Error).message, "error"));
});

// ---- headphone delay: hold the cursor back by however late the sound arrives ----

function setDelay(ms: number): void {
  const v = Math.max(+ui.delay.min, Math.min(+ui.delay.max, Math.round(ms / 5) * 5));
  ui.delay.value = String(v);
  ui.delayOut.textContent = `${v > 0 ? "+" : ""}${v} ms`;
  store.set("avDelay", v);
}
setDelay(store.get<number>("avDelay") ?? 0);
ui.delay.addEventListener("input", () => setDelay(+ui.delay.value));
$("av-minus").addEventListener("click", () => setDelay(+ui.delay.value - 10));
$("av-plus").addEventListener("click", () => setDelay(+ui.delay.value + 10));

const avTest = $("av-test");
const avTap = $<HTMLButtonElement>("av-tap");
const avDot = $("av-dot");
const avResult = $("av-result");
let tapTest: TapTest | null = null;
let tapTimer = 0;

function endTapTest(): void {
  tapTest?.stop();
  tapTest = null;
  clearTimeout(tapTimer);
  avTap.disabled = true;
}

$("av-measure").addEventListener("click", () => {
  if (player?.playing) stopPlayback();
  endTapTest();
  const ctx = audio();
  void ctx.resume();
  avTest.hidden = false;
  avTap.disabled = false;
  avTap.focus();
  const reported = reportedDelay(ctx);
  avResult.textContent = reported !== null ? `Your browser reports about ${reported} ms; tapping will tell us what you actually hear.` : "";
  const test = (tapTest = new TapTest(ctx));
  const end = test.start();
  // flash the dot in time with each click, shifted by the current setting, so you can see whether it matches
  const flash = () => {
    if (tapTest !== test) return;
    const now = ctx.currentTime - +ui.delay.value / 1000;
    avDot.classList.toggle("on", test.clicks.some((c) => now >= c && now < c + 0.1));
    if (ctx.currentTime < end + 0.8) requestAnimationFrame(flash);
  };
  requestAnimationFrame(flash);
  tapTimer = window.setTimeout(() => {
    const r = test.result();
    endTapTest();
    avDot.classList.remove("on");
    if (!r) {
      avResult.textContent = "Not enough taps landed near the clicks. Press Measure to try again.";
      return;
    }
    setDelay(r.ms);
    avResult.textContent =
      `Measured ${r.ms} ms from ${r.taps} taps (give or take ${r.spreadMs} ms). The cursor now waits that long. ` +
      (r.spreadMs > 40 ? "Your taps were spread out, so try once more for a steadier number. " : "") +
      "Fine-tune with − and + if the cursor still looks early or late.";
  }, (end - ctx.currentTime + 0.8) * 1000);
});

avTap.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  tapTest?.tap(e);
  avTap.classList.add("hit");
  setTimeout(() => avTap.classList.remove("hit"), 80);
});
document.addEventListener("keydown", (e) => {
  if (!tapTest || avTest.hidden || e.repeat || (e.key !== " " && e.key !== "Enter")) return;
  e.preventDefault();
  tapTest.tap(e);
});
$("av-close").addEventListener("click", () => {
  endTapTest();
  avTest.hidden = true;
});

// ---- recording and analysis ----

let recordStartedAt = 0;

ui.record.addEventListener("click", async () => {
  if (!score) return;
  if (recorder?.recording) return stopPlayback();
  try {
    const c = audio();
    await recorder!.start();
    recordStartedAt = c.currentTime;
    await startPlayback(!ui.playWhileRecording.checked);
    ui.record.textContent = "Stop and check";
    ui.record.classList.add("on");
    ui.play.disabled = true;
    status(ui.countIn.checked ? "Recording. Start after the count-in." : "Recording…");
  } catch (e) {
    status(`Could not record: ${(e as Error).message}`, "error");
  }
});

async function finishRecording(): Promise<void> {
  const c = audio();
  const raw = recorder!.stop();
  ui.record.textContent = "Record";
  ui.record.classList.remove("on");
  ui.play.disabled = training();
  // drop the count-in, so its clicks are not taken for notes
  const skip = Math.max(0, Math.floor((player!.firstBeatTime - recordStartedAt - 0.25) * c.sampleRate));
  const samples = raw.subarray(Math.min(skip, raw.length));
  if (samples.length < c.sampleRate * 0.5) return status("The recording was too short to check.", "error");
  status("Checking your playing…");
  const t = await toAnalysisRate(samples, c.sampleRate);
  if (training()) return trainerPass(t);
  take = t;
  await check();
}

ui.audioFile.addEventListener("change", async () => {
  const f = ui.audioFile.files?.[0];
  ui.audioFile.value = "";
  if (!f || !score) return;
  try {
    status(`Reading ${f.name}…`);
    take = await timed("decode-audio", async () => decodeFile(audio(), await f.arrayBuffer()));
    await check();
  } catch (e) {
    status(`Could not read ${f.name}: ${(e as Error).message}`, "error");
  }
});

async function check(): Promise<void> {
  return timed("check", checkNow);
}

async function checkNow(): Promise<void> {
  if (!take || !score) return;
  await new Promise((r) => setTimeout(r, 30)); // let the status paint
  try {
    const fresh = parseScore(plainXml, score.partId, score.title); // a copy of the shown parts, to color
    const s = settings();
    if (!track || track.take !== take || track.a4 !== s.a4) {
      const t = take;
      const pitch = await timed("track-pitch", () =>
        trackPitchAsync(t, s.a4, (done) => status(`Listening to the recording… ${Math.round(done * 100)}%`)),
      );
      track = { take: t, a4: s.a4, pitch };
    }
    const pitch = track.pitch;
    analysis = await timed("analyze", () => analyze(fresh, pitch, s));
    coloredScore(analysis);
    await render(new XMLSerializer().serializeToString(analysis.score.doc));
    showingColors = true;
    showFeedback(analysis);
    status("Done. Colored notes show how each one went.");
  } catch (e) {
    status(`Could not check the recording: ${(e as Error).message}`, "error");
  }
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function download(blob: Blob, name: string): void {
  const a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function loopSpot(sp: Spot): void {
  loopMeasures(sp.fromIndex, sp.toIndex);
  if (sp.loopBpm) ui.tempo.value = String(Math.max(30, Math.min(120, Math.round((sp.loopBpm / writtenTempo()) * 20) * 5)));
  updateTempoLabel();
}

function loopMeasures(from: number, to: number): void {
  ui.from.value = String(from);
  ui.to.value = String(to);
  ui.loop.checked = true;
  updateTempoLabel();
  ui.controls.scrollIntoView({ behavior: "smooth" });
  status(`Looping measures ${score!.measures[from]} to ${score!.measures[to]}. Press Play, or Wait mode.`);
}

function showFeedback(a: Analysis): void {
  const s = summarize(a);
  const box = ui.feedback;
  box.replaceChildren();
  const head = el("div", undefined, "cards");
  const card = (big: string, small: string) => {
    const c = el("div", undefined, "card");
    c.append(el("strong", big), el("span", small));
    head.append(c);
  };
  card(s.inTunePercent !== null ? `${s.inTunePercent}%` : "–", "notes in tune");
  card(a.tempoBpm ? `${Math.round(a.tempoBpm)}` : "–", "bpm played");
  card(String(s.counts.missed + s.counts.wrong_note), "missed or wrong");
  card(String(a.results.filter((r) => r.timing).length), "early or late");
  box.append(el("h2", `Feedback · ${s.span}`), head);
  const lines = el("ul", undefined, "lines");
  for (const t of [s.tempo, s.pitch, s.timing, s.scoreCheck, s.doubleStops, ...a.warnings]) if (t) lines.append(el("li", t));
  box.append(lines);

  const spots = problemSpots(a);
  if (spots.length) {
    box.append(el("h3", "Spots to practise"));
    const list = el("ol", undefined, "spots");
    for (const sp of spots) {
      const li = el("li");
      const where = sp.fromMeasure === sp.toMeasure ? `Measure ${sp.fromMeasure}` : `Measures ${sp.fromMeasure}–${sp.toMeasure}`;
      li.append(el("strong", where), el("span", ` ${sp.notes.slice(0, 5).join("; ")}`));
      const b = el("button", sp.loopBpm ? `Loop at ${sp.loopBpm} bpm` : "Loop it");
      b.type = "button";
      b.addEventListener("click", () => loopSpot(sp));
      li.append(b);
      list.append(li);
    }
    box.append(list);
  }

  const issues = a.results.filter((r) => r.status !== "not_played" && r.status !== "double_stop" && (r.status !== "in_tune" || r.timing));
  if (issues.length) {
    const det = el("details");
    det.append(el("summary", `All ${issues.length} notes that need attention`));
    const table = el("table");
    table.append(rowOf(["Measure", "Beat", "Written", "What happened"], "th"));
    for (const r of issues) table.append(rowOf([r.measure, String(r.beatInMeasure + 1), r.written, whatHappened(r)], "td", r.status));
    det.append(table);
    box.append(det);
  }

  const legend = el("p", undefined, "legend");
  for (const [k, cls] of [["in_tune", "in_tune"], ["slightly_off", "slightly_off"], ["out_of_tune", "out_of_tune"], ["missed", "missed"], ["score_suspect", "score_suspect"]] as const) {
    legend.append(el("span", LABELS[k], `dot ${cls}`));
  }
  box.append(legend);

  const tools = el("div", undefined, "tools");
  const btn = (text: string, fn: () => void) => {
    const b = el("button", text);
    b.type = "button";
    b.addEventListener("click", fn);
    tools.append(b);
  };
  btn(showingColors ? "Hide colors" : "Show colors", async () => {
    showingColors = !showingColors;
    await render(showingColors && analysis ? new XMLSerializer().serializeToString(analysis.score.doc) : plainXml);
    showFeedback(a);
  });
  if (take) btn("Save recording", () => download(encodeWav(take!, 22050), `${a.score.title} take.wav`));
  btn("Download colored score", () =>
    download(new Blob([new XMLSerializer().serializeToString(a.score.doc)], { type: "application/vnd.recordare.musicxml+xml" }), `${a.score.title} feedback.musicxml`),
  );
  box.append(tools);
  box.hidden = false;
}

function whatHappened(r: NoteResult): string {
  if (r.status === "in_tune") return r.timing ? `in tune, ${Math.abs(r.timingMs!)} ms ${r.timing}` : "in tune";
  if (r.status === "score_suspect") return `heard ${r.heard}: the score may be wrong here`;
  return describe(r).slice(r.written.length + 1);
}

function rowOf(cells: string[], tag: "td" | "th", cls?: string): HTMLTableRowElement {
  const tr = el("tr", undefined, cls);
  for (const c of cells) tr.append(el(tag, c));
  return tr;
}

// ---- wait mode: the cursor waits on each note until you play it ----

const wp = {
  panel: $("wait-panel"),
  note: $("wait-note"),
  where: $("wait-where"),
  progress: $("wait-progress"),
  heard: $("wait-heard"),
};
let mic: LiveMic | null = null;
let judge: WaitJudge | null = null;
let waitAccomp: Score[] = [];
let waitStarted = 0;
let quietUntil = 0; // the mic is ignored while the app plays a hint, so it doesn't hear itself
let wrongInRow = 0;
let heardShown = "";

const waiting = (): boolean => judge !== null;

async function startWait(): Promise<void> {
  if (!score) return;
  if (player?.playing) stopPlayback();
  const steps = waitSteps(score, +ui.from.value, +ui.to.value);
  if (!steps.length) return status("There are no notes in these measures.", "error");
  const s = settings();
  const c = audio();
  const m = new LiveMic(c);
  try {
    await m.start();
  } catch (e) {
    return status(`Could not use the microphone: ${(e as Error).message}`, "error");
  }
  mic = m;
  judge = new WaitJudge(steps, { cents: s.okCents, holdMs: 150 });
  waitAccomp = accompaniment();
  mic.onFrame = (f) => onMicFrame(f, s.a4);
  waitStarted = performance.now();
  wrongInRow = 0;
  ui.wait.textContent = "Stop waiting";
  ui.wait.classList.add("on");
  ui.play.disabled = ui.record.disabled = true;
  wp.panel.hidden = false;
  osmd?.cursor.show();
  osmd?.cursor.reset();
  lastBeat = -1;
  showStep();
  status(
    waitAccomp.length
      ? "Play each note when you're ready; the other parts follow you. Use headphones so the microphone hears only you."
      : "Play each note when you're ready. The cursor waits for you.",
  );
}

function showStep(): void {
  const st = judge?.current;
  if (!st || !score) return;
  wp.note.textContent = stepName(st);
  wp.note.classList.remove("ok");
  wp.where.textContent = celloWhere(Math.min(...st.midis));
  wp.progress.textContent = `${judge!.index + 1} of ${judge!.steps.length}`;
  moveCursorTo(st.beat);
}

function onMicFrame(f: MicFrame, a4: number): void {
  if (!judge || f.time < quietUntil) return;
  const midi = f.hz ? 69 + 12 * Math.log2(f.hz / a4) : null;
  const heard = midi === null ? "" : `heard ${midiName(Math.round(midi))}`;
  if (heard !== heardShown) {
    wp.heard.textContent = heardShown = heard;
    wp.heard.classList.remove("wrong");
  }
  const ev = judge.feed(midi, f.rms, f.time);
  if (ev === "wrong") {
    wp.heard.classList.add("wrong");
    if (++wrongInRow === 3) playHint();
  } else if (ev) advanced(ev === "done");
}

function advanced(done: boolean): void {
  const prev = judge!.steps[judge!.index - 1];
  wrongInRow = 0;
  if (waitAccomp.length && score) {
    // the other parts play from the note you just found up to your next one
    const next = judge!.current?.beat ?? score.measureStarts[+ui.to.value + 1] ?? score.totalBeats;
    player!.playSpan(waitAccomp, prev.beat, next, +ui.tempo.value / 100);
  }
  if (done) finishWait(true);
  else showStep();
}

/** Plays the note you're looking for, at a comfortable length. */
function playHint(): void {
  const st = judge?.current;
  if (!st || !score || !player) return;
  const n = st.notes[0];
  const secs = score.secondsAt(n.beat + n.duration) - score.secondsAt(n.beat);
  const factor = Math.max(1, secs / 1.2);
  player.playSpan([score], st.beat, st.beat + 1e-3, factor, 0.9);
  quietUntil = performance.now() + (secs / factor) * 1000 + 350;
  status(`Listen: ${stepName(st)}. Then play it.`);
}

function stopWait(): void {
  mic?.stop();
  mic = null;
  judge = null;
  player?.stop();
  ui.wait.textContent = "Wait mode";
  ui.wait.classList.remove("on");
  ui.play.disabled = ui.record.disabled = false;
  wp.panel.hidden = true;
  osmd?.cursor.hide();
}

function finishWait(completed: boolean): void {
  const j = judge;
  if (!j || !score) return stopWait();
  const secs = Math.round((performance.now() - waitStarted) / 1000);
  stopWait();
  if (j.index === 0) return status("Wait mode stopped.");
  const found = j.steps.slice(0, j.index);
  const hard = j.hardest();
  const time = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const box = ui.feedback;
  box.replaceChildren();
  const head = el("div", undefined, "cards");
  for (const [big, small] of [
    [`${found.length}`, completed ? "notes found" : `of ${j.steps.length} notes found`],
    [time, "time taken"],
    [`${found.filter((s) => s.tries === 0).length}`, "found first time"],
    [`${hard.length}`, "needed several tries"],
  ]) {
    const c = el("div", undefined, "card");
    c.append(el("strong", big), el("span", small));
    head.append(c);
  }
  box.append(el("h2", `Wait mode · Measures ${found[0].measure} to ${found[found.length - 1].measure}`), head);
  if (hard.length) {
    box.append(el("h3", "Notes to work on"));
    const list = el("ol", undefined, "spots");
    for (const st of hard.slice(0, 8)) {
      const li = el("li");
      li.append(el("strong", `Measure ${st.measure}, beat ${Math.floor(st.beatInMeasure) + 1}`), el("span", ` ${stepName(st)}: ${st.tries} wrong tries`));
      const b = el("button", "Loop this measure");
      b.type = "button";
      b.addEventListener("click", () => loopMeasures(st.measureIndex, st.measureIndex));
      li.append(b);
      list.append(li);
    }
    box.append(list);
  } else box.append(el("p", "Every note came within two tries.", "hint"));
  box.hidden = false;
  if (completed && ui.loop.checked) {
    status("Done. Going round again; press Stop waiting to finish.");
    void startWait();
  } else status(completed ? "Done: you found every note. Switch to Play to bring it up to tempo." : "Wait mode stopped.");
}

ui.wait.addEventListener("click", () => (waiting() ? finishWait(false) : void startWait()));
$("wait-stop").addEventListener("click", () => finishWait(false));
$("wait-hint").addEventListener("click", playHint);
$("wait-skip").addEventListener("click", () => {
  const ev = judge?.skip(performance.now());
  if (ev) advanced(ev === "done");
});

// ---- speed trainer: loop a passage, raising the tempo after each clean pass ----

const tr = {
  box: $<HTMLDetailsElement>("trainer"),
  start: $<HTMLSelectElement>("tr-start"),
  target: $<HTMLSelectElement>("tr-target"),
  step: $<HTMLSelectElement>("tr-step"),
  need: $<HTMLSelectElement>("tr-need"),
  go: $<HTMLButtonElement>("tr-go"),
  best: $("tr-best"),
  log: $("tr-log"),
};
let trainer: SpeedTrainer | null = null;
let trainerTimer = 0;

for (const sel of [tr.start, tr.target]) for (let p = 30; p <= 120; p += 5) sel.append(new Option(`${p}%`, String(p)));
{
  const saved = { ...DEFAULT_TRAINER, ...(store.get<Partial<TrainerConfig>>("trainer") ?? {}) };
  tr.start.value = String(saved.start);
  tr.target.value = String(saved.target);
  tr.step.value = String(saved.step);
  tr.need.value = String(saved.need);
}
function trainerConfig(): TrainerConfig {
  const c = { start: +tr.start.value, target: +tr.target.value, step: +tr.step.value, need: +tr.need.value };
  store.set("trainer", c);
  return c;
}

/** The fastest clean pass saved for these measures of this score. */
const bestKey = () => `trainer:${fileName}:${ui.from.value}-${ui.to.value}`;
function showBest(): void {
  const b = score ? store.get<number>(bestKey()) : null;
  tr.best.textContent = b ? `Fastest clean pass for these measures so far: ${b}%.` : "";
}

const training = (): boolean => trainer !== null;

function startTrainer(): void {
  if (!score) return;
  if (player?.playing) stopPlayback();
  if (waiting()) stopWait();
  trainer = new SpeedTrainer(trainerConfig());
  tr.log.replaceChildren();
  tr.go.textContent = "Stop trainer";
  tr.go.classList.add("on");
  ui.play.disabled = ui.record.disabled = ui.wait.disabled = true;
  void runPass();
}

async function runPass(): Promise<void> {
  if (!trainer || !score) return;
  ui.tempo.value = String(trainer.tempo);
  updateTempoLabel();
  try {
    const c = audio();
    await recorder!.start();
    recordStartedAt = c.currentTime;
    await startPlayback(!ui.playWhileRecording.checked);
    status(`Pass ${trainer.passes.length + 1} at ${trainer.tempo}%. ${ui.countIn.checked ? "Start after the count-in." : "Play now."}`);
  } catch (e) {
    stopTrainer();
    status(`Could not record: ${(e as Error).message}`, "error");
  }
}

/** Called with each finished pass's recording. */
async function trainerPass(t: Float32Array): Promise<void> {
  if (!trainer || !score) return;
  const tempo = trainer.tempo;
  status(`Listening to pass ${trainer.passes.length + 1}…`);
  try {
    const s = settings();
    const pitch = await timed("track-pitch", () => trackPitchAsync(t, s.a4));
    const a = await timed("analyze", () => analyze(parseScore(plainXml, score!.partId, score!.title), pitch, s));
    if (!trainer) return; // stopped while listening
    analysis = a;
    take = t;
    const p = judgePass(a, tempo, (writtenTempo() * tempo) / 100, trainer.cfg.need);
    const verdict = trainer.next(p);
    const why = p.dragged ? "fell behind the tempo" : `${p.percent}% right`;
    const then = { up: `clean, up to ${trainer.tempo}%`, same: "again at this tempo", down: `back to ${trainer.tempo}%`, done: "clean at the target!" }[verdict];
    tr.log.prepend(el("li", `${tempo}%: ${why}, ${then}`, p.clean ? "clean" : "miss"));
    if (p.clean && tempo > (store.get<number>(bestKey()) ?? 0)) store.set(bestKey(), tempo);
    showBest();
    if (verdict === "done") return finishTrainer(`Done: a clean pass at ${tempo}%.`);
    status(`Pass ${trainer.passes.length}: ${why}. Next pass at ${trainer.tempo}% in 3 seconds…`);
    trainerTimer = window.setTimeout(() => void runPass(), 3000);
  } catch (e) {
    if (!trainer) return;
    tr.log.prepend(el("li", `${tempo}%: couldn't hear this pass (${(e as Error).message}), trying again`, "miss"));
    trainerTimer = window.setTimeout(() => void runPass(), 3000);
  }
}

function stopTrainer(): void {
  trainer = null;
  clearTimeout(trainerTimer);
  if (recorder?.recording) recorder.stop(); // discard the unfinished pass
  player?.stop();
  cancelAnimationFrame(frame);
  osmd?.cursor.hide();
  ui.play.textContent = "Play";
  tr.go.textContent = "Start trainer";
  tr.go.classList.remove("on");
  ui.play.disabled = ui.record.disabled = ui.wait.disabled = false;
}

function finishTrainer(message: string): void {
  const best = trainer?.best;
  stopTrainer();
  status(best ? `${message} Fastest clean pass: ${best}%.` : message);
  if (analysis) showFeedback(analysis); // the last pass, in detail
}

tr.go.addEventListener("click", () => (training() ? finishTrainer("Trainer stopped.") : startTrainer()));
for (const sel of [tr.start, tr.target, tr.step, tr.need]) sel.addEventListener("change", trainerConfig);
ui.from.addEventListener("change", showBest);
ui.to.addEventListener("change", showBest);

// ---- score marks: fingerings, bowings and notes on top of the score, saved beside it ----

const mk = {
  btn: $<HTMLButtonElement>("marks-btn"),
  bar: $("marks-bar"),
  text: $<HTMLInputElement>("marks-text"),
  show: $<HTMLInputElement>("marks-show"),
  saved: $("marks-saved"),
  tools: [...document.querySelectorAll<HTMLButtonElement>("#marks-bar [data-kind]")],
};
let marks: MarkSet | null = null;
let places = new Map<string, NotePlace>();
let tool: { kind: MarkKind | "erase"; value?: string } | null = null;
let marking = false;
let pushTimer = 0;
let lastTouched: string | null = null;

const sidecarName = () => `${fileName.replace(/\.[^.]+$/, "")}.marks.json`;
const localKey = () => `marks:${pieceId ?? "device"}:${fileName}`;

/** Loads this score's marks: this device's copy and the library's, whichever was changed last. */
async function loadMarks(): Promise<void> {
  const name = fileName;
  const local = store.get<MarkSet & { pending?: boolean }>(localKey());
  marks = local ?? emptyMarks(name);
  drawScoreMarks();
  const lib = pieceId ? library() : null;
  if (!lib || !pieceId) return;
  try {
    const remote = parseMarks(JSON.stringify(await lib.readSidecar(pieceId, sidecarName())));
    if (name !== fileName) return; // another score was opened meanwhile
    const best = newer(local, remote) ?? emptyMarks(name);
    marks = best;
    store.set(localKey(), best);
    drawScoreMarks();
    if (local?.pending || (local && best === local && remote && local.updated !== remote.updated)) pushMarks(0);
  } catch {
    /* offline and never synced: this device's copy is all there is */
  }
}

/** Saves on this device now, and to the library a moment later (so a run of taps is one upload). */
function saveMarks(): void {
  if (!marks) return;
  store.set(localKey(), { ...marks, pending: !!pieceId });
  pushMarks(1500);
}

function pushMarks(delay: number): void {
  clearTimeout(pushTimer);
  const lib = pieceId ? library() : null;
  if (!lib || !pieceId || !marks) {
    mk.saved.textContent = marks?.marks.length ? "Saved on this device." : "";
    return;
  }
  const [id, set, key] = [pieceId, marks, localKey()];
  pushTimer = window.setTimeout(async () => {
    try {
      const { pending: _, ...clean } = set as MarkSet & { pending?: boolean };
      await lib.writeSidecar(id, sidecarName(), clean);
      if (store.get<MarkSet>(key)?.updated === set.updated) store.set(key, clean);
      mk.saved.textContent = "Saved to your library.";
    } catch {
      mk.saved.textContent = "Saved on this device. It goes to your library the next time this score opens online.";
    }
  }, delay);
}

/** Redraws the marks over the score; call after every render. */
function drawScoreMarks(): void {
  if (!osmd || !score || !choice || ui.sheet.hidden) return;
  if (!marking && !marks?.marks.length) {
    // nothing to draw: skip finding every note on the page (it takes a moment on a big score)
    ui.sheet.querySelector(".marks-layer")?.replaceChildren();
    return;
  }
  // marks belong to the written notes, so they stay on the same notes when the score is transposed
  places = notePlaces(osmd, ui.sheet, score, Math.max(0, choice.shown.indexOf(choice.practise)), view.transpose);
  drawMarks(ui.sheet, places, marks ? marksIn(marks, score, view.transpose) : new Map(), marking ? lastTouched : null);
  ui.sheet.querySelector(".marks-layer")?.classList.toggle("off", !mk.show.checked);
}

function setMarking(on: boolean): void {
  marking = on && !!score;
  mk.bar.hidden = !marking;
  ui.controls.hidden = marking || !score; // more room for the score while marking
  mk.btn.setAttribute("aria-pressed", String(marking));
  ui.sheet.classList.toggle("marking", marking);
  lastTouched = null;
  if (marking) {
    if (!mk.show.checked) mk.show.checked = true;
    status(tool ? "Tap notes to mark them. Tap again to take a mark off." : "Pick a mark, then tap notes.");
  }
  drawScoreMarks();
}

for (const b of mk.tools)
  b.addEventListener("click", () => {
    const kind = b.dataset.kind as MarkKind | "erase";
    const same = tool && tool.kind === kind && tool.value === b.dataset.value;
    tool = same ? null : { kind, value: b.dataset.value };
    for (const x of mk.tools) x.setAttribute("aria-pressed", String(x === b && !same));
    mk.text.hidden = tool?.kind !== "text";
    if (tool?.kind === "text") mk.text.focus();
    status(tool ? "Tap notes to mark them. Tap again to take a mark off." : "Pick a mark, then tap notes.");
  });

ui.sheet.addEventListener("click", (e) => {
  if (!marking || !marks || !score) return;
  const c = ui.sheet.getBoundingClientRect();
  const hit = nearestNote(places, e.clientX - c.left + ui.sheet.scrollLeft, e.clientY - c.top + ui.sheet.scrollTop);
  if (!hit) return;
  lastTouched = hit.key;
  if (!tool) return status("Pick a mark first.");
  if (tool.kind === "erase") marks = clearNote(marks, hit.key);
  else if (tool.kind === "text") {
    const v = mk.text.value.trim();
    if (!v) return status("Type the text first, then tap a note.");
    marks = toggleMark(marks, { note: hit.key, kind: "text", value: v });
  } else marks = toggleMark(marks, { note: hit.key, kind: tool.kind, value: tool.value });
  saveMarks();
  drawScoreMarks();
});

mk.btn.addEventListener("click", () => setMarking(!marking));
$("marks-done").addEventListener("click", () => setMarking(false));
mk.show.addEventListener("change", () => {
  store.set("marks.show", mk.show.checked);
  drawScoreMarks();
});
mk.show.checked = store.get<boolean>("marks.show") ?? true;

// ---- transpose and clef: how the score is shown, saved for each score ----

for (let t = MAX_TRANSPOSE; t >= -MAX_TRANSPOSE; t--) ui.transpose.append(new Option(transposeLabel(t), String(t)));
for (const [k, label] of Object.entries(CLEF_LABELS)) ui.clef.append(new Option(label, k));

function showView(): void {
  ui.transpose.value = String(view.transpose);
  ui.clef.value = view.clef;
}

async function changeView(): Promise<void> {
  if (!score || !choice) return;
  const next = cleanView({ transpose: +ui.transpose.value, clef: ui.clef.value as ClefChoice });
  if (training()) stopTrainer();
  if (player?.playing) stopPlayback();
  if (waiting()) stopWait();
  store.set(`view:${fileName}`, next);
  status(next.transpose !== view.transpose ? "Transposing…" : "Changing the clef…");
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); // let the message show first
  await openScore(fileName, xml, choice).catch((e) => status((e as Error).message, "error"));
}
ui.transpose.addEventListener("change", () => void changeView());
ui.clef.addEventListener("change", () => void changeView());

// ---- restore the last session ----

labelCustom();
for (const [input, key] of [[ui.a4, "a4"], [ui.pitchStrict, "pitch"], [ui.timingStrict, "timing"], [ui.click, "click"]] as const) {
  const v = store.get<string>(key);
  if (v) input.value = v;
  input.addEventListener("change", () => {
    store.set(key, input.value);
    if (analysis && take) void check(); // re-judge the same take with the new windows
  });
}
const savedTempo = store.get<number>("tempo");
if (savedTempo) ui.tempo.value = String(savedTempo);
{
  // Load the renderer when the user reaches for "Open score", so it loads while the file picker is open.
  // (Loading it in the background at startup froze taps for about a quarter second on a phone.)
  const warm = () => void sheetRenderer();
  const opener = document.querySelector<HTMLElement>('label[for="score-file"]');
  for (const ev of ["pointerdown", "focus", "keydown"]) opener?.addEventListener(ev, warm, { once: true });
}

/** Is a score open? The app asks before going home, since that closes it. */
export function hasScore(): boolean {
  return score !== null;
}

/** Closes the score and anything about it (playback, a recording in progress, feedback), freeing its memory. */
export function closeScore(): void {
  if (waiting()) stopWait();
  if (training()) stopTrainer();
  if (recorder?.recording) recorder.stop(); // discard: the user chose to leave
  player?.stop();
  cancelAnimationFrame(frame);
  ui.play.textContent = "Play";
  ui.record.textContent = "Record";
  ui.record.classList.remove("on");
  ui.play.disabled = false;
  score = null;
  xml = plainXml = fileName = "";
  fullDoc = null;
  choice = null;
  accompParts = null;
  analysis = null;
  take = null;
  track = null;
  showingColors = false;
  osmd?.clear();
  ui.sheet.hidden = true;
  ui.feedback.hidden = true;
  ui.feedback.replaceChildren();
  showFitOffer();
  ui.controls.hidden = true;
  scoreFocus.set(false);
  ui.focusBtn.hidden = true;
  ui.partsBtn.hidden = true;
  ui.marksBtn.hidden = true;
  setMarking(false);
  marks = null;
  pieceId = null;
  view = PLAIN_VIEW;
  ui.sheet.querySelector(".marks-layer")?.replaceChildren();
  ui.title.textContent = "";
  ui.welcome.hidden = false;
  status("Open a score to start.");
}

/**
 * Called when the user opens the screen: pick up tuning, headphone delay and judging windows changed in Settings
 * or the Tuner.
 */
export function enterPractice(): void {
  const d = store.get<number>("avDelay");
  if (d !== null && d !== +ui.delay.value) setDelay(d);
  const before = JSON.stringify([ui.a4.value, windows()]);
  const v = store.get<string>("a4");
  if (v) ui.a4.value = v;
  for (const [sel, key] of [[ui.pitchStrict, "pitch"], [ui.timingStrict, "timing"]] as const) {
    const s = store.get<string>(key);
    if (s) sel.value = s;
  }
  labelCustom();
  if (analysis && take && JSON.stringify([ui.a4.value, windows()]) !== before) void check(); // re-judge the same take
}
