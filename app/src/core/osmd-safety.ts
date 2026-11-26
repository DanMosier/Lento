/**
 * Guards around spots where the score renderer (OpenSheetMusicDisplay) can throw on an imperfect file, as converter
 * output sometimes is. Without them the whole score stays blank:
 * - a slur whose notes it can't place on a line throws while laying the score out;
 * - an octave line (8va / 8vb) that is started but never stopped throws when it looks for the line's end.
 * Such a mark is left out instead; everything else draws. Shared by Practice and the Convert PDF Review window.
 */
type Proto = Record<string, unknown> & { __lentoSafe?: boolean };

let skippedSlurs = 0;
let skippedOctaveLines = 0;

/** How many marks were left out since the last call. */
export function takeSkipped(): { slurs: number; octaveLines: number } {
  const n = { slurs: skippedSlurs, octaveLines: skippedOctaveLines };
  skippedSlurs = skippedOctaveLines = 0;
  return n;
}

/** A sentence saying what was left out since the last call ("" when nothing was), starting with a space. */
export function skippedNote(): string {
  const { slurs, octaveLines } = takeSkipped();
  const what = [slurs ? `${slurs} slur${slurs > 1 ? "s" : ""}` : "", octaveLines ? `${octaveLines} octave line${octaveLines > 1 ? "s" : ""}` : ""].filter(Boolean);
  if (!what.length) return "";
  const many = slurs + octaveLines > 1;
  return ` ${what.join(" and ")} that couldn't be placed ${many ? "were" : "was"} left out.`;
}

export function guardRenderer(osmdModule: Record<string, unknown>): void {
  const slur = (osmdModule.GraphicalSlur as { prototype?: Proto } | undefined)?.prototype;
  if (slur && !slur.__lentoSafe && typeof slur.calculateCurve === "function") {
    const calculate = slur.calculateCurve as (this: { staffEntries?: unknown[] }, rules: unknown) => void;
    slur.calculateCurve = function (this: { staffEntries?: unknown[]; lentoSkip?: boolean }, rules: unknown) {
      if (!this.staffEntries?.length) {
        this.lentoSkip = true;
        skippedSlurs++;
        return;
      }
      try {
        calculate.call(this, rules);
      } catch {
        this.lentoSkip = true;
        skippedSlurs++;
      }
    };
    slur.__lentoSafe = true;
  }
  const drawer = (osmdModule.VexFlowMusicSheetDrawer as { prototype?: Proto } | undefined)?.prototype;
  if (drawer && !drawer.__lentoSafe && typeof drawer.drawSlur === "function") {
    const draw = drawer.drawSlur as (this: unknown, s: { lentoSkip?: boolean; bezierStartPt?: unknown }, at: unknown) => void;
    drawer.drawSlur = function (this: unknown, s: { lentoSkip?: boolean; bezierStartPt?: unknown }, at: unknown) {
      if (s?.lentoSkip || !s?.bezierStartPt) return;
      draw.call(this, s, at);
    };
    drawer.__lentoSafe = true;
  }
  // With no end, this throws while looking for the line's last note, before anything is added to the staff, so
  // nothing half-made is left behind.
  const calc = (osmdModule.VexFlowMusicSheetCalculator as { prototype?: Proto } | undefined)?.prototype;
  if (calc && !calc.__lentoSafe && typeof calc.calculateSingleOctaveShift === "function") {
    const octave = calc.calculateSingleOctaveShift as (this: unknown, ...a: unknown[]) => void;
    calc.calculateSingleOctaveShift = function (this: unknown, ...a: unknown[]) {
      try {
        octave.apply(this, a);
      } catch {
        skippedOctaveLines++;
      }
    };
    calc.__lentoSafe = true;
  }
}
