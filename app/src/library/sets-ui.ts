/**
 * The Setlists window in the Library: every setlist (sorted A-Z, by date made, or by last played), and one setlist's
 * pieces in playing order. Opening a piece from here shows the usual piece window, and practising it marks the
 * setlist as played.
 */
import { $, store } from "../core/app";
import { search, type Piece } from "../core/library/model";
import {
  addToSetlist,
  createSetlist,
  deleteSetlist,
  editSetlist,
  moveInSetlist,
  removeFromSetlist,
  setlists,
  type Setlist,
  type SetlistSort,
} from "./lists";
import { changeLists, currentLists, onListsChanged, syncNote } from "./lists-store";

interface Host {
  pieces(): Piece[];
  byId(id: string): Piece | undefined;
  /** Shows the piece window; `setId` says it was opened from that setlist. */
  openPiece(p: Piece, setId: string): void;
}

const ui = {
  dialog: $<HTMLDialogElement>("lib-sets"),
  title: $("lib-sets-title"),
  back: $<HTMLButtonElement>("lib-sets-back"),
  close: $<HTMLButtonElement>("lib-sets-close"),
  body: $("lib-sets-body"),
  sync: $("lib-sets-sync"),
};

let host: Host | null = null;
let openSet: string | null = null; // the setlist being shown, or null for all of them
let sortBy: SetlistSort = store.get<SetlistSort>("library.setlistSort") ?? "name";
let addQuery = "";
let confirmDelete = false;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function button(text: string, cls: string | undefined, onClick: () => void, label?: string): HTMLButtonElement {
  const b = el("button", text, cls);
  b.type = "button";
  if (label) b.setAttribute("aria-label", (b.title = label));
  b.addEventListener("click", onClick);
  return b;
}

const day = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

export function ago(t: number, now = Date.now()): string {
  const min = Math.round((now - t) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 14) return d === 1 ? "yesterday" : `${d} days ago`;
  return day.format(t);
}

function count(n: number): string {
  return `${n} piece${n === 1 ? "" : "s"}`;
}

export function initSetlists(h: Host): void {
  host = h;
}

/** Opens the window: on the setlist shown last time, or the list of setlists. */
export function openSetlists(setId: string | null = openSet): void {
  openSet = setId && currentLists().setlists[setId] && !currentLists().setlists[setId].deleted ? setId : null;
  draw();
  if (!ui.dialog.open) ui.dialog.showModal();
}

export function closeSetlists(): void {
  if (ui.dialog.open) ui.dialog.close();
}

function draw(): void {
  confirmDelete = false;
  ui.sync.textContent = syncNote();
  const s = openSet ? currentLists().setlists[openSet] : null;
  if (s && !s.deleted) drawOne(s);
  else {
    openSet = null;
    drawAll();
  }
}

function drawAll(): void {
  ui.title.textContent = "Setlists";
  ui.back.hidden = true;
  const sort = el("select", undefined, "sets-sort");
  sort.setAttribute("aria-label", "Sort setlists");
  for (const [v, label] of [
    ["name", "A–Z"],
    ["created", "Date created"],
    ["played", "Last played"],
  ] as const)
    sort.append(new Option(label, v, false, v === sortBy));
  sort.addEventListener("change", () => {
    sortBy = sort.value as SetlistSort;
    store.set("library.setlistSort", sortBy);
    drawAll();
  });

  const form = el("form", undefined, "sets-new");
  const name = el("input");
  name.placeholder = "New setlist name";
  name.setAttribute("aria-label", "New setlist name");
  name.maxLength = 80;
  const make = el("button", "Create", "primary");
  form.append(name, make);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!name.value.trim()) return name.focus();
    let made = "";
    changeLists((l) => {
      const r = createSetlist(l, name.value);
      made = r.id;
      return r.lists;
    });
    openSet = made;
    draw();
  });

  const all = setlists(currentLists(), sortBy);
  const list = el("ul", undefined, "sets-list");
  for (const s of all) {
    const li = el("li");
    const b = button("", "sets-item", () => {
      openSet = s.id;
      draw();
    });
    const meta = [count(s.pieces.length), `created ${day.format(s.created)}`, s.played ? `played ${ago(s.played)}` : "not played yet"];
    b.append(el("strong", s.name), el("span", meta.join(" · "), "piece-meta"));
    li.append(b);
    list.append(li);
  }
  const top = el("div", undefined, "sets-top");
  top.append(form, sort);
  sort.hidden = all.length < 2;
  ui.body.replaceChildren(top, all.length ? list : el("p", "No setlists yet. Name one above, then add pieces to it.", "hint"));
}

