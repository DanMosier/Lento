/**
 * The one connection to the score library in Google Drive, shared by the Library, Convert and Settings screens.
 * Settings writes the folder link and client ID; the others just ask for `library()`.
 */
import { store } from "../app";
import { GoogleAuth } from "./auth";
import { Drive, IdbCache } from "./drive";
import { DriveLibrary } from "./library";
import { folderIdFromLink } from "./model";

export const auth = new GoogleAuth();
export const cache = new IdbCache();
let current: DriveLibrary | null = null;

export const libraryFolder = (): string => store.get<string>("library.folder") ?? "";
/**
 * The app's Google client ID (from Google Cloud, made for this app's address). It isn't a secret: it only names the
 * app to Google, and works only from the app's own address. A repository variable or Settings can override it.
 */
const BUILT_IN_CLIENT = "58187739726-bc8b69ursjooua6j28dqbt22rn0bb12i.apps.googleusercontent.com";
export const clientId = (): string =>
  store.get<string>("library.client") || (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) || BUILT_IN_CLIENT;

export function saveConnection(folder: string, client: string): void {
  store.set("library.folder", folder.trim());
  store.set("library.client", client.trim());
}

/** The library, or null until a folder has been set in Settings. */
export function library(): DriveLibrary | null {
  const id = folderIdFromLink(libraryFolder());
  if (!id) return null;
  if (current?.rootId !== id) current = new DriveLibrary(id, new Drive((fresh) => auth.getToken(clientId(), fresh)), cache);
  return current;
}

/**
 * Finds the library in the user's Drive by itself, so a new device needs nothing typed in: the folder holding a
 * library.json beside a pieces/ folder (the newest, if there are several). Signs in first if needed, so call it from
 * a click. Saves the folder on this device only and returns its ID, or null if there is no library.json anywhere.
 */
export async function findLibrary(drive = new Drive((fresh) => auth.getToken(clientId(), fresh))): Promise<string | null> {
  const found = (await drive.find("library.json")).filter((f) => f.parents?.length);
  let pick: string | null = null;
  for (const f of found) {
    if (await drive.child(f.parents![0], "pieces")) {
      pick = f.parents![0];
      break;
    }
  }
  pick ??= found[0]?.parents?.[0] ?? null;
  if (pick) store.set("library.folder", `https://drive.google.com/drive/folders/${pick}`);
  return pick;
}

/** Requests made from this device that the index doesn't show yet (Drive's index updates only when the PC rebuilds it). */
export const requestedHere = {
  all: (): Set<string> => new Set(store.get<string[]>("library.requested") ?? []),
  save: (s: Set<string>): void => store.set("library.requested", [...s]),
};

/** Reviews made on this device (score name -> "approved" or "rejected") that the index doesn't show yet. */
export const reviewedHere = {
  all: (): Record<string, string> => store.get<Record<string, string>>("library.reviewed") ?? {},
  save: (r: Record<string, string>): void => store.set("library.reviewed", r),
};

/** Tell open screens that the library index changed, so they redraw. */
const CHANGED = "lento:library-changed";
export const libraryChanged = (): boolean => window.dispatchEvent(new Event(CHANGED));
export const onLibraryChanged = (fn: () => void): void => window.addEventListener(CHANGED, fn);
