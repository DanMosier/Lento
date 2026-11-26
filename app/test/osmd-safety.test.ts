import { describe, expect, it } from "vitest";
import { guardRenderer, takeSkippedSlurs } from "../src/practice/osmd-safety";

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
    expect(takeSkippedSlurs()).toBe(2);
    expect(takeSkippedSlurs()).toBe(0);
    const d = new VexFlowMusicSheetDrawer();
    d.drawSlur(empty);
    d.drawSlur(Object.assign(new GraphicalSlur(), { bezierStartPt: { x: 0, y: 0 } }));
    expect(drawn).toHaveLength(1);
  });
});
