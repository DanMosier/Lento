/**
 * The speed trainer: loop a passage, listen to each pass, and raise the tempo a step after each clean one, up to a
 * target. A pass with mistakes keeps the tempo; two in a row step it back. No page or audio code here.
 */
import type { Analysis, Status } from "./analyze";

export interface TrainerConfig {
  start: number; // percent of the written tempo
  target: number;
  step: number;
  need: number; // percent of notes that must be right for a clean pass
}

export const DEFAULT_TRAINER: TrainerConfig = { start: 60, target: 100, step: 5, need: 90 };

export interface PassSummary {
  tempo: number; // percent this pass was played at
  graded: number;
  good: number; // in tune (or slightly off) and on time
  percent: number;
  dragged: boolean; // played well below the set tempo
  clean: boolean;
}

const UNGRADED: Status[] = ["not_played", "double_stop", "score_suspect"];

/** How one pass went. `setBpm` is the tempo it was played at (quarter notes a minute). */
export function judgePass(a: Analysis, tempo: number, setBpm: number, need: number): PassSummary {
  const graded = a.results.filter((r) => !UNGRADED.includes(r.status));
  const good = graded.filter((r) => (r.status === "in_tune" || r.status === "slightly_off") && !r.timing).length;
  const percent = graded.length ? Math.round((100 * good) / graded.length) : 0;
  const dragged = a.tempoBpm !== null && a.tempoBpm < 0.9 * setBpm;
  return { tempo, graded: graded.length, good, percent, dragged, clean: graded.length > 0 && percent >= need && !dragged };
}

export type Verdict = "up" | "same" | "down" | "done";

export class SpeedTrainer {
  tempo: number;
  passes: PassSummary[] = [];
  private misses = 0;

  constructor(readonly cfg: TrainerConfig) {
    this.tempo = Math.min(cfg.start, cfg.target);
  }

  /** The fastest clean pass so far, or null. */
  get best(): number | null {
    const clean = this.passes.filter((p) => p.clean).map((p) => p.tempo);
    return clean.length ? Math.max(...clean) : null;
  }

  /** Records a pass and sets the tempo for the next one. */
  next(p: PassSummary): Verdict {
    this.passes.push(p);
    if (p.clean) {
      this.misses = 0;
      if (this.tempo >= this.cfg.target) return "done";
      this.tempo = Math.min(this.cfg.target, this.tempo + this.cfg.step);
      return "up";
    }
    if (++this.misses < 2) return "same";
    this.misses = 0;
    const lower = Math.max(Math.min(this.cfg.start, this.cfg.target), this.tempo - this.cfg.step);
    if (lower === this.tempo) return "same";
    this.tempo = lower;
    return "down";
  }
}
