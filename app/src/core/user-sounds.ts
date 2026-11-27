/**
 * Your own sounds, chosen in Settings: a SoundFont file kept on this device, or the MIDI output to send notes to.
 * Small on purpose: Settings uses it, and the synthesizer that plays a SoundFont (core/soundfont) loads only when a
 * score is played with it.
 */
import { store } from "./app";

const CACHE = "lento-soundfont-v1";
const KEY = "soundfont"; // the one SoundFont kept (a new one replaces it)

export interface SoundFontInfo {
  name: string;
  bytes: number;
  stamp: number; // changes each time a new file is chosen, so open players pick it up
}

export function soundFontInfo(): SoundFontInfo | null {
  return store.get<SoundFontInfo>("soundfontInfo") ?? null;
}

/** Looks like a SoundFont 2/3 (RIFF…sfbk) or DLS (RIFF…DLS ) file? */
export async function isSoundFont(file: Blob): Promise<boolean> {
  const head = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  const tag = (a: number) => String.fromCharCode(...head.slice(a, a + 4));
  return head.length === 12 && tag(0) === "RIFF" && (tag(8) === "sfbk" || tag(8) === "DLS ");
}

/** Keeps `file` on this device as the SoundFont to play with. */
export async function saveSoundFont(file: File): Promise<SoundFontInfo> {
  if (!(await isSoundFont(file))) throw new Error("That file isn't a SoundFont (.sf2 or .sf3).");
  const cache = await caches.open(CACHE);
  await cache.put(KEY, new Response(file, { headers: { "content-type": "application/octet-stream" } }));
  // ask the browser not to clear it when space runs low (it may say no; then it's kept as long as space allows)
  void navigator.storage?.persist?.().catch(() => false);
  const info = { name: file.name, bytes: file.size, stamp: Date.now() };
  store.set("soundfontInfo", info);
  return info;
}

export async function loadSoundFont(): Promise<ArrayBuffer | null> {
  try {
    const hit = await (await caches.open(CACHE)).match(KEY);
    return hit ? await hit.arrayBuffer() : null;
  } catch {
    return null;
  }
}

export async function removeSoundFont(): Promise<void> {
  store.set("soundfontInfo", null);
  await caches.delete(CACHE).catch(() => false);
}

/** The MIDI output chosen in Settings (by name, which stays the same between visits), or "" for the first one. */
export function midiOutName(): string {
  return store.get<string>("midiOut") ?? "";
}

export function setMidiOutName(name: string): void {
  store.set("midiOut", name);
}

export function midiSupported(): boolean {
  return typeof navigator !== "undefined" && "requestMIDIAccess" in navigator;
}

/** Megabytes, for showing a file's size. */
export function mb(bytes: number): string {
  return `${(bytes / 1e6).toFixed(bytes < 1e7 ? 1 : 0)} MB`;
}
