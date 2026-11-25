/** trackPitch in a Web Worker, with progress; falls back to the main thread where workers aren't available. */
import { trackPitch, type PitchTrack } from "./pitch";

let worker: Worker | null = null;
let next = 0;

export function trackPitchAsync(samples: Float32Array, a4: number, onProgress?: (done: number) => void): Promise<PitchTrack> {
  if (typeof Worker === "undefined") return Promise.resolve(trackPitch(samples, a4, onProgress));
  try {
    worker ??= new Worker(new URL("./pitch.worker.ts", import.meta.url), { type: "module" });
  } catch {
    return Promise.resolve(trackPitch(samples, a4, onProgress));
  }
  const w = worker;
  const id = ++next;
  return new Promise((resolve, reject) => {
    const onMessage = (e: MessageEvent<{ id: number; progress?: number; result?: PitchTrack; error?: string }>) => {
      if (e.data.id !== id) return;
      if (e.data.progress !== undefined) return onProgress?.(e.data.progress);
      w.removeEventListener("message", onMessage);
      if (e.data.error) reject(new Error(e.data.error));
      else resolve(e.data.result!);
    };
    w.addEventListener("message", onMessage);
    w.postMessage({ id, samples, a4 });
  });
}
