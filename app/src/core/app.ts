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
  pieceId?: string; // set when the score comes from the Drive library, so things saved about it can go beside it
}
const OPEN_SCORE = "lento:open-score";

let pending: OpenScoreRequest | null = null; // kept until Practice takes it: its code may still be loading

export function requestOpenScore(req: OpenScoreRequest): void {
  pending = req;
  window.dispatchEvent(new CustomEvent<OpenScoreRequest>(OPEN_SCORE, { detail: req }));
}

/**
 * For the feature that opens scores: handles each request, including one made before its code had loaded.
 * (Plain listeners, like the app shell's, use onOpenScore.)
 */
export function takeOpenScore(handler: (req: OpenScoreRequest) => void): void {
  const take = (req: OpenScoreRequest) => {
    if (pending !== req) return;
    pending = null;
    handler(req);
  };
  window.addEventListener(OPEN_SCORE, (e) => take((e as CustomEvent<OpenScoreRequest>).detail));
  queueMicrotask(() => pending && take(pending)); // after the caller's module has finished setting up

}

export function onOpenScore(handler: (req: OpenScoreRequest) => void): void {
  window.addEventListener(OPEN_SCORE, (e) => handler((e as CustomEvent<OpenScoreRequest>).detail));
}
