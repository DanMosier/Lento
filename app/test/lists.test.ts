import { describe, expect, it } from "vitest";
import {
  addToSetlist,
  createSetlist,
  deleteSetlist,
  editSetlist,
  emptyLists,
  favoriteIds,
  isFavorite,
  markPlayed,
  mergeLists,
  moveInSetlist,
  parseLists,
  removeFromSetlist,
  sameLists,
  setFavorite,
  setlists,
} from "../src/library/lists";

describe("favorites", () => {
  it("stars and unstars a piece", () => {
    let l = setFavorite(emptyLists(), "bach_suite-1", true, 10);
    expect(isFavorite(l, "bach_suite-1")).toBe(true);
    l = setFavorite(l, "bach_suite-1", false, 20);
    expect(isFavorite(l, "bach_suite-1")).toBe(false);
    expect(favoriteIds(setFavorite(l, "faure_elegie", true, 30))).toEqual(new Set(["faure_elegie"]));
  });

  it("merges two devices: the newer change to each piece wins, so an unstar isn't undone by an older star", () => {
    const base = setFavorite(setFavorite(emptyLists(), "a", true, 10), "b", true, 10);
    const phone = setFavorite(base, "a", false, 50); // unstarred on the phone later
    const pc = setFavorite(base, "c", true, 40); // starred something else on the PC
    const m = mergeLists(phone, pc);
    expect(favoriteIds(m)).toEqual(new Set(["b", "c"]));
    expect(sameLists(m, mergeLists(pc, phone))).toBe(true);
  });
});

describe("setlists", () => {
  const make = () => {
    const r = createSetlist(emptyLists(), "  Recital  ", ["a", "b", "a"], 100, "s1");
    return r.lists;
  };

  it("creates, adds, moves, removes and renames", () => {
    let l = make();
    expect(l.setlists.s1).toMatchObject({ name: "Recital", pieces: ["a", "b"], created: 100 });
    l = addToSetlist(l, "s1", "c", 110);
    l = addToSetlist(l, "s1", "a", 120); // already there: no change
    expect(l.setlists.s1.pieces).toEqual(["a", "b", "c"]);
    l = moveInSetlist(l, "s1", 2, -1, 130);
    expect(l.setlists.s1.pieces).toEqual(["a", "c", "b"]);
    expect(moveInSetlist(l, "s1", 0, -1, 140)).toBe(l); // can't move the first one up
    l = removeFromSetlist(l, "s1", 0, 150);
    expect(l.setlists.s1.pieces).toEqual(["c", "b"]);
    l = editSetlist(l, "s1", { name: "Spring recital" }, 160);
    expect(l.setlists.s1.name).toBe("Spring recital");
    expect(l.setlists.s1.updated).toBe(160);
  });

  it("sorts A-Z, newest first, and most recently played first with unplayed last", () => {
    let l = emptyLists();
    l = createSetlist(l, "warm-ups", [], 300, "w").lists;
    l = createSetlist(l, "Bach", [], 100, "b").lists;
    l = createSetlist(l, "concerto", [], 200, "c").lists;
    l = markPlayed(l, "b", 500);
    l = markPlayed(l, "c", 900);
    expect(setlists(l, "name").map((s) => s.name)).toEqual(["Bach", "concerto", "warm-ups"]);
    expect(setlists(l, "created").map((s) => s.id)).toEqual(["w", "c", "b"]);
    expect(setlists(l, "played").map((s) => s.id)).toEqual(["c", "b", "w"]);
  });

  it("deleted setlists disappear and stay deleted when merged with an older copy", () => {
    const old = make();
    const gone = deleteSetlist(old, "s1", 200);
    expect(setlists(gone, "name")).toEqual([]);
    expect(setlists(mergeLists(old, gone), "name")).toEqual([]);
  });

  it("merges: the newer edit wins, last played is the later of the two, new setlists from both are kept", () => {
    const base = make();
    const phone = markPlayed(addToSetlist(base, "s1", "c", 300), "s1", 400);
    const pc = createSetlist(markPlayed(base, "s1", 500), "Etudes", ["x"], 250, "s2").lists;
    const m = mergeLists(phone, pc);
    expect(m.setlists.s1.pieces).toEqual(["a", "b", "c"]);
    expect(m.setlists.s1.played).toBe(500);
    expect(m.setlists.s2.name).toBe("Etudes");
  });

  it("reads back what it saved, and ignores junk", () => {
    const l = setFavorite(make(), "a", true, 5);
    expect(sameLists(parseLists(JSON.parse(JSON.stringify(l))), l)).toBe(true);
    expect(parseLists({ favorites: { a: "yes" }, setlists: { x: { name: 3 } } })).toEqual(emptyLists());
    expect(parseLists(null)).toEqual(emptyLists());
  });
});
