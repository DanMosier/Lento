/**
 * How big to draw the score for the space it has. On a phone held upright the renderer's normal size fits only one
 * or two measures on a line, so the notes come out huge and every line breaks after a bar or two. Shrinking the
 * whole page a little fits several measures per line and keeps the spacing between notes natural.
 */

/** "auto", or a fixed percentage of the renderer's normal size. */
export type ScoreSize = "auto" | number;

export const SCORE_SIZES: readonly ScoreSize[] = ["auto", 50, 60, 70, 80, 90, 100, 120];

/** Narrower than this (in CSS pixels) counts as a phone: smaller margins, no part name for a single part. */
export const NARROW = 700;

/** The width at which the normal size (100%) is used; narrower screens draw the score proportionally smaller. */
const FULL_SIZE_WIDTH = 760;
const SMALLEST_AUTO = 0.6;
/** A phone on its side is wide but very short; a little smaller fits another line of music on the screen. */
const LARGEST_ON_PHONE = 0.8;

/**
 * The renderer zoom for a score area `width` CSS pixels wide. `phone` is true on a small screen whichever way it
 * is held (decided from the screen, not the window, so the address bar sliding away never changes it).
 */
export function fitZoom(width: number, size: ScoreSize = "auto", phone = false): number {
  if (size !== "auto") return size / 100;
  if (!(width > 0)) return 1;
  const largest = phone ? LARGEST_ON_PHONE : 1;
  return Math.round(Math.min(largest, Math.max(SMALLEST_AUTO, width / FULL_SIZE_WIDTH)) * 100) / 100;
}

/** Is this a phone-sized screen? (Its short side is under 500 CSS pixels.) */
export function phoneScreen(s: { width: number; height: number } = screen): boolean {
  return Math.min(s.width, s.height) < 500;
}

export interface PageLayout {
  zoom: number;
  /** Left and right page margins, in the renderer's units (10 px at 100%). */
  margin: number;
  partNames: boolean;
}

/** Everything about the page that depends on its width. */
export function pageLayout(width: number, size: ScoreSize, partsShown: number, phone = false): PageLayout {
  const narrow = width > 0 && width < NARROW;
  return { zoom: fitZoom(width, size, phone), margin: narrow ? 2 : 5, partNames: !(narrow && partsShown < 2) };
}

/** Reads a saved size, falling back to "auto" for anything unexpected. */
export function parseScoreSize(v: unknown): ScoreSize {
  if (v === "auto" || v === null || v === undefined) return "auto";
  const n = Number(v);
  return SCORE_SIZES.includes(n) ? n : "auto";
}
