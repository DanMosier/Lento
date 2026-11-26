/** Draws score marks over the rendered score, and finds the note under a tap. */
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import type { Score } from "../core/score";
import { glyph, noteKey, STACK, type Mark } from "./marks";

export interface NotePlace {
  key: string;
  x: number; // notehead, in px from the sheet container's top left (including its scroll)
  y: number;
  top: number; // top line of the note's staff
  unit: number; // px per staff space
}

/** Where each note of the practised part sits on the page right now. */
export function notePlaces(osmd: OpenSheetMusicDisplay, container: HTMLElement, score: Score, partIndex: number, transposed = 0): Map<string, NotePlace> {
  const places = new Map<string, NotePlace>();
  const svg = container.querySelector("svg");
  const inst = osmd.Sheet?.Instruments[partIndex];
  if (!svg || !inst || !osmd.GraphicSheet) return places;
  const unit = 10 * osmd.zoom;
  const c = container.getBoundingClientRect();
  const s = svg.getBoundingClientRect();
  const ox = s.left - c.left + container.scrollLeft;
  const oy = s.top - c.top + container.scrollTop;
  const byBeat = new Map(score.notes.map((n) => [`${Math.round(n.beat * 1000)}:${n.midi}`, n]));
  for (const row of osmd.GraphicSheet.MeasureList)
    for (const gm of row) {
      if (!gm || gm.ParentStaff?.ParentInstrument !== inst) continue;
      const top = gm.PositionAndShape.AbsolutePosition.y;
      for (const se of gm.staffEntries)
        for (const gve of se.graphicalVoiceEntries)
          for (const gn of gve.notes) {
            const sn = gn.sourceNote;
            if (!sn || sn.isRest() || !sn.Pitch) continue;
            const beat = Math.round(sn.getAbsoluteTimestamp().RealValue * 4000);
            const n = byBeat.get(`${beat}:${sn.halfTone + 12}`);
            if (!n) continue; // a tied continuation or a grace note
            const p = gn.PositionAndShape.AbsolutePosition;
            const key = noteKey(score.partId, n, transposed);
            if (!places.has(key)) places.set(key, { key, x: ox + p.x * unit, y: oy + p.y * unit, top: oy + top * unit, unit });
          }
    }
  return places;
}

/** The note nearest to a tap at (x, y), if one is close enough. */
export function nearestNote(places: Map<string, NotePlace>, x: number, y: number): NotePlace | null {
  let best: NotePlace | null = null;
  let bestD = Infinity;
  for (const p of places.values()) {
    const d = Math.hypot((p.x + 0.6 * p.unit - x) * 1.4, p.y - y); // notes sit closer side by side than up and down
    if (d < bestD) [best, bestD] = [p, d];
  }
  return best && bestD < Math.max(28, 4 * best.unit) ? best : null;
}

/** Replaces the marks layer inside `container`. Marks stack above the staff, nearest the note first. */
export function drawMarks(container: HTMLElement, places: Map<string, NotePlace>, marks: Map<string, Mark[]>, selected?: string | null): void {
  let layer = container.querySelector<HTMLElement>(":scope > .marks-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "marks-layer";
    layer.setAttribute("aria-hidden", "true");
    container.append(layer);
  }
  const out: HTMLElement[] = [];
  const add = (cls: string, x: number, y: number, text = "", size = 0): HTMLElement => {
    const e = document.createElement("span");
    e.className = cls;
    e.style.left = `${x}px`;
    e.style.top = `${y}px`;
    if (size) e.style.fontSize = `${size}px`;
    e.textContent = text;
    out.push(e);
    return e;
  };
  for (const [key, list] of marks) {
    const p = places.get(key);
    if (!p) continue;
    const cx = p.x + 0.5 * p.unit;
    const size = Math.max(12, 1.5 * p.unit);
    if (list.some((m) => m.kind === "highlight")) {
      const r = 1.3 * p.unit;
      const ring = add("mark-ring", cx - r, p.y - r);
      ring.style.width = ring.style.height = `${2 * r}px`;
    }
    let y = Math.min(p.top, p.y - p.unit) - 0.6 * size;
    for (const kind of STACK)
      for (const m of list.filter((x) => x.kind === kind)) {
        add(`mark mark-${kind}`, cx, y, glyph(m), kind === "text" ? size * 0.85 : size);
        y -= size * 1.05;
      }
  }
  if (selected) {
    const p = places.get(selected);
    if (p) {
      const r = 1.6 * p.unit;
      const sel = add("mark-selected", p.x + 0.5 * p.unit - r, p.y - r);
      sel.style.width = sel.style.height = `${2 * r}px`;
    }
  }
  layer.replaceChildren(...out);
}
