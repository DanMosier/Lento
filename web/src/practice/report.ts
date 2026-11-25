/** Summaries, practice spots and a colored copy of the score. Mirrors lento_practice/report.py. */
import type { Analysis, NoteResult, Status } from "./analyze";

export const COLORS: Partial<Record<Status, string>> = {
  in_tune: "#2E9E44",
  slightly_off: "#D99A00",
  out_of_tune: "#D0342C",
  wrong_note: "#D0342C",
  missed: "#8E44AD",
  score_suspect: "#1F6FD0",
  double_stop: "#7F8C8D",
};
const SEVERITY: Partial<Record<Status, number>> = { slightly_off: 1, out_of_tune: 2, wrong_note: 3, missed: 3 };
export const LABELS: Record<Status, string> = {
  in_tune: "in tune",
  slightly_off: "slightly off",
  out_of_tune: "out of tune",
  wrong_note: "wrong note",
  missed: "missed",
  score_suspect: "score may be wrong",
  double_stop: "double stop, not checked",
  not_played: "not in the recording",
};

/** Short text shown under the note in the colored score. */
export function label(r: NoteResult): string {
  const parts: string[] = [];
  if ((r.status === "slightly_off" || r.status === "out_of_tune") && r.cents !== null) parts.push(`${r.cents > 0 ? "+" : ""}${r.cents.toFixed(0)}`);
  else if (r.status === "wrong_note") parts.push(`${r.heard}?`);
  else if (r.status === "missed") parts.push("miss");
  else if (r.status === "score_suspect") parts.push("score?");
  if (r.timing) parts.push(r.timing);
  return parts.join(" ");
}

export function describe(r: NoteResult): string {
  const bits: string[] = [];
  if (r.status === "wrong_note") bits.push(`played ${r.heard}`);
  else if ((r.status === "slightly_off" || r.status === "out_of_tune") && r.cents !== null)
    bits.push(`${Math.abs(r.cents).toFixed(0)} cents ${r.cents > 0 ? "sharp" : "flat"}`);
  else if (r.status === "missed") bits.push("missed");
  if (r.timing && r.timingMs !== null) bits.push(`${Math.abs(r.timingMs).toFixed(0)} ms ${r.timing}`);
  return `${r.written} ${bits.join(" and ")}`;
}

const played = (a: Analysis) => a.results.filter((r) => r.status !== "not_played");
const severity = (r: NoteResult) => (SEVERITY[r.status] ?? 0) + (r.timing ? 1 : 0);

export interface Spot {
  fromMeasure: string;
  toMeasure: string;
  fromIndex: number;
  toIndex: number;
  issues: number;
  notes: string[];
  loopBpm: number | null;
}

/** The worst stretches of one or two measures, with a suggested loop tempo. */
export function problemSpots(a: Analysis, limit = 3): Spot[] {
  const perMeasure = new Map<number, number>();
  for (const r of played(a)) {
    const s = severity(r);
    if (s) perMeasure.set(r.note.measureIndex, (perMeasure.get(r.note.measureIndex) ?? 0) + s);
  }
  const spots: Spot[] = [];
  const taken = new Set<number>();
  const ranked = [...perMeasure.entries()].sort((p, q) => q[1] - p[1] || p[0] - q[0]);
  for (const [m] of ranked) {
    if (taken.has(m)) continue;
    const next = (perMeasure.get(m + 1) ?? 0) > 0 && !taken.has(m + 1) ? m + 1 : m;
    taken.add(m).add(next);
    const rs = played(a).filter((r) => r.note.measureIndex >= m && r.note.measureIndex <= next && severity(r) > 0);
    spots.push({
      fromMeasure: a.score.measures[m],
      toMeasure: a.score.measures[next],
      fromIndex: m,
      toIndex: next,
      issues: rs.reduce((s, r) => s + severity(r), 0),
      notes: rs.map(describe),
      loopBpm: a.tempoBpm ? Math.max(40, Math.round((a.tempoBpm * 0.75) / 2) * 2) : null,
    });
    if (spots.length === limit) break;
  }
  return spots;
}

export interface Summary {
  span: string;
  tempo: string | null;
  pitch: string;
  thresholds: string;
  timing: string;
  scoreCheck: string | null;
  doubleStops: string | null;
  counts: Record<Status, number>;
  inTunePercent: number | null;
}

