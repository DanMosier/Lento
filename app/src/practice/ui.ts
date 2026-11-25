/** The Practice tab: slowed playback, loops, metronome, recording and note-by-note feedback. */
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { $, onOpenScore, sharedAudio, store } from "../core/app";
import { timed } from "../core/perf";
import { LiveMic, type MicFrame } from "../core/live-pitch";
import { defaultPart, midiName, parseScore, partXml, quickPartList, scoreText, type Score } from "../core/score";
import { choiceLabel, cleanChoice, pickParts, type PartChoice } from "./parts";
import { analyze, DEFAULT_SETTINGS, PITCH_WINDOWS, TIMING_WINDOWS, type Analysis, type NoteResult, type Strictness } from "./analyze";
import { type PitchTrack } from "./pitch";
import { trackPitchAsync } from "./pitch-async";
import { roomOut } from "../core/room";
import { SoundBank } from "../core/sounds";
import { partInstrument, Player } from "./player";
import { reportedDelay, TapTest } from "./latency";
import { decodeFile, encodeWav, Recorder, toAnalysisRate } from "./recorder";
import { coloredScore, describe, LABELS, problemSpots, summarize, type Spot } from "./report";
import { celloWhere, stepName, WaitJudge, waitSteps } from "./wait";
import { DEFAULT_TRAINER, judgePass, SpeedTrainer, type TrainerConfig } from "./trainer";

const ui = {
  scoreFile: $<HTMLInputElement>("score-file"),
  partsBtn: $<HTMLButtonElement>("parts-btn"),
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
  playWhileRecording: $<HTMLInputElement>("play-while-recording"),
  delay: $<HTMLInputElement>("av-delay"),
  delayOut: $<HTMLOutputElement>("av-delay-out"),
  status: $("status"),
  welcome: $("welcome"),
  feedback: $("feedback"),
  sheet: $("sheet"),
};

let xml = "";
let plainXml = ""; // the chosen parts only, as drawn
let fullDoc: Document | null = null; // the whole file, parsed once and reused when parts change
let choice: PartChoice | null = null;
let accompParts: Score[] | null = null; // the other shown parts, parsed the first time they are played
let fileName = "";
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
  osmdLoading ??= import("opensheetmusicdisplay").then(
    ({ OpenSheetMusicDisplay }) =>
      (osmd = new OpenSheetMusicDisplay(ui.sheet, { autoResize: true, backend: "svg", drawTitle: true, drawPartNames: true, followCursor: true })),
  );
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

function settings() {
  return {
    ...DEFAULT_SETTINGS,
    a4: +ui.a4.value || 440,
    goodCents: PITCH_WINDOWS[ui.pitchStrict.value as Strictness][0],
    okCents: PITCH_WINDOWS[ui.pitchStrict.value as Strictness][1],
    timingMs: TIMING_WINDOWS[ui.timingStrict.value as Strictness],
    measures: [score!.measures[+ui.from.value], score!.measures[+ui.to.value]] as [string, string],
    strict: false,
  };
}

async function render(text: string): Promise<void> {
  ui.sheet.hidden = false; // OSMD measures the container, so it must be visible first
  const sheet = await sheetRenderer();
  await timed("render-score", async () => {
    await timed("load-sheet", () => sheet.load(text));
    timed("draw-sheet", () => sheet.render());
  });
}

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
async function openFile(name: string, text: string): Promise<void> {
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
  await openScore(name, text, picked);
}

async function openScoreNow(name: string, text: string, picked?: PartChoice): Promise<void> {
  const title = name.replace(/\.[^.]+$/, "");
  const reuse = text === xml && fullDoc !== null;
  const s = await timed("parse-score", () => parseScore(reuse ? fullDoc! : text, picked?.practise, title));
  fullDoc = s.doc;
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
  ui.title.textContent = s.title;
  ui.partsBtn.hidden = s.parts.length < 2;
  ui.partsBtn.textContent = choiceLabel(s.parts, choice);
  ui.accompLabel.hidden = choice.shown.length < 2;
  const opts = () => s.measures.map((m, i) => new Option(m, String(i)));
  ui.from.replaceChildren(...opts());
  ui.to.replaceChildren(...opts());
  ui.to.value = String(s.measures.length - 1);
  updateTempoLabel();
  plainXml = partXml(s.doc, choice.shown); // only the chosen parts are drawn
  await render(plainXml);
  loadSounds();
  showBest();
  status(s.notes.length ? `${s.partName}: ${s.notes.length} notes in ${s.measures.length} measures.` : "This part has no notes.");
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

onOpenScore(async ({ name, data }) => {
  if (training()) stopTrainer();
  if (player?.playing) stopPlayback();
  if (waiting()) stopWait();
  try {
    status(`Opening ${name}…`);
    await openFile(name, scoreText(name, data));
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
  accompParts ??= choice.shown.filter((id) => id !== choice!.practise).map((id) => parseScore(fullDoc!, id));
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

// ---- restore the last session ----

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
  ui.controls.hidden = true;
  ui.partsBtn.hidden = true;
  ui.title.textContent = "";
  ui.welcome.hidden = false;
  status("Open a score to start.");
}

/** Called when the user opens the screen: pick up tuning and headphone delay changed in Settings or the Tuner. */
export function enterPractice(): void {
  const d = store.get<number>("avDelay");
  if (d !== null && d !== +ui.delay.value) setDelay(d);
  const v = store.get<string>("a4");
  if (v && v !== ui.a4.value) {
    ui.a4.value = v;
    if (analysis && take) void check();
  }
}
