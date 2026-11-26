/**
 * Favorites and setlists: the data, and merging two copies of it. Pure functions, so they are tested on their own.
 *
 * Each device keeps a copy and the library keeps one in Drive (lento-lists.json beside library.json). Copies are
 * merged item by item, newest change winning, so starring a piece on the phone and making a setlist on the PC at
 * the same time keeps both. Removals are kept as dated entries (a few bytes each) so they win over an older "add".
 */

export interface Favorite {
  on: boolean;
  at: number; // ms since 1970, when it was starred or unstarred
}

export interface Setlist {
  id: string;
  name: string;
  pieces: string[]; // piece ids, in playing order
  created: number;
  updated: number; // the last change to its name or pieces (or when it was deleted)
  played?: number; // the last time a piece was opened from it
  deleted?: boolean;
}

export interface Lists {
  format: "lento-lists";
  version: 1;
  favorites: Record<string, Favorite>; // piece id -> state
  setlists: Record<string, Setlist>; // setlist id -> setlist
}

export const LISTS_FILE = "lento-lists.json";

export function emptyLists(): Lists {
  return { format: "lento-lists", version: 1, favorites: {}, setlists: {} };
}

/** Accepts anything (a saved copy, Drive's file) and keeps only what makes sense. */
export function parseLists(raw: unknown): Lists {
  const out = emptyLists();
  if (!raw || typeof raw !== "object") return out;
  const r = raw as Partial<Lists>;
  for (const [id, f] of Object.entries(r.favorites ?? {})) {
    if (f && typeof f.at === "number") out.favorites[id] = { on: !!f.on, at: f.at };
  }
  for (const [id, s] of Object.entries(r.setlists ?? {})) {
    if (!s || typeof s.name !== "string" || !Array.isArray(s.pieces) || typeof s.created !== "number") continue;
    out.setlists[id] = {
      id,
      name: s.name,
      pieces: s.pieces.filter((p): p is string => typeof p === "string"),
      created: s.created,
      updated: typeof s.updated === "number" ? s.updated : s.created,
      ...(typeof s.played === "number" ? { played: s.played } : {}),
      ...(s.deleted ? { deleted: true } : {}),
    };
  }
  return out;
}

/** Both copies together: per piece and per setlist the newer change wins; "last played" is the later of the two. */
export function mergeLists(a: Lists, b: Lists): Lists {
  const out = emptyLists();
  for (const id of new Set([...Object.keys(a.favorites), ...Object.keys(b.favorites)])) {
    const x = a.favorites[id];
    const y = b.favorites[id];
    out.favorites[id] = !x ? y : !y ? x : y.at > x.at ? y : x;
  }
  for (const id of new Set([...Object.keys(a.setlists), ...Object.keys(b.setlists)])) {
    const x = a.setlists[id];
    const y = b.setlists[id];
    if (!x || !y) {
      out.setlists[id] = x ?? y;
      continue;
    }
    const win = y.updated > x.updated ? y : x;
    const played = Math.max(x.played ?? 0, y.played ?? 0);
    out.setlists[id] = { ...win, ...(played ? { played } : {}) };
  }
  return out;
}

/** Same contents? (Used to skip an upload when nothing changed.) */
export function sameLists(a: Lists, b: Lists): boolean {
  return JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));
}

function sorted(l: Lists): unknown {
  const keys = (o: object) => Object.keys(o).sort();
  return [keys(l.favorites).map((k) => [k, l.favorites[k]]), keys(l.setlists).map((k) => [k, l.setlists[k]])];
}

// ---- favorites ----

export function isFavorite(l: Lists, pieceId: string): boolean {
  return !!l.favorites[pieceId]?.on;
}

export function setFavorite(l: Lists, pieceId: string, on: boolean, now = Date.now()): Lists {
  return { ...l, favorites: { ...l.favorites, [pieceId]: { on, at: now } } };
}

export function favoriteIds(l: Lists): Set<string> {
  return new Set(Object.keys(l.favorites).filter((id) => l.favorites[id].on));
}

// ---- setlists ----

export type SetlistSort = "name" | "created" | "played";

const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

/** The setlists to show: A-Z, newest first, or most recently played first (never played last, then A-Z). */
export function setlists(l: Lists, by: SetlistSort): Setlist[] {
  const all = Object.values(l.setlists).filter((s) => !s.deleted);
  const name = (a: Setlist, b: Setlist) => collator.compare(a.name, b.name) || a.created - b.created;
  if (by === "created") return all.sort((a, b) => b.created - a.created || name(a, b));
  if (by === "played") return all.sort((a, b) => (b.played ?? 0) - (a.played ?? 0) || name(a, b));
  return all.sort(name);
}

export function newSetlistId(now = Date.now()): string {
  return `s${now.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function createSetlist(l: Lists, name: string, pieces: string[] = [], now = Date.now(), id = newSetlistId(now)): { lists: Lists; id: string } {
  const s: Setlist = { id, name: name.trim() || "Untitled setlist", pieces: [...new Set(pieces)], created: now, updated: now };
  return { lists: { ...l, setlists: { ...l.setlists, [id]: s } }, id };
}

/** Changes a setlist's name or pieces (marking it changed now). */
export function editSetlist(l: Lists, id: string, change: { name?: string; pieces?: string[] }, now = Date.now()): Lists {
  const s = l.setlists[id];
  if (!s) return l;
  const next: Setlist = { ...s, updated: Math.max(now, s.updated + 1) };
  if (change.name !== undefined) next.name = change.name.trim() || s.name;
  if (change.pieces) next.pieces = [...new Set(change.pieces)];
  return { ...l, setlists: { ...l.setlists, [id]: next } };
}

export function addToSetlist(l: Lists, id: string, pieceId: string, now = Date.now()): Lists {
  const s = l.setlists[id];
  if (!s || s.pieces.includes(pieceId)) return l;
  return editSetlist(l, id, { pieces: [...s.pieces, pieceId] }, now);
}

export function removeFromSetlist(l: Lists, id: string, index: number, now = Date.now()): Lists {
  const s = l.setlists[id];
  if (!s) return l;
  return editSetlist(l, id, { pieces: s.pieces.filter((_, i) => i !== index) }, now);
}

/** Moves the piece at `index` up (-1) or down (+1). */
export function moveInSetlist(l: Lists, id: string, index: number, by: -1 | 1, now = Date.now()): Lists {
  const s = l.setlists[id];
  const to = index + by;
  if (!s || to < 0 || to >= s.pieces.length) return l;
  const pieces = [...s.pieces];
  [pieces[index], pieces[to]] = [pieces[to], pieces[index]];
  return editSetlist(l, id, { pieces }, now);
}

export function deleteSetlist(l: Lists, id: string, now = Date.now()): Lists {
  const s = l.setlists[id];
  if (!s) return l;
  return { ...l, setlists: { ...l.setlists, [id]: { ...s, pieces: [], deleted: true, updated: Math.max(now, s.updated + 1) } } };
}

export function markPlayed(l: Lists, id: string, now = Date.now()): Lists {
  const s = l.setlists[id];
  if (!s || s.deleted) return l;
  return { ...l, setlists: { ...l.setlists, [id]: { ...s, played: now } } };
}
