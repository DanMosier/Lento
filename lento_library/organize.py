"""Filing an existing, unorganized score folder into the library layout, one batch at a time.

  plan   scans every score file outside pieces/ and writes organize-plan.csv: for each file, its batch (the top
         folder it is in), the piece_id and variant it would get, and action "move". Nothing is moved. Edit the
         CSV in Excel or Sheets: fix ids, set action to "skip" for anything that should stay where it is.
  apply  moves the files of one batch as the plan says, adds catalog rows for the PDFs, and logs every move to
         organize-log.csv, so that batch can be put back with `undo`.
  undo   moves a batch's files back where they were (from organize-log.csv).

Files that belong together (a PDF, the MusicXML made from it, its quality report) share a stem, so they move
together and keep sharing one.
"""

from __future__ import annotations

import csv
import datetime
import re
import shutil
import unicodedata
from pathlib import Path

from lento_library.library import (
    COLUMNS,
    ID_RE,
    INDEX_NAME,
    KINDS,
    MUSESCORE,
    REQUESTS,
    VARIANT_RE,
    Library,
    count_pages,
)

PLAN = "organize-plan.csv"
LOG = "organize-log.csv"
PLAN_COLUMNS = ["batch", "source", "piece_id", "variant", "action", "composer", "title"]
LOG_COLUMNS = ["batch", "source", "dest", "moved"]
SCORE_EXT = set(KINDS) | set(MUSESCORE)
SKIP_TOP = {"pieces", REQUESTS, "inbox"}


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def composer_slug(folder: str) -> str:
    """'Villa-Lobos, Heitor' -> 'villa-lobos'; 'Bach, Johann Sebastian' -> 'bach'."""
    return slug(folder.split(",")[0]) or "unknown"


def split_stem(stem: str) -> tuple[str, str]:
    """('34 - Brahms Symphony 2 mvt 4', '1') for '34 - Brahms Symphony 2 mvt 4-1': a trailing -N is a part number."""
    m = re.match(r"^(.*\S)-(\d{1,2})$", stem)
    return (m.group(1), m.group(2)) if m else (stem, "")


def strip_number(stem: str) -> str:
    return re.sub(r"^\s*\d+\s*[-.)]\s*", "", stem)  # "74 - Mozart ..." -> "Mozart ..."


def title_slug(stem: str, composer: str) -> str:
    s = slug(strip_number(stem))
    if composer and s.startswith(composer + "-"):  # "mozart-magic-flute" -> "magic-flute"
        s = s[len(composer) + 1:]
    return s or "untitled"


def scan(lib: Library) -> list[Path]:
    out = []
    for p in sorted(lib.root.rglob("*")):
        rel = p.relative_to(lib.root)
        if len(rel.parts) > 1 and rel.parts[0] in SKIP_TOP:
            continue
        if p.is_file() and p.suffix.lower() in SCORE_EXT:
            out.append(p)
    return out


def plan(lib: Library) -> tuple[Path, int]:
    """Writes organize-plan.csv, keeping the rows of a plan already there (so edits survive a re-run)."""
    path = lib.root / PLAN
    old = {r["source"]: r for r in read_csv(path)}
    rows: list[dict[str, str]] = []
    taken: set[tuple[str, str, str]] = set()  # (piece_id, variant, ext) already planned
    for r in old.values():
        taken.add((r["piece_id"], r["variant"], Path(r["source"]).suffix.lower()))
    for p in scan(lib):
        rel = p.relative_to(lib.root).as_posix()
        if rel in old:
            rows.append(old[rel])
            continue
        parts = p.relative_to(lib.root).parts
        batch = parts[0] if len(parts) > 1 else "(top folder)"
        composer_folder = parts[0] if len(parts) > 1 and "," in parts[0] else ""
        stem, part = split_stem(p.stem)
        # the composer from a "Last, First" folder, else the first word of the name ("74 - Mozart Magic Flute")
        comp = composer_slug(composer_folder) if composer_folder else (slug(strip_number(stem).split(" ")[0]) or "unknown")
        title = title_slug(stem, comp)
        pid = f"{comp}_{title}"
        variant = f"part-{part}" if part else "score"
        ext = p.suffix.lower()
        n, base = 2, variant
        while (pid, variant, ext) in taken:  # two files would get the same name: number the later one
            variant, n = f"{base}-{n}", n + 1
        taken.add((pid, variant, ext))
        rows.append({"batch": batch, "source": rel, "piece_id": pid, "variant": variant, "action": "move",
                     "composer": composer_folder, "title": stem})
    rows.sort(key=lambda r: (r["batch"], r["source"]))
    write_csv(path, PLAN_COLUMNS, rows)
    return path, len(rows)


