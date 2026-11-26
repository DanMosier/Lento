/**
 * Your own windows for judging notes, set in Settings and used by Practice when its Pitch or Timing menu is on
 * "Custom". Kept in core because two features share them, and features don't import each other.
 */
import { store } from "./app";

export interface PitchWindow {
  /** Cents either side that still count as in tune. */
  good: number;
  /** Cents either side that count as slightly off; further out is out of tune. */
  ok: number;
}

export const PITCH_LIMITS = { min: 1, max: 50 };
export const OK_LIMIT = 60; // past 70 cents a note is taken for a different note, so "slightly off" stops short of it
export const TIMING_LIMITS = { min: 20, max: 400 };
export const DEFAULT_PITCH: PitchWindow = { good: 10, ok: 25 };
export const DEFAULT_TIMING = 100;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** A pitch window made sensible: whole cents, in range, and "slightly off" wider than "in tune". */
export function cleanPitch(w: Partial<PitchWindow> | null | undefined): PitchWindow {
  const good = clamp(Math.round(Number(w?.good) || DEFAULT_PITCH.good), PITCH_LIMITS.min, PITCH_LIMITS.max);
  const ok = clamp(Math.round(Number(w?.ok) || DEFAULT_PITCH.ok), good + 1, OK_LIMIT);
  return { good, ok };
}

export function cleanTiming(ms: unknown): number {
  return clamp(Math.round(Number(ms) || DEFAULT_TIMING), TIMING_LIMITS.min, TIMING_LIMITS.max);
}

export const customPitch = (): PitchWindow => cleanPitch(store.get<PitchWindow>("pitchCustom"));
export const customTiming = (): number => cleanTiming(store.get<number>("timingCustom"));

/** Saves the window and switches Practice's Pitch menu to Custom, since that's what changing it means. */
export function saveCustomPitch(w: Partial<PitchWindow>): PitchWindow {
  const v = cleanPitch(w);
  store.set("pitchCustom", v);
  store.set("pitch", "custom");
  return v;
}

export function saveCustomTiming(ms: unknown): number {
  const v = cleanTiming(ms);
  store.set("timingCustom", v);
  store.set("timing", "custom");
  return v;
}
