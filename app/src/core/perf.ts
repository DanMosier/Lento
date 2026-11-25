/**
 * Timing marks for the performance tests (app/perf/). They cost nothing noticeable, and the browser's
 * Performance panel shows them too. Names start with "lento:".
 */
export async function timed<T>(name: string, fn: () => Promise<T> | T): Promise<T> {
  const start = performance.now();
  try {
    return await fn();
  } finally {
    try {
      performance.measure(`lento:${name}`, { start, end: performance.now() });
    } catch {
      /* measure() with options is missing in very old browsers: timing is optional */
    }
  }
}

export function mark(name: string): void {
  try {
    performance.mark(`lento:${name}`);
  } catch {
    /* optional */
  }
}
