/**
 * Guards around two spots where the score renderer (OpenSheetMusicDisplay) can throw on an imperfect file, as
 * converter output sometimes is: a slur whose notes it can't place on a line throws while laying the score out, and
 * the whole score then stays blank (playback still works, since that reads the file itself). Such a slur is left
 * out instead; everything else draws.
 */
type Proto = Record<string, unknown> & { __lentoSafe?: boolean };

let skipped = 0;

/** How many slurs were left out since the last call. */
export function takeSkippedSlurs(): number {
  const n = skipped;
  skipped = 0;
  return n;
}

export function guardRenderer(osmdModule: Record<string, unknown>): void {
  const slur = (osmdModule.GraphicalSlur as { prototype?: Proto } | undefined)?.prototype;
  if (slur && !slur.__lentoSafe && typeof slur.calculateCurve === "function") {
    const calculate = slur.calculateCurve as (this: { staffEntries?: unknown[] }, rules: unknown) => void;
    slur.calculateCurve = function (this: { staffEntries?: unknown[]; lentoSkip?: boolean }, rules: unknown) {
      if (!this.staffEntries?.length) {
        this.lentoSkip = true;
        skipped++;
        return;
      }
      try {
        calculate.call(this, rules);
      } catch {
        this.lentoSkip = true;
        skipped++;
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
}
