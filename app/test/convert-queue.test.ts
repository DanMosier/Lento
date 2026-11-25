import { describe, expect, it } from "vitest";
import { buildQueue, duration, namesOf } from "../src/convert/queue";
import { pcOnline, type LibraryIndex, type PcStatus } from "../src/core/library/model";

const pdf = (id: string, extra = {}) => ({ name: `${id}__imslp.pdf`, kind: "pdf" as const, variant: "imslp", ...extra });
const INDEX: LibraryIndex = {
  format: "lento-library",
  version: 1,
  generated: "",
  pieces: [
    { id: "a", title: "Elegie", composer: "Fauré", files: [pdf("a", { requested: true })] },
    { id: "b", title: "The Swan", composer: "Saint-Saëns", files: [pdf("b", { requested: true })] },
    { id: "c", title: "Prelude", composer: "Bach", files: [pdf("c", { requested: true })] },
    { id: "d", title: "Late one", composer: "Popper", files: [pdf("d")] },
    { id: "e", title: "Done", composer: "Davidov", files: [pdf("e", { musicxml: "e__imslp.musicxml" })] },
  ],
};
const NOW = Date.parse("2026-11-25T12:00:00Z");
const status = (over: Partial<PcStatus> = {}): PcStatus => ({
  pc: "PC",
  state: "converting",
  heartbeat: "2026-11-25T11:59:55Z",
  interval_s: 30,
  queue: ["b__imslp.pdf", "c__imslp.pdf"],
  current: "a__imslp.pdf",
  current_files: ["a__imslp.pdf"],
  started: "2026-11-25T11:59:00Z",
  batch: { total: 4, done: 1, started: "2026-11-25T11:50:00Z" },
  avg_s: 240,
  results: [{ pdf: "x__imslp.pdf", ok: true, at: "2026-11-25T11:58:00Z", seconds: 230 }],
  ...over,
});

describe("convert queue", () => {
  it("shows what's converting, what's next in order, and how far the batch is", () => {
    const v = buildQueue(status(), INDEX, namesOf(INDEX), new Set(["convert__d__imslp.json"]), NOW);
    expect(v.now).toHaveLength(1);
    expect(v.now[0]).toMatchObject({ title: "Elegie", sub: "Fauré · imslp", elapsed_s: 60, left_s: 180 });
    expect(v.now[0].fraction).toBeCloseTo(0.25);
    expect(v.next.map((i) => i.title)).toEqual(["The Swan", "Prelude"]);
    expect(v.pickup.map((i) => i.title)).toEqual(["Late one"]); // queued here after the batch started
    expect(v.batch).toEqual({ done: 1, total: 4, left_s: 180 + 2 * 240 });
    expect(v.recent[0]).toMatchObject({ title: "x__imslp", ok: true, seconds: 230 }); // unknown names keep the file name
  });

  it("caps the estimate and has none before any timings", () => {
    const slow = buildQueue(status({ started: "2026-11-25T11:00:00Z" }), INDEX, namesOf(INDEX), new Set(), NOW);
    expect(slow.now[0].fraction).toBe(0.95);
    expect(slow.now[0].left_s).toBe(0);
    const fresh = buildQueue(status({ avg_s: null }), INDEX, namesOf(INDEX), new Set(), NOW);
    expect(fresh.now[0].fraction).toBeNull();
    expect(fresh.batch?.left_s).toBeNull();
  });

  it("when idle, everything asked for is waiting for the PC, except what just converted", () => {
    const s = status({ state: "idle", queue: [], current: null, current_files: undefined, batch: undefined, results: [{ pdf: "a__imslp.pdf", ok: true, at: "2026-11-25T11:58:00Z" }] });
    const v = buildQueue(s, INDEX, namesOf(INDEX), new Set(), NOW);
    expect(v.now).toEqual([]);
    expect(v.next).toEqual([]);
    expect(v.batch).toBeNull();
    expect(v.pickup.map((i) => i.title)).toEqual(["The Swan", "Prelude"]);
  });

  it("reads an older watcher's status (no current_files)", () => {
    const v = buildQueue(status({ current_files: undefined, avg_s: undefined, batch: undefined, current: "a__imslp.pdf, b__imslp.pdf" }), INDEX, namesOf(INDEX), new Set(), NOW);
    expect(v.now.map((i) => i.title)).toEqual(["Elegie", "The Swan"]);
    expect(v.now[1].elapsed_s).toBe(0);
  });

  it("a newer watcher's heartbeat goes stale quickly even while converting; an older one gets an hour", () => {
    const later = NOW + 20 * 60_000;
    expect(pcOnline(status(), later)).toBe(false);
    expect(pcOnline(status({ batch: undefined }), later)).toBe(true);
  });

  it("formats durations", () => {
    expect(duration(20)).toBe("under a minute");
    expect(duration(240)).toBe("about 4 min");
    expect(duration(4800)).toBe("about 1 h 20 min");
  });

  it("hides what was removed on this device until the PC catches up", () => {
    const v = buildQueue(status(), INDEX, namesOf(INDEX), new Set(["convert__d__imslp.json"]), NOW, new Set(["c__imslp.pdf", "d__imslp.pdf"]));
    expect(v.next.map((i) => i.title)).toEqual(["The Swan"]);
    expect(v.pickup).toEqual([]);
  });
});