def batches(lib: Library) -> dict[str, tuple[int, int]]:
    """Batch -> (files still to move, files moved)."""
    moved = {r["source"] for r in read_csv(lib.root / LOG) if r.get("moved") == "yes"}
    out: dict[str, tuple[int, int]] = {}
    for r in read_csv(lib.root / PLAN):
        if r["action"].strip().lower() != "move":
            continue
        todo, done = out.get(r["batch"], (0, 0))
        out[r["batch"]] = (todo, done + 1) if r["source"] in moved else (todo + 1, done)
    return out


def apply(lib: Library, batch: str) -> tuple[list[str], list[str]]:
    """Moves one batch. Returns (moved, problems). Checks every row first, so a bad id moves nothing."""
    rows = [r for r in read_csv(lib.root / PLAN) if r["batch"] == batch and r["action"].strip().lower() == "move"]
    if not rows:
        raise ValueError(f"no files to move in batch '{batch}' (see {PLAN})")
    done = {r["source"] for r in read_csv(lib.root / LOG) if r.get("moved") == "yes"}
    problems, todo = [], []
    seen: set[Path] = set()
    for r in rows:
        if r["source"] in done:
            continue
        src = lib.root / r["source"]
        pid, var = r["piece_id"].strip(), r["variant"].strip()
        dest = lib.pieces / pid / f"{pid}__{var}{src.suffix.lower()}"
        if not ID_RE.match(pid):
            problems.append(f"{r['source']}: piece_id '{pid}' should be composer_title (lowercase, hyphens)")
        elif not VARIANT_RE.match(var):
            problems.append(f"{r['source']}: variant '{var}' should be lowercase words joined by hyphens")
        elif not src.is_file():
            problems.append(f"{r['source']}: not found")
        elif dest.exists() or dest in seen:
            problems.append(f"{r['source']}: {dest.relative_to(lib.root).as_posix()} would be taken twice")
        else:
            seen.add(dest)
            todo.append((r, src, dest))
    if problems:
        return [], problems
    log = read_csv(lib.root / LOG)
    catalog_new = not lib.catalog_path.is_file()
    cat_rows = []
    moved = []
    today = datetime.date.today().isoformat()
    for r, src, dest in todo:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dest)
        log.append({"batch": batch, "source": r["source"], "dest": dest.relative_to(lib.root).as_posix(), "moved": "yes"})
        report = src.with_name(f"{src.stem}.quality.json")  # Lento_ConvertPDF's quality report travels with its file
        if report.is_file() and not dest.with_name(f"{dest.stem}.quality.json").exists():
            shutil.move(str(report), dest.with_name(f"{dest.stem}.quality.json"))
            log.append({"batch": batch, "source": report.relative_to(lib.root).as_posix(),
                        "dest": dest.with_name(f"{dest.stem}.quality.json").relative_to(lib.root).as_posix(), "moved": "yes"})
        moved.append(dest.relative_to(lib.root).as_posix())
        if dest.suffix == ".pdf":
            row = {c: "" for c in COLUMNS}
            row.update(piece_id=r["piece_id"].strip(), file=dest.name, variant=r["variant"].strip(), composer=r.get("composer", ""),
                       title=r.get("title", ""), source=r["source"], pages=count_pages(dest), added=today)
            cat_rows.append(row)
        write_csv(lib.root / LOG, LOG_COLUMNS, log)  # after every move, so a crash leaves an exact record
    if cat_rows:
        with lib.catalog_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if catalog_new:
                w.writeheader()
            w.writerows(cat_rows)
    lib.write_index()
    return moved, []


def undo(lib: Library, batch: str) -> list[str]:
    """Moves a batch's files back and drops their catalog rows. Returns what was put back."""
    log = read_csv(lib.root / LOG)
    back, names = [], set()
    for r in log:
        if r["batch"] != batch or r.get("moved") != "yes":
            continue
        dest, src = lib.root / r["dest"], lib.root / r["source"]
        if dest.is_file() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), src)
            r["moved"] = "undone"
            back.append(r["source"])
            names.add(dest.name)
            if dest.parent.is_dir() and not any(dest.parent.iterdir()):
                dest.parent.rmdir()
    write_csv(lib.root / LOG, LOG_COLUMNS, log)
    if names and lib.catalog_path.is_file():
        rows = [r for r in lib.catalog() if r["file"] not in names]
        write_csv(lib.catalog_path, COLUMNS, rows)
    if (lib.root / INDEX_NAME).exists() or back:
        lib.write_index()
    return back


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "") for k, v in r.items() if k} for r in csv.DictReader(f)]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads accents right
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
