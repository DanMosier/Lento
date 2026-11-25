import { describe, expect, it } from "vitest";
import type { Analysis, NoteResult, Status } from "../src/practice/analyze";
import { judgePass, SpeedTrainer, type PassSummary } from "../src/practice/trainer";

const pass = (tempo: number, clean: boolean): PassSummary => ({ tempo, graded: 10, good: clean ? 10 : 5, percent: clean ? 100 : 50, dragged: false, clean });

function analysis(statuses: Status[], timing: number[] = [], tempoBpm: number | null = 60): Analysis {
  const results = statuses.map((status, i) => ({ status, timing: timing.includes(i) ? "late" : null }) as unknown as NoteResult);
  return { results, tempoBpm } as unknown as Analysis;
}

describe("speed trainer", () => {
  it("steps up after clean passes and finishes at the target", () => {
    const t = new SpeedTrainer({ start: 80, target: 90, step: 5, need: 90 });
    expect(t.next(pass(80, true))).toBe("up");
    expect(t.tempo).toBe(85);
    expect(t.next(pass(85, true))).toBe("up");
    expect(t.tempo).toBe(90);
    expect(t.next(pass(90, true))).toBe("done");
    expect(t.best).toBe(90);
  });

  it("keeps the tempo after one bad pass and steps back after two, never below the start", () => {
    const t = new SpeedTrainer({ start: 60, target: 100, step: 10, need: 90 });
    t.next(pass(60, true));
    expect(t.next(pass(70, false))).toBe("same");
    expect(t.next(pass(70, false))).toBe("down");
    expect(t.tempo).toBe(60);
    t.next(pass(60, false));
    expect(t.next(pass(60, false))).toBe("same");
    expect(t.tempo).toBe(60);
  });

  it("judges a pass by right notes, timing and keeping up", () => {
    const ok: Status[] = ["in_tune", "in_tune", "slightly_off", "in_tune", "in_tune", "in_tune", "in_tune", "in_tune", "in_tune", "missed"];
    expect(judgePass(analysis(ok), 70, 60, 90)).toMatchObject({ percent: 90, clean: true });
    expect(judgePass(analysis(ok, [0]), 70, 60, 90)).toMatchObject({ percent: 80, clean: false }); // one late note
    expect(judgePass(analysis(ok, [], 50), 70, 60, 90)).toMatchObject({ dragged: true, clean: false }); // fell behind
    expect(judgePass(analysis([...ok, "not_played", "double_stop"]), 70, 60, 90).graded).toBe(10);
  });
});
