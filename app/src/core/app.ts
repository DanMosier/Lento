/** Small helpers every feature may use: element lookup, saved settings, and one shared AudioContext. */

export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export const store = {
  get<T>(key: string): T | null {
    try {
      const v = localStorage.getItem(`lento.${key}`);
      return v ? (JSON.parse(v) as T) : null;
    } catch {
      return null;
    }
  },
  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(`lento.${key}`, JSON.stringify(value));
    } catch {
      /* storage full or blocked: not essential */
    }
  },
};

let ctx: AudioContext | null = null;

/** Browsers allow only a few AudioContexts, so features share one. Create it from a click. */
export function sharedAudio(): AudioContext {
  if (!ctx) ctx = new AudioContext({ latencyHint: "interactive" });
  return ctx;
}

/**
 * Handing a score from one feature to another without importing it: the Library asks for a score to be opened,
 * and whoever practises listens. The app shell also listens, to switch to that tab.
 */
export interface OpenScoreRequest {
  name: string;
  data: ArrayBuffer;
}
const OPEN_SCORE = "lento:open-score";

export function requestOpenScore(req: OpenScoreRequest): void {
  window.dispatchEvent(new CustomEvent<OpenScoreRequest>(OPEN_SCORE, { detail: req }));
}

export function onOpenScore(handler: (req: OpenScoreRequest) => void): void {
  window.addEventListener(OPEN_SCORE, (e) => handler((e as CustomEvent<OpenScoreRequest>).detail));
}
