/**
 * A short log of what went wrong on this device: errors, and moments when the page froze for over a second (with
 * what the app was doing then). Settings shows it, so a problem on a phone can be read off the screen. Kept in
 * local storage, last 20 entries.
 */
import { store } from "./app";
import { VERSION } from "./version";

export interface Problem {
  at: string; // ISO time
  kind: "error" | "freeze";
  text: string;
  version: string;
}

const KEY = "problems";
const MAX = 20;

export function problems(): Problem[] {
  return store.get<Problem[]>(KEY) ?? [];
}

export function clearProblems(): void {
  store.set(KEY, []);
}

export function note(kind: Problem["kind"], text: string): void {
  const list = problems();
  list.push({ at: new Date().toISOString(), kind, text: text.slice(0, 300), version: VERSION.commit });
  store.set(KEY, list.slice(-MAX));
}

/** What the app was timing (lento:* measures) during [start, end], longest first. */
function busyWith(start: number, end: number): string {
  const names = performance
    .getEntriesByType("measure")
    .filter((m) => m.name.startsWith("lento:") && m.startTime < end && m.startTime + m.duration > start)
    .sort((a, b) => b.duration - a.duration)
    .map((m) => m.name.slice(6));
  return [...new Set(names)].slice(0, 3).join(", ");
}

/** Starts listening. Cheap: the browser reports long tasks itself; nothing runs in between. */
export function watchProblems(): void {
  window.addEventListener("error", (e) => note("error", e.message || String(e.error)));
  window.addEventListener("unhandledrejection", (e) => note("error", String((e.reason as Error)?.message ?? e.reason)));
  try {
    new PerformanceObserver((list) => {
      for (const t of list.getEntries()) {
        if (t.duration < 1000) continue;
        const what = busyWith(t.startTime, t.startTime + t.duration);
        note("freeze", `Froze ${(t.duration / 1000).toFixed(1)} s on ${location.hash.slice(1) || "home"}${what ? ` during ${what}` : ""}${document.hidden ? " (in the background)" : ""}`);
      }
    }).observe({ type: "longtask" });
  } catch {
    /* long tasks aren't reported in this browser */
  }
}
