/**
 * Where favorites and setlists live: on this device at once (so a tap never waits for the network), and in the
 * library folder in Drive a moment later, which is how the phone and the PC share them. See lists.ts for merging.
 */
import { store } from "../core/app";
import { auth, library } from "../core/library/connection";
import { LISTS_FILE, mergeLists, parseLists, sameLists, type Lists } from "./lists";

const KEY = "library.lists";
const PENDING = "library.lists.pending"; // changes made here that Drive hasn't got yet

let lists: Lists = parseLists(store.get(KEY));
const listeners = new Set<() => void>();
let pushTimer = 0;
let running: Promise<void> = Promise.resolve();

export type SyncState = "device" | "syncing" | "synced" | "waiting";
let state: SyncState = store.get<boolean>(PENDING) ? "waiting" : "device";

export const currentLists = (): Lists => lists;
export const syncState = (): SyncState => state;

/** Called after every change, from this device or another. */
export function onListsChanged(fn: () => void): void {
  listeners.add(fn);
}

function notify(): void {
  for (const fn of listeners) fn();
}

function keep(next: Lists): void {
  lists = next;
  store.set(KEY, lists);
}

/** Applies a change here now, and sends it to Drive a moment later (so a run of taps is one upload). */
export function changeLists(fn: (l: Lists) => Lists): void {
  const next = fn(lists);
  if (next === lists) return;
  keep(next);
  store.set(PENDING, true);
  state = "waiting";
  notify();
  clearTimeout(pushTimer);
  pushTimer = window.setTimeout(() => void syncLists(false), 1500);
}

/**
 * Fetches the library's copy, merges it with this device's, and uploads the result if it differs. Without a click
 * it runs only while already signed in, so it never opens Google's sign-in window by itself; changes made offline
 * or signed out wait for the next Refresh.
 */
export function syncLists(fromClick: boolean): Promise<void> {
  running = running.then(() => syncNow(fromClick));
  return running;
}

async function syncNow(fromClick: boolean): Promise<void> {
  const lib = library();
  if (!lib || (!fromClick && !auth.signedIn)) return;
  const before = state;
  state = "syncing";
  try {
    const remote = parseLists(await lib.readRootJson(LISTS_FILE));
    const merged = mergeLists(lists, remote);
    const changedHere = !sameLists(merged, lists);
    if (changedHere) keep(merged);
    const sent = lists;
    if (!sameLists(sent, remote)) await lib.writeRootJson(LISTS_FILE, sent);
    if (sent === lists) store.set(PENDING, false); // nothing new arrived while uploading
    state = store.get<boolean>(PENDING) ? "waiting" : "synced";
    if (changedHere || before !== state) notify();
  } catch {
    state = store.get<boolean>(PENDING) ? "waiting" : before;
    notify();
  }
}

/** A line for the screen saying where the lists are saved. */
export function syncNote(): string {
  switch (state) {
    case "syncing":
      return "Syncing with your library…";
    case "synced":
      return "Saved to your library in Google Drive, so your other devices see it.";
    case "waiting":
      return "Saved on this device. It goes to Google Drive the next time the library is online (or press Refresh).";
    default:
      return "Saved on this device.";
  }
}
