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
