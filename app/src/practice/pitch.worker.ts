/// <reference lib="webworker" />
/** Runs pitch tracking off the main thread, so the page stays responsive while a long take is checked. */
import { trackPitch } from "./pitch";

self.onmessage = (e: MessageEvent<{ id: number; samples: Float32Array; a4: number }>) => {
  const { id, samples, a4 } = e.data;
  try {
    const r = trackPitch(samples, a4, (done) => self.postMessage({ id, progress: done }));
    self.postMessage({ id, result: r }, [r.times.buffer, r.midi.buffer, r.rms.buffer, r.onset.buffer]);
  } catch (err) {
    self.postMessage({ id, error: (err as Error).message });
  }
};
