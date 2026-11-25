"""The score library on disk (usually a Google Drive for Desktop folder).

Layout (see docs/library.md):

    <root>/
      library.json      generated index the app reads (do not edit by hand)
      catalog.csv       one row per PDF: titles, editions, technique tags
      tags.md           allowed technique tags
      inbox/            new downloads waiting to be filed
      pieces/<piece_id>/<piece_id>__<variant>.pdf
                        <piece_id>.musicxml  or  <piece_id>__<variant>.musicxml / .mxl
"""

from __future__ import annotations

import csv
import datetime
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*(_[a-z0-9]+(-[a-z0-9]+)*){1,2}$")
VARIANT_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COLUMNS = ["piece_id", "file", "variant", "composer", "title", "catalog_no",
           "edition", "source", "pages", "key", "clefs", "positions", "tags",
           "added", "notes"]
KINDS = {".pdf": "pdf", ".musicxml": "musicxml", ".mxl": "musicxml", ".xml": "musicxml"}
INDEX_NAME = "library.json"
FORMAT = "lento-library"
VERSION = 1


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Library:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.pieces = self.root / "pieces"
        self.catalog_path = self.root / "catalog.csv"
        self.tags_path = self.root / "tags.md"

    # ---- reading ----

    def tags(self) -> set[str] | None:
        if not self.tags_path.is_file():
            return None
        found = set()
        for line in self.tags_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^- ([a-z0-9-]+)", line)
            if m:
                found.add(m.group(1))
        return found

    def catalog(self) -> list[dict[str, str]]:
        if not self.catalog_path.is_file():
            return []
        with self.catalog_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"catalog.csv is missing columns: {', '.join(missing)}")
            return [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]

    def folders(self) -> list[Path]:
        if not self.pieces.is_dir():
            return []
        return sorted(p for p in self.pieces.iterdir() if p.is_dir())

    # ---- checking ----

    def check(self, practice_ids: set[str] | None = None) -> Report:
        rep = Report()
        tags = self.tags()
        rows = self.catalog()
        catalogued: set[tuple[str, str]] = set()
        for i, r in enumerate(rows, start=2):
            pid, fname, variant = r["piece_id"], r["file"], r["variant"]
            where = f"catalog.csv line {i}"
            if not ID_RE.match(pid):
                rep.problems.append(f"{where}: piece_id '{pid}' does not follow composer_title[_catalog]")
            if not VARIANT_RE.match(variant):
                rep.problems.append(f"{where}: variant '{variant}' should be lowercase words joined by hyphens")
            expected = f"{pid}__{variant}.pdf"
            if fname != expected:
                rep.problems.append(f"{where}: file '{fname}' should be named '{expected}'")
            if not (self.pieces / pid / fname).is_file():
                rep.problems.append(f"{where}: file not found at pieces/{pid}/{fname}")
            if (pid, fname) in catalogued:
                rep.problems.append(f"{where}: duplicate row for {fname}")
            catalogued.add((pid, fname))
            for t in split_tags(r["tags"]):
                if tags is not None and t not in tags:
                    rep.problems.append(f"{where}: tag '{t}' is not in tags.md")
            if not r["tags"]:
                rep.notes.append(f"{where}: {pid} has no technique tags yet")

        for folder in self.folders():
            if not ID_RE.match(folder.name):
                rep.problems.append(f"pieces/{folder.name}: folder name is not a valid piece_id")
            for pdf in sorted(folder.glob("*.pdf")):
                if (folder.name, pdf.name) not in catalogued:
                    rep.problems.append(f"pieces/{folder.name}/{pdf.name}: not in catalog.csv")

        inbox = sorted(p.name for p in (self.root / "inbox").glob("*") if p.is_file())
        if inbox:
            rep.notes.append(f"inbox has {len(inbox)} file(s) waiting: {', '.join(inbox)}")

        if practice_ids is not None:
            for pid in sorted(i for i in practice_ids if not ID_RE.match(i)):
                rep.problems.append(f"practice list: piece_id '{pid}' does not follow composer_title[_catalog]")
            lib_ids = {r["piece_id"] for r in rows} | {f.name for f in self.folders()}
            for pid in sorted(lib_ids - practice_ids):
                rep.notes.append(f"{pid}: in the library but not on the practice list")
            for pid in sorted(practice_ids - lib_ids):
                rep.notes.append(f"{pid}: on the practice list but not in the library yet")
        return rep

    # ---- changing ----

    def add(self, src: Path, piece_id: str, variant: str) -> Path:
        """Move a PDF (or MusicXML) into its piece folder and, for a PDF, append a catalog row."""
        if not src.is_file():
            raise FileNotFoundError(src)
        kind = KINDS.get(src.suffix.lower())
        if not kind:
            raise ValueError("only PDF and MusicXML files go in the library")
        if not ID_RE.match(piece_id):
            raise ValueError(f"piece_id '{piece_id}' does not follow composer_title[_catalog]")
        if not VARIANT_RE.match(variant):
            raise ValueError(f"variant '{variant}' should be lowercase words joined by hyphens")
        dest = self.pieces / piece_id / f"{piece_id}__{variant}{src.suffix.lower()}"
        if dest.exists():
            raise FileExistsError(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dest)
        if kind == "pdf":
            new = not self.catalog_path.is_file()
            row = {c: "" for c in COLUMNS}
            row.update(piece_id=piece_id, file=dest.name, variant=variant, pages=count_pages(dest),
                       added=datetime.date.today().isoformat())
            with self.catalog_path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                if new:
                    w.writeheader()
                w.writerow(row)
        return dest

    # ---- the index ----

    def index(self) -> dict:
        """Everything the app needs to browse the library, built from the folders plus catalog.csv."""
        rows: dict[str, list[dict[str, str]]] = {}
        for r in self.catalog():
            rows.setdefault(r["piece_id"], []).append(r)
        pieces = []
        for folder in self.folders():
            pid = folder.name
            if not ID_RE.match(pid):
                continue
            meta = rows.get(pid, [])
            first = meta[0] if meta else {}
            by_file = {r["file"]: r for r in meta}
            files = []
            for p in sorted(folder.iterdir()):
                kind = KINDS.get(p.suffix.lower())
                if not p.is_file() or not kind:
                    continue
                stem = p.name[: -len(p.suffix)]
                entry: dict = {"name": p.name, "kind": kind, "variant": stem.split("__", 1)[1] if "__" in stem else ""}
                r = by_file.get(p.name)
                if r:
                    for k in ("edition", "source"):
                        if r[k]:
                            entry[k] = r[k]
                    if r["pages"].isdigit():
                        entry["pages"] = int(r["pages"])
                files.append(entry)
            if not files:
                continue
            tags = sorted({t for r in meta for t in split_tags(r["tags"])})
            piece = {
                "id": pid,
                "title": first.get("title") or title_from_id(pid),
                "composer": first.get("composer") or composer_from_id(pid),
                "files": files,
            }
            for k in ("catalog_no", "key", "clefs", "positions", "notes"):
                if first.get(k):
                    piece[k] = first[k]
            if tags:
                piece["tags"] = tags
            pieces.append(piece)
        return {
            "format": FORMAT,
            "version": VERSION,
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "pieces": pieces,
        }

    def write_index(self) -> tuple[Path, int]:
        data = self.index()
        path = self.root / INDEX_NAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)  # atomic, so Drive never syncs a half-written index
        return path, len(data["pieces"])


def split_tags(text: str) -> list[str]:
    return [t for t in (t.strip() for t in text.split(";")) if t]


def title_from_id(pid: str) -> str:
    parts = pid.split("_")
    title = parts[1].replace("-", " ").capitalize() if len(parts) > 1 else pid
    return f"{title}, {parts[2].upper()}" if len(parts) > 2 else title


def composer_from_id(pid: str) -> str:
    return "-".join(w.capitalize() for w in pid.split("_")[0].split("-"))


def count_pages(path: Path) -> str:
    """Rough page count without extra libraries; blank if unsure."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    n = len(re.findall(rb"/Type\s*/Page(?![s\w])", data))
    return str(n) if n else ""
