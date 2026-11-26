import { describe, expect, it } from "vitest";
import { guardRenderer, skippedNote, takeSkipped } from "../src/core/osmd-safety";

describe("renderer guards", () => {
  it("leaves out a slur the renderer can't place, instead of failing the whole score", () => {
    class GraphicalSlur {
      staffEntries: unknown[] = [];
      calculateCurve(): void {
        throw new TypeError("Cannot read properties of undefined (reading 'findGraphicalNoteFromNote')");
      }
    }
    const drawn: unknown[] = [];
    class VexFlowMusicSheetDrawer {
      drawSlur(s: unknown): void {
        drawn.push(s);
      }
    }
    guardRenderer({ GraphicalSlur, VexFlowMusicSheetDrawer });
    const empty = new GraphicalSlur();
    const broken = Object.assign(new GraphicalSlur(), { staffEntries: [1] });
    expect(() => empty.calculateCurve()).not.toThrow();
    expect(() => broken.calculateCurve()).not.toThrow();
    expect(takeSkipped()).toEqual({ slurs: 2, octaveLines: 0 });
    expect(takeSkipped()).toEqual({ slurs: 0, octaveLines: 0 });
    const d = new VexFlowMusicSheetDrawer();
    d.drawSlur(empty);
    d.drawSlur(Object.assign(new GraphicalSlur(), { bezierStartPt: { x: 0, y: 0 } }));
    expect(drawn).toHaveLength(1);
  });

  it("leaves out an octave line that is never stopped", () => {
    const done: number[] = [];
    class VexFlowMusicSheetCalculator {
      calculateSingleOctaveShift(_m: unknown, e: { end?: { realValue: number } }, i: number): void {
        if (e.end!.realValue < 0) return; // reads the missing end, like the renderer does
        done.push(i);
      }
    }
    guardRenderer({ VexFlowMusicSheetCalculator });
    const c = new VexFlowMusicSheetCalculator();
    expect(() => c.calculateSingleOctaveShift(null, {}, 1)).not.toThrow();
    c.calculateSingleOctaveShift(null, { end: { realValue: 1 } }, 2);
    expect(done).toEqual([2]);
    expect(skippedNote()).toBe(" 1 octave line that couldn't be placed was left out.");
    expect(skippedNote()).toBe("");
  });

  it("names everything left out in one sentence", () => {
    class GraphicalSlur {
      staffEntries: unknown[] = [];
      calculateCurve(): void {}
    }
    guardRenderer({ GraphicalSlur });
    new GraphicalSlur().calculateCurve();
    new GraphicalSlur().calculateCurve();
    expect(skippedNote()).toBe(" 2 slurs that couldn't be placed were left out.");
  });
});
