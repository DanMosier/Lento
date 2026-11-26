/**
 * Tap a note to play from it: finds the beat under a tap on the drawn score, and works out what to play from there.
 *
 * Nothing here runs while the score is just shown. The places are found on the first tap after a render (one pass
 * over the drawn measures) and kept until the score is drawn again.
 */
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";

export interface BeatPlace {
  beat: number; // quarter notes from the start, as in Score.notes
  x: number; // px from the sheet container's top left (including its scroll)
  top: number; // top line of the staff
  bottom: number; // bottom line of the staff
}

/** Where every note and rest of every shown staff sits on the page right now. */
export function beatPlaces(osmd: OpenSheetMusicDisplay, container: HTMLElement): BeatPlace[] {
  const out: BeatPlace[] = [];
  const svg = container.querySelector("svg");
  if (!svg || !osmd.GraphicSheet) return out;
  const unit = 10 * osmd.zoom;
  const c = container.getBoundingClientRect();
  const s = svg.getBoundingClientRect();
  const ox = s.left - c.left + container.scrollLeft;
  const oy = s.top - c.top + container.scrollTop;
  for (const row of osmd.GraphicSheet.MeasureList)
    for (const gm of row) {
      if (!gm?.PositionAndShape) continue;
      const top = oy + gm.PositionAndShape.AbsolutePosition.y * unit;
      const bottom = top + 4 * unit;
      for (const se of gm.staffEntries) {
        const ts = se.getAbsoluteTimestamp?.();
        if (!ts || !se.PositionAndShape) continue;
        out.push({ beat: ts.RealValue * 4, x: ox + se.PositionAndShape.AbsolutePosition.x * unit, top, bottom });
      }
    }
  return out;
}

/**
 * The beat of the note or rest nearest a tap at (x, y): on the staff the tap is on (or near), the one closest
 * side to side. Null when the tap is well away from every staff, e.g. on the title.
 */
export function beatAt(places: BeatPlace[], x: number, y: number): number | null {
  let bestBand = Infinity;
  for (const p of places) {
    const h = p.bottom - p.top;
    const d = y < p.top ? p.top - y : y > p.bottom ? y - p.bottom : 0;
    if (d <= 1.25 * h) bestBand = Math.min(bestBand, d); // ledger lines and marks go a little past the staff
  }
  if (bestBand === Infinity) return null;
  let best: BeatPlace | null = null;
  let bestX = Infinity;
  for (const p of places) {
    const d = y < p.top ? p.top - y : y > p.bottom ? y - p.bottom : 0;
    if (d > bestBand + 1) continue;
    const dx = Math.abs(p.x - x);
    if (dx < bestX) [best, bestX] = [p, dx];
  }
  return best ? best.beat : null;
}

/** The measure a beat falls in. */
export function measureAt(measureStarts: number[], beat: number): number {
  let i = 0;
  while (i + 1 < measureStarts.length && measureStarts[i + 1] <= beat + 1e-6) i++;
  return i;
}

export interface TapPlay {
  fromMeasure: number;
  toMeasure: number;
  fromBeat: number;
  loop: boolean;
}

/**
 * What a tap at `beat` plays. Inside the chosen measures: from the note to the last chosen measure, and if Loop is
 * on, round again from the first chosen measure. Outside them: from the note to the end of the score, once.
 */
export function tapPlay(measureStarts: number[], from: number, to: number, beat: number, loop: boolean): TapPlay {
  const m = measureAt(measureStarts, beat);
  if (m >= from && m <= to) return { fromMeasure: from, toMeasure: to, fromBeat: beat, loop };
  return { fromMeasure: m, toMeasure: measureStarts.length - 1, fromBeat: beat, loop: false };
}
