/**
 * The Convert PDF queue: what the PC is converting now, what comes next, and what it hasn't picked up yet, worked
 * out from the watcher's requests/_status.json and the library index. Pure functions, so they're cheap and tested.
 */
import type { LibraryFile, LibraryIndex, PcStatus, Piece } from "../core/library/model";
import { musicxmlOf, requestName } from "../core/library/model";

export interface QueueItem {
  name: string; // the PDF's file name
  title: string;
  sub: string;
}

export interface NowItem extends QueueItem {
  elapsed_s: number;
  /** 0..1 estimate from recent conversion times, or null before there are any. */
  fraction: number | null;
  left_s: number | null;
  /** The page homr is on, when the PC says. */
  page?: { page: number; pages: number };
}

export interface QueueView {
  now: NowItem[];
  next: QueueItem[];
  /** Asked for (here or on another device) but not in the PC's current batch yet. */
  pickup: QueueItem[];
  recent: (QueueItem & { ok: boolean; at: string; seconds?: number; error?: string })[];
  batch: { done: number; total: number; left_s: number | null } | null;
}

export type Names = Map<string, { piece: Piece; file: LibraryFile }>;

/** PDF file name -> its piece, for labelling the PC's file names. Build once per index. */
export function namesOf(index: LibraryIndex | null): Names {
  const m: Names = new Map();
  for (const piece of index?.pieces ?? []) for (const file of piece.files) if (file.kind === "pdf") m.set(file.name, { piece, file });
  return m;
}

export function item(name: string, names: Names): QueueItem {
  const hit = names.get(name);
  if (!hit) return { name, title: name.replace(/\.(pdf|mscz|mscx)$/i, ""), sub: "" };
  const ed = hit.file.edition || hit.file.variant;
  return { name, title: hit.piece.title, sub: [hit.piece.composer, ed].filter(Boolean).join(" · ") };
}

/** `removed`: PDF names taken off the queue on this device, hidden until the PC and the index catch up. */
export function buildQueue(s: PcStatus | null, index: LibraryIndex | null, names: Names, mine: Set<string>, now = Date.now(), removed = new Set<string>()): QueueView {
  const busy = s?.state === "converting" ? (s.current_files ?? (s.current ? s.current.split(", ") : [])) : [];
  const avg = s?.avg_s && s.avg_s > 0 ? s.avg_s : null;
  const elapsed = s?.started ? Math.max(0, (now - Date.parse(s.started)) / 1000) : 0;
  const nowItems: NowItem[] = busy.map((n, i) => {
    // a folder's PDFs convert one after another; only the first is under way
    const e = i === 0 ? elapsed : 0;
    const p = s?.page && s.page.pdf === n && s.page.pages > 0 ? { page: s.page.page, pages: s.page.pages } : undefined;
    return { ...item(n, names), elapsed_s: e, fraction: avg ? Math.min(0.95, e / avg) : null, left_s: avg ? Math.max(0, avg - e) : null, ...(p ? { page: p } : {}) };
  });
  const queue = (s?.state === "converting" ? s.queue : []).filter((n) => !removed.has(n));
  const inBatch = new Set([...busy, ...queue]);
  const converted = new Set((s?.results ?? []).filter((r) => r.ok).map((r) => r.pdf));
  const pickup: QueueItem[] = [];
  for (const piece of index?.pieces ?? [])
    for (const file of piece.files) {
      if (file.kind !== "pdf" || musicxmlOf(file) || inBatch.has(file.name) || removed.has(file.name)) continue;
      if (!(file.requested || mine.has(requestName(file)))) continue;
      if (converted.has(file.name)) continue; // converted since the index was built
      pickup.push(item(file.name, names));
    }
  const batch = s?.state === "converting" && s.batch ? s.batch : null;
  const left = avg ? (nowItems[0]?.left_s ?? 0) + avg * (Math.max(0, nowItems.length - 1) + queue.length) : null;
  return {
    now: nowItems,
    next: queue.map((n) => item(n, names)),
    pickup,
    recent: [...(s?.results ?? [])].reverse().slice(0, 10).map((r) => ({ ...item(r.pdf, names), ok: r.ok, at: r.at, seconds: r.seconds, error: r.error })),
    batch: batch ? { done: batch.done, total: batch.total, left_s: left } : null,
  };
}

/** "about 4 min", "about 1 h 20 min", "under a minute". */
export function duration(s: number): string {
  if (s < 60) return "under a minute";
  const m = Math.round(s / 60);
  if (m < 60) return `about ${m} min`;
  return `about ${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}
