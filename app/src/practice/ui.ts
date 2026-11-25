/** The Practice tab: slowed playback, loops, metronome, recording and note-by-note feedback. */
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { $, sharedAudio, store } from "../core/app";
import { parseScore, scoreText, type Score } from "../core/score";
import { analyze, DEFAULT_SETTINGS, PITCH_WINDOWS, TIMING_WINDOWS, type Analysis, type NoteResult, type Strictness } from "./analyze";
import { trackPitch, type PitchTrack } from "./pitch";
import { Player } from "./player";
import { decodeFile, encodeWav, Recorder, toAnalysisRate } from "./recorder";
import { coloredScore, describe, LABELS, problemSpots, summarize, type Spot } from "./report";

const ui = {
  scoreFile: $<HTMLInputElement>("score-file"),
  part: $<HTMLSelectElement>("part"),
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
  play: $<HTMLButtonElement>("play"),
  record: $<HTMLButtonElement>("record"),
  audioFile: $<HTMLInputElement>("audio-file"),
  a4: $<HTMLInputElement>("a4"),
  pitchStrict: $<HTMLSelectElement>("pitch-strict"),
  timingStrict: $<HTMLSelectElement>("timing-strict"),
  playWhileRecording: $<HTMLInputElement>("play-while-recording"),
  status: $("status"),
  welcome: $("welcome"),
  feedback: $("feedback"),
  sheet: $("sheet"),
};

let xml = "";
let fileName = "";
let score: Score | null = null;
let ctx: AudioContext | null = null;
let player: Player | null = null;
let recorder: Recorder | null = null;
let take: Float32Array | null = null; // last recording, at the analysis rate
let track: { take: Float32Array; a4: number; pitch: PitchTrack } | null = null; // its pitch, kept so re-checks are instant
let analysis: Analysis | null = null;
let showingColors = false;
const osmd = new OpenSheetMusicDisplay(ui.sheet, {
  autoResize: true,
  backend: "svg",
  drawTitle: true,
  drawPartNames: true,
  followCursor: true,
});

function status(text: string, kind: "info" | "error" = "info"): void {
  ui.status.textContent = text;
  ui.status.dataset.kind = kind;
}

function audio(): AudioContext {
  if (!ctx) {
    ctx = sharedAudio();
    player = new Player(ctx);
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
  await osmd.load(text);
  osmd.render();
}

async function openScore(name: string, text: string, part?: string): Promise<void> {
  const s = parseScore(text, part, name.replace(/\.[^.]+$/, ""));
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
  ui.part.hidden = s.parts.length < 2;
  ui.part.replaceChildren(...s.parts.map((p) => new Option(p.name, p.id, false, p.id === s.partId)));
  const opts = () => s.measures.map((m, i) => new Option(m, String(i)));
  ui.from.replaceChildren(...opts());
  ui.to.replaceChildren(...opts());
  ui.to.value = String(s.measures.length - 1);
  updateTempoLabel();
  await render(text);
  status(s.notes.length ? `${s.partName}: ${s.notes.length} notes in ${s.measures.length} measures.` : "This part has no notes.");
  if (text.length < 3_000_000) store.set("score", { name, text, part: s.partId });
}

ui.scoreFile.addEventListener("change", async () => {
  const f = ui.scoreFile.files?.[0];
  if (!f) return;
  try {
    status(`Opening ${f.name}…`);
    await openScore(f.name, scoreText(f.name, await f.arrayBuffer()));
  } catch (e) {
    status(`Could not open ${f.name}: ${(e as Error).message}`, "error");
  }
  ui.scoreFile.value = "";
});

ui.part.addEventListener("change", () => openScore(fileName, xml, ui.part.value).catch((e) => status((e as Error).message, "error")));
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
  const beat = player?.currentBeat();
  if (beat !== null && beat !== undefined) moveCursorTo(beat);
  frame = requestAnimationFrame(follow);
}

async function startPlayback(mute = false): Promise<void> {
  if (!score) return;
  audio();
  const parts = ui.accomp.checked ? [score, ...score.parts.filter((p) => p.id !== score!.partId).map((p) => parseScore(xml, p.id))] : [score];
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
  osmd.cursor.show();
  osmd.cursor.reset();
  lastBeat = -1;
  moveCursorTo(score.measureStarts[+ui.from.value] ?? 0);
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(follow);
  ui.play.textContent = "Stop";
}

function stopPlayback(): void {
  player?.stop();
  cancelAnimationFrame(frame);
  osmd.cursor.hide();
  ui.play.textContent = "Play";
  if (recorder?.recording) void finishRecording();
}

ui.play.addEventListener("click", () => {
  if (player?.playing) stopPlayback();
  else startPlayback().catch((e) => status((e as Error).message, "error"));
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
  ui.play.disabled = false;
  // drop the count-in, so its clicks are not taken for notes
  const skip = Math.max(0, Math.floor((player!.firstBeatTime - recordStartedAt - 0.25) * c.sampleRate));
  const samples = raw.subarray(Math.min(skip, raw.length));
  if (samples.length < c.sampleRate * 0.5) return status("The recording was too short to check.", "error");
  status("Checking your playing…");
  take = await toAnalysisRate(samples, c.sampleRate);
  await check();
}

ui.audioFile.addEventListener("change", async () => {
  const f = ui.audioFile.files?.[0];
  ui.audioFile.value = "";
  if (!f || !score) return;
  try {
    status(`Reading ${f.name}…`);
    take = await decodeFile(audio(), await f.arrayBuffer());
    await check();
  } catch (e) {
    status(`Could not read ${f.name}: ${(e as Error).message}`, "error");
  }
});

async function check(): Promise<void> {
  if (!take || !score) return;
  await new Promise((r) => setTimeout(r, 30)); // let the status paint
  try {
    const fresh = parseScore(xml, score.partId, fileName.replace(/\.[^.]+$/, ""));
    const s = settings();
    if (!track || track.take !== take || track.a4 !== s.a4) track = { take, a4: s.a4, pitch: trackPitch(take, s.a4) };
    analysis = analyze(fresh, track.pitch, s);
    await render(coloredScore(analysis));
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
  ui.from.value = String(sp.fromIndex);
  ui.to.value = String(sp.toIndex);
  ui.loop.checked = true;
  if (sp.loopBpm) ui.tempo.value = String(Math.max(30, Math.min(120, Math.round((sp.loopBpm / writtenTempo()) * 20) * 5)));
  updateTempoLabel();
  ui.controls.scrollIntoView({ behavior: "smooth" });
  status(`Looping measures ${sp.fromMeasure} to ${sp.toMeasure}. Press Play.`);
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
    await render(showingColors && analysis ? new XMLSerializer().serializeToString(analysis.score.doc) : xml);
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
const saved = store.get<{ name: string; text: string; part: string }>("score");
if (saved) openScore(saved.name, saved.text, saved.part).catch(() => status("Open a score to start."));

/** Called when the user opens the tab: pick up a tuning change made in another tab. */
export function enterPractice(): void {
  const v = store.get<string>("a4");
  if (v && v !== ui.a4.value) {
    ui.a4.value = v;
    if (analysis && take) void check();
  }
}
