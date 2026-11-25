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
from dataclasses import dataclass
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


PARTICLES = {"von", "van", "de", "der", "den", "d", "la", "le", "du", "da", "di", "jr", "sr", "zu"}
MAX_TITLE = 60  # keeps pieces/<id>/<id>__<variant>.pdf well inside Windows' 260-character path limit


def strip_number(stem: str) -> str:
    return re.sub(r"^\s*\d+\s*[-.)]\s*", "", stem)  # "74 - Mozart ..." -> "Mozart ..."


def initials(first: str) -> str:
    """'Johann Sebastian' -> 'js', 'J.S' -> 'js', 'CPE' -> 'cpe', 'Fr' -> 'f', 'Ludwig van' -> 'l'."""
    out = ""
    for tok in re.split(r"[\s.\-]+", unicodedata.normalize("NFKD", first)):
        tok = re.sub(r"[^A-Za-z]", "", tok)
        if not tok or tok.lower() in PARTICLES:
            continue
        out += tok.lower() if tok.isupper() and len(tok) <= 4 else tok[0].lower()
    return out


@dataclass
class Name:
    composer: str  # "Bach, Johann Sebastian" as written, or ""
    surname: str  # slug
    first: str  # initials
    title: str  # what is left of the file name
    variant: str


def parse(parts: tuple[str, ...], stem: str) -> Name:
    """Reads composer, title and part from where a file is and what it is called.

    "Bach, Johann Sebastian/Bach, Johann Sebastian - Cello Suite No.1 C.pdf" -> bach / js / Cello Suite No.1 / cello
    "Compilations/.../02 - Bartok Concerto for Orchestra-1.pdf"            -> bartok / Concerto for Orchestra excerpt 1
    """
    folder = parts[0] if len(parts) > 1 else ""
    text = strip_number(stem).strip()
    numbered = text != stem.strip()
    composer = ""
    m = re.match(r"^([^,]+,.+?)\s+-\s+(.+)$", text)  # "Last, First - Title": the name as written beats a garbled folder name
    if m:
        composer, text = m.group(1).strip(), m.group(2).strip()
    elif "," in folder:
        composer = folder
        pre, sep, rest = text.partition(" - ")  # "di Lasso - I know a Young Maiden" in "Lasso, di"
        if sep and slug(folder.split(",")[0]) in slug(pre).split("-"):
            text = rest.strip()
    variant = "score"
    text = re.sub(r"\s+P\s*&\s*C$", "", text)  # "P & C": piano and cello, i.e. the whole score
    pm = re.match(r"^(.*?)(?:\s+|(?<=[\d.]))([CP])$", text)  # "Op.65P", "Op. 31 C": the piano or cello part
    wm = re.match(r"^(.*\S)\s+(cello|piano)$", text, re.IGNORECASE)
    if pm and pm.group(1):
        text, variant = pm.group(1).rstrip(" .,-"), "cello" if pm.group(2) == "C" else "piano"
    elif wm and wm.group(1).split()[-1].lower() not in {"for", "and", "solo", "et", "pour", "violoncelle", "&"}:
        text, variant = wm.group(1).rstrip(" .,-"), wm.group(2).lower()
    # "Bartok Concerto for Orchestra-5": excerpt 5. After a digit only in numbered files ("34 - ... mvt 4-1"),
    # since "Op.4 nos. 1-5" is a range
    em = re.match(r"^(.*[A-Za-z)])-(\d{1,2})$", text) or (numbered and re.match(r"^(.*\S)-(\d{1,2})$", text))
    if em:
        text = f"{em.group(1)} excerpt {em.group(2)}"
    if composer:
        last, _, first = composer.partition(",")
        surname, first = slug(last) or "unknown", initials(first)
    else:  # no composer given: the first word of the title ("Bartok Concerto for Orchestra")
        word = text.split(" ")[0]
        surname, first = slug(word) or "unknown", ""
        if " " in text and slug(word):
            text = text.split(" ", 1)[1]
    return Name(composer, surname, first, text, variant)


def title_slug(text: str) -> str:
    s = slug(text) or "untitled"
    if len(s) > MAX_TITLE:
        s = s[:MAX_TITLE].rsplit("-", 1)[0]
    return s


def scan(lib: Library) -> list[Path]:
    out = []
    for p in sorted(lib.root.rglob("*")):
        rel = p.relative_to(lib.root)
        if len(rel.parts) > 1 and rel.parts[0] in SKIP_TOP:
            continue
        if p.is_file() and p.suffix.lower() in SCORE_EXT:
            out.append(p)
    return out


def plan(lib: Library, fresh: bool = False) -> tuple[Path, int]:
    """Writes organize-plan.csv, keeping the rows of a plan already there (so edits survive a re-run) unless
    `fresh`. Files already moved (in organize-log.csv) are never planned again."""
    path = lib.root / PLAN
    old = {} if fresh else {r["source"]: r for r in read_csv(path)}
    files = scan(lib)
    names = {p: parse(p.relative_to(lib.root).parts, p.stem) for p in files}
    # a surname shared by composers with different first names (the Bachs, the Rombergs) gets their initials
    firsts: dict[str, set[str]] = {}
    for n in names.values():
        if n.first:
            firsts.setdefault(n.surname, set()).add(n.first)
    families = {s for s, f in firsts.items() if len(f) > 1}
    rows: list[dict[str, str]] = []
    taken: set[tuple[str, str, str]] = set()  # (piece_id, variant, ext) already planned
    for r in old.values():
        taken.add((r["piece_id"], r["variant"], Path(r["source"]).suffix.lower()))
    for p in files:
        rel = p.relative_to(lib.root).as_posix()
        if rel in old:
            rows.append(old[rel])
            continue
        parts = p.relative_to(lib.root).parts
        batch = parts[0] if len(parts) > 1 else "(top folder)"
        nm = names[p]
        comp = f"{nm.surname}-{nm.first}" if nm.surname in families and nm.first else nm.surname
        pid = f"{comp}_{title_slug(nm.title)}"
        variant = nm.variant
        ext = p.suffix.lower()
        n, base = 2, variant
        while (pid, variant, ext) in taken:  # two files would get the same name: number the later one
            variant, n = f"{base}-{n}", n + 1
        taken.add((pid, variant, ext))
        rows.append({"batch": batch, "source": rel, "piece_id": pid, "variant": variant, "action": "move",
                     "composer": nm.composer, "title": nm.title})
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