export function summarize(a: Analysis): Summary {
  const s = a.settings;
  const p = played(a);
  const counts = Object.fromEntries(Object.keys(LABELS).map((k) => [k, p.filter((r) => r.status === k).length])) as Record<Status, number>;
  const graded = counts.in_tune + counts.slightly_off + counts.out_of_tune + counts.wrong_note + counts.missed;
  const pct = graded ? Math.round((100 * counts.in_tune) / graded) : null;
  let tempo: string | null = null;
  if (a.tempoBpm) {
    let drift = "";
    if (a.tempoStartBpm && a.tempoEndBpm && Math.abs(a.tempoEndBpm - a.tempoStartBpm) >= 0.06 * a.tempoBpm) {
      drift = ` You ${a.tempoEndBpm > a.tempoStartBpm ? "sped up" : "slowed down"} from about ${a.tempoStartBpm.toFixed(0)} to ${a.tempoEndBpm.toFixed(0)}.`;
    }
    tempo = `About ${a.tempoBpm.toFixed(0)} quarter notes a minute (the score says ${a.score.tempos[0][1]}).${drift}`;
  }
  return {
    span: a.firstMeasure ? `Measures ${a.firstMeasure} to ${a.lastMeasure}` : "No measures found",
    tempo,
    pitch:
      `${graded} notes: ${counts.in_tune} in tune${pct !== null ? ` (${pct}%)` : ""}, ${counts.slightly_off} slightly off, ` +
      `${counts.out_of_tune} out of tune, ${counts.wrong_note} wrong, ${counts.missed} missed.`,
    thresholds: `In tune means within ${s.goodCents} cents; slightly off within ${s.okCents}. Judged against A=${s.a4}.`,
    timing: `${p.filter((r) => r.timing === "early").length} early and ${p.filter((r) => r.timing === "late").length} late by more than ${s.timingMs} ms.`,
    scoreCheck: counts.score_suspect
      ? `${counts.score_suspect} notes in a row were all off by the same interval. The score was probably misread (for example a tenor clef read as alto), so they are not counted against you.`
      : null,
    doubleStops: counts.double_stop ? `Double stops: only one note of each is measured (${counts.double_stop} not checked).` : null,
    counts,
    inTunePercent: pct,
  };
}

function insertBefore(parent: Element, el: Element, before: string[]): void {
  const ref = Array.from(parent.children).find((c) => before.includes(c.localName));
  parent.insertBefore(el, ref ?? null);
}

/** Color and label each checked note in the analysis's score document; returns the MusicXML text. */
export function coloredScore(a: Analysis, labels = true): string {
  const doc = a.score.doc;
  for (const r of a.results) {
    const color = COLORS[r.status];
    if (!color) continue;
    r.note.elements.forEach((el, i) => {
      el.setAttribute("color", color);
      let head = Array.from(el.children).find((c) => c.localName === "notehead");
      if (!head) {
        head = doc.createElement("notehead");
        head.textContent = "normal";
        insertBefore(el, head, ["notehead-text", "staff", "beam", "notations", "lyric", "play", "listen"]);
      }
      head.setAttribute("color", color);
      const text = label(r);
      if (labels && i === 0 && text) {
        const lyric = doc.createElement("lyric");
        lyric.setAttribute("number", String(Array.from(el.children).filter((c) => c.localName === "lyric").length + 1));
        lyric.setAttribute("name", "feedback");
        lyric.setAttribute("color", color);
        const syl = doc.createElement("syllabic");
        syl.textContent = "single";
        const t = doc.createElement("text");
        t.textContent = text;
        lyric.append(syl, t);
        insertBefore(el, lyric, ["play", "listen"]);
      }
    });
  }
  return new XMLSerializer().serializeToString(doc);
}

export function summaryMarkdown(a: Analysis): string {
  const s = summarize(a);
  const lines = [`# ${a.score.title}: practice feedback`, "", `${a.score.partName}. ${s.span}.`, ""];
  if (s.tempo) lines.push(`**Tempo:** ${s.tempo}`);
  lines.push(`**Pitch:** ${s.pitch}`, s.thresholds, `**Timing:** ${s.timing}`);
  if (s.scoreCheck) lines.push(`**Check the score:** ${s.scoreCheck}`);
  if (s.doubleStops) lines.push(s.doubleStops);
  const spots = problemSpots(a);
  if (spots.length) {
    lines.push("", "## Spots to practise", "");
    spots.forEach((sp, i) => {
      const where = sp.fromMeasure === sp.toMeasure ? sp.fromMeasure : `${sp.fromMeasure} to ${sp.toMeasure}`;
      lines.push(`${i + 1}. **Measure ${where}:** ${sp.notes.slice(0, 6).join("; ")}.${sp.loopBpm ? ` Loop it at ${sp.loopBpm} bpm.` : ""}`);
    });
  }
  if (a.warnings.length) lines.push("", "## Notes on this analysis", "", ...a.warnings.map((w) => `- ${w}`));
  return lines.join("\n");
}
