/**
 * Where the "to split" list lives: on this device at once (so a tap never waits for the network), and in the library
 * folder in Drive a moment later, which is how the phone and the PC share it. See split-list.ts for merging.
 */
import { store } from "../core/app";
import { auth, library } from "../core/library/connection";
import { SPLIT_FILE, mergeSplit, parseSplit, sameSplit, type SplitList } from "./split-list";

const KEY = "convert.split";
const PENDING = "convert.split.pending"; // changes made here that Drive hasn't got yet

let list: SplitList = parseSplit(store.get(KEY));
const listeners = new Set<() => void>();
let pushTimer = 0;
let running: Promise<void> = Promise.resolve();
let synced = false;

export const currentSplit = (): SplitList => list;

/** Called after every change, from this device or another. */
export function onSplitChanged(fn: () => void): void {
  listeners.add(fn);
}

function notify(): void {
  for (const fn of listeners) fn();
}

function keep(next: SplitList): void {
  list = next;
  store.set(KEY, list);
}

/** Applies a change here now, and sends it to Drive a moment later (so a run of taps is one upload). */
export function changeSplit(fn: (l: SplitList) => SplitList): void {
  const next = fn(list);
  if (next === list) return;
  keep(next);
  store.set(PENDING, true);
  synced = false;
  notify();
  clearTimeout(pushTimer);
  pushTimer = window.setTimeout(() => void syncSplit(false), 1500);
}

/**
 * Fetches the library's copy, merges it with this device's, and uploads the result if it differs. Without a click
 * it runs only while already signed in, so it never opens Google's sign-in window by itself.
 */
export function syncSplit(fromClick: boolean): Promise<void> {
  running = running.then(() => syncNow(fromClick));
  return running;
}

async function syncNow(fromClick: boolean): Promise<void> {
  const lib = library();
  if (!lib || (!fromClick && !auth.signedIn)) return;
  try {
    const remote = parseSplit(await lib.readRootJson(SPLIT_FILE));
    const merged = mergeSplit(list, remote);
    const changedHere = !sameSplit(merged, list);
    if (changedHere) keep(merged);
    const sent = list;
    if (!sameSplit(sent, remote)) await lib.writeRootJson(SPLIT_FILE, sent);
    if (sent === list) store.set(PENDING, false); // nothing new arrived while uploading
    const was = synced;
    synced = !store.get<boolean>(PENDING);
    if (changedHere || was !== synced) notify();
  } catch {
    /* offline or signed out: the change waits on this device for the next sync */
  }
}

/** A line for the screen saying where the list is saved. */
export function splitSyncNote(): string {
  if (synced) return "Saved to your library in Google Drive, so your other devices see it.";
  if (store.get<boolean>(PENDING)) return "Saved on this device. It goes to Google Drive the next time the library is online (or press Refresh).";
  return "Saved on this device.";
}
