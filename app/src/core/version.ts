/**
 * Which version of the app this is, and whether a newer one has been published. GitHub Pages replaces the whole
 * site on each update, so a copy of the app left open in the background can be running old code whose remaining
 * pieces are gone from the server; it should reload rather than half work.
 */
declare const __LENTO_COMMIT__: string;
declare const __LENTO_BUILT__: string;

export const VERSION = {
  commit: typeof __LENTO_COMMIT__ === "string" ? __LENTO_COMMIT__ : "dev",
  built: typeof __LENTO_BUILT__ === "string" ? __LENTO_BUILT__ : "",
};

/** "a1b2c3d, Nov 26, 9:55 PM" in the device's own time. */
export function versionLabel(v = VERSION): string {
  if (!v.built) return v.commit;
  const d = new Date(v.built);
  return `${v.commit}, ${d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
}

/** The published version, or null when offline or in development. */
export async function publishedVersion(): Promise<{ commit: string; built: string } | null> {
  try {
    const r = await fetch(`version.json?t=${Date.now()}`, { cache: "no-store" }); // past every cache, the CDN's too
    if (!r.ok) return null;
    const v = await r.json();
    return typeof v?.commit === "string" ? v : null;
  } catch {
    return null;
  }
}

/** The published version's commit when it differs from this one, else null (also offline or in development). */
export async function newerVersion(): Promise<string | null> {
  if (VERSION.commit === "dev") return null;
  const v = await publishedVersion();
  return v && v.commit !== VERSION.commit ? v.commit : null;
}

/**
 * Reloads into the newest version. The app's offline copy (service worker) is told to fetch the update first;
 * otherwise a reload could start the old copy again.
 */
export async function reloadToNewest(): Promise<void> {
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) {
      await reg.update().catch(() => {});
      const sw = reg.installing ?? reg.waiting;
      if (sw && sw.state !== "activated")
        await new Promise<void>((done) => {
          sw.addEventListener("statechange", () => sw.state === "activated" && done());
          setTimeout(done, 10000);
        });
    }
  } catch {
    /* reload anyway */
  }
  location.reload();
}