function drawOne(s: Setlist): void {
  ui.title.textContent = s.name;
  ui.back.hidden = false;
  const pieces = el("ol", undefined, "sets-pieces");
  s.pieces.forEach((id, i) => {
    const p = host?.byId(id);
    const li = el("li");
    const open = button("", "sets-piece", () => p && host?.openPiece(p, s.id));
    open.disabled = !p;
    open.append(el("strong", p?.title ?? id), el("span", p ? p.composer : "No longer in the library", "piece-meta"));
    const up = button("↑", "sets-icon", () => changeLists((l) => moveInSetlist(l, s.id, i, -1)), "Move up");
    const down = button("↓", "sets-icon", () => changeLists((l) => moveInSetlist(l, s.id, i, 1)), "Move down");
    up.disabled = i === 0;
    down.disabled = i === s.pieces.length - 1;
    const remove = button("✕", "sets-icon", () => changeLists((l) => removeFromSetlist(l, s.id, i)), "Remove from setlist");
    li.append(open, up, down, remove);
    pieces.append(li);
  });

  // adding pieces: search the library right here
  const add = el("div", undefined, "sets-add");
  const q = el("input");
  q.type = "search";
  q.placeholder = "Add a piece: search title or composer";
  q.setAttribute("aria-label", "Search for a piece to add");
  q.value = addQuery;
  const found = el("ul", undefined, "sets-found");
  const showFound = () => {
    addQuery = q.value;
    found.replaceChildren();
    if (!q.value.trim() || !host) return;
    const have = new Set(s.pieces);
    const hits = search(host.pieces(), q.value).filter((p) => !have.has(p.id)).slice(0, 8);
    for (const p of hits) {
      const li = el("li");
      const b = button("", "sets-piece", () => {
        changeLists((l) => addToSetlist(l, s.id, p.id));
      });
      b.append(el("strong", `+ ${p.title}`), el("span", p.composer, "piece-meta"));
      li.append(b);
      found.append(li);
    }
    if (!hits.length) found.append(el("li", "Nothing matches.", "hint"));
  };
  let typing = 0;
  q.addEventListener("input", () => {
    clearTimeout(typing);
    typing = window.setTimeout(showFound, 120);
  });
  add.append(q, found);
  showFound();

  const rename = el("form", undefined, "sets-rename");
  const name = el("input");
  name.value = s.name;
  name.maxLength = 80;
  name.setAttribute("aria-label", "Setlist name");
  rename.append(name, el("button", "Rename"));
  rename.addEventListener("submit", (e) => {
    e.preventDefault();
    if (name.value.trim() && name.value.trim() !== s.name) changeLists((l) => editSetlist(l, s.id, { name: name.value }));
  });
  const del = button("Delete setlist", "danger", () => {
    if (!confirmDelete) {
      confirmDelete = true;
      del.textContent = "Tap again to delete";
      return;
    }
    changeLists((l) => deleteSetlist(l, s.id));
    openSet = null;
    draw();
  });
  const manage = el("details", undefined, "sets-manage");
  manage.append(el("summary", "Rename or delete"), rename, del);

  const meta = [count(s.pieces.length), `created ${day.format(s.created)}`, s.played ? `played ${ago(s.played)}` : "not played yet"];
  ui.body.replaceChildren(
    el("p", meta.join(" · "), "piece-meta sets-meta"),
    s.pieces.length ? pieces : el("p", "No pieces yet. Search below to add some, or use “Add to setlist” in any piece's window.", "hint"),
    add,
    manage,
  );
}

ui.back.addEventListener("click", () => {
  openSet = null;
  addQuery = "";
  draw();
});
ui.close.addEventListener("click", () => ui.dialog.close());
ui.dialog.addEventListener("click", (e) => {
  if (e.target === ui.dialog) ui.dialog.close(); // a tap on the backdrop
});
onListsChanged(() => {
  if (!ui.dialog.open) return;
  // keep the search box (and the keyboard) while adding pieces: redraw the rest
  const active = document.activeElement as HTMLInputElement | null;
  const typing = active && ui.body.contains(active) && active.type === "search";
  draw();
  if (typing) {
    const q = ui.body.querySelector<HTMLInputElement>(".sets-add input");
    q?.focus();
  }
});
