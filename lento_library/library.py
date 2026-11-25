"""The score library on disk (usually a Google Drive for Desktop folder).

Layout (see docs/library.md):

    <root>/
      library.json      generated index the app reads (do not edit by hand)
      catalog.csv       one row per PDF: titles, editions, technique tags
      tags.md           allowed technique tags
      inbox/            new downloads waiting to be filed
      requests/         convert__<pdf name without .pdf>.json, left by the app's "Make MusicXML" button
      pieces/<piece_id>/<piece_id>__<variant>.pdf
                        <piece_id>__<variant>.musicxml   (same name as its PDF, right beside it)
                        <piece_id>__<variant>.mscz       (optional: a MuseScore file; MusicXML and PDF are exported from it)
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
           "added", "notes", "year", "genre", "instrumentation", "level"]
# added later, so an older catalog.csv may not have them yet (it gets them the next time a row is added)
OPTIONAL = {"year", "genre", "instrumentation", "level"}
# piece metadata copied from a piece's first catalog row into library.json
PIECE_FIELDS = ("catalog_no", "key", "clefs", "positions", "notes", "year", "genre", "instrumentation", "level")
KINDS = {".pdf": "pdf", ".musicxml": "musicxml", ".mxl": "musicxml", ".xml": "musicxml"}
MUSESCORE = (".mscz", ".mscx")
INDEX_NAME = "library.json"
REQUESTS = "requests"
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
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or []) and c not in OPTIONAL]
            if missing:
                raise ValueError(f"catalog.csv is missing columns: {', '.join(missing)}")
            blank = dict.fromkeys(OPTIONAL, "")
            return [{**blank, **{k: (v or "").strip() for k, v in r.items() if k}} for r in reader]

    def write_catalog(self, rows: list[dict[str, str]]) -> None:
        """Rewrites catalog.csv with every column (BOM, so Excel reads accents right)."""
        tmp = self.catalog_path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(self.catalog_path)

    def append_catalog(self, rows: list[dict[str, str]]) -> None:
        """Adds rows to catalog.csv, first bringing an older file's header up to date so columns stay aligned."""
        if not rows:
            return
        if self.catalog_path.is_file():
            with self.catalog_path.open(newline="", encoding="utf-8-sig") as f:
                header = next(csv.reader(f), [])
            if header != COLUMNS:
                self.write_catalog(self.catalog() + rows)
                return
        new = not self.catalog_path.is_file()
        with self.catalog_path.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)

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
        kind = KINDS.get(src.suffix.lower()) or ("musescore" if src.suffix.lower() in MUSESCORE else None)
        if not kind:
            raise ValueError("only PDF, MusicXML and MuseScore files go in the library")
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
            row = {c: "" for c in COLUMNS}
            row.update(piece_id=piece_id, file=dest.name, variant=variant, pages=count_pages(dest),
                       added=datetime.date.today().isoformat())
            self.append_catalog([row])
        return dest

    # ---- the index ----

    def index(self) -> dict:
        """Everything the app needs to browse the library, built from the folders plus catalog.csv."""
        rows: dict[str, list[dict[str, str]]] = {}
        for r in self.catalog():
            rows.setdefault(r["piece_id"], []).append(r)
        requested = set(self.requests())
        failed = set(self.failed_requests())
        pieces = []
        for folder in self.folders():
            pid = folder.name
            if not ID_RE.match(pid):
                continue
            meta = rows.get(pid, [])
            first = meta[0] if meta else {}
            by_file = {r["file"]: r for r in meta}
            on_disk = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in KINDS)
            from_musescore = {p.stem for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MUSESCORE}
            xml_by_stem = {p.stem: p for p in on_disk if KINDS[p.suffix.lower()] == "musicxml"}
            files = []
            paired: set[str] = set()
            for p in on_disk:
                if KINDS[p.suffix.lower()] != "pdf":
                    continue
                entry = file_entry(p, by_file.get(p.name))
                xml = xml_by_stem.get(p.stem)
                if xml:
                    paired.add(xml.name)
                    entry["musicxml"] = xml.name
                    level = quality_level(folder / f"{p.stem}.quality.json")
                    if p.stem in from_musescore:
                        entry["from"] = "musescore"  # exported by MuseScore: exact, nothing to check
                    elif level:
                        entry["quality"] = level
                elif p.stem in requested:
                    entry["requested"] = True
                elif p.stem in failed:
                    entry["convert_failed"] = True
                files.append(entry)
            for x in xml_by_stem.values():  # MusicXML with no PDF beside it
                if x.name not in paired:
                    entry = file_entry(x, None)
                    level = quality_level(folder / f"{x.stem}.quality.json")
                    if x.stem in from_musescore:
                        entry["from"] = "musescore"
                    elif level:
                        entry["quality"] = level
                    files.append(entry)
            if not files:
                continue
            tags = sorted({t for r in meta for t in split_tags(r["tags"])})
            piece = {
                "id": pid,
                "title": first.get("title") or title_from_id(pid),
                "composer": first.get("composer") or composer_from_id(pid),
                "musicxml": any(f["kind"] == "musicxml" or "musicxml" in f for f in files),
                "files": files,
            }
            for k in PIECE_FIELDS:  # the first row that says, so a piano part's row can fill in what the cello part's lacks
                v = next((r[k] for r in meta if r.get(k)), "")
                if v:
                    piece[k] = v
            if tags:
                piece["tags"] = tags
            pieces.append(piece)
        return {
            "format": FORMAT,
            "version": VERSION,
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "pieces": pieces,
        }

    def requests(self) -> list[str]:
        """PDF names (without .pdf) the app asked to convert to MusicXML."""
        d = self.root / REQUESTS
        if not d.is_dir():
            return []
        return sorted({p.stem.removeprefix("convert__") for p in d.glob("convert__*.json")})

    def failed_requests(self) -> list[str]:
        """PDF names whose last conversion failed (set aside by the watcher or convert)."""
        d = self.root / REQUESTS
        return sorted({p.stem.removeprefix("failed__") for p in d.glob("failed__*.json")}) if d.is_dir() else []

    def clear_request(self, stem: str) -> None:
        (self.root / REQUESTS / f"failed__{stem}.json").unlink(missing_ok=True)
        (self.root / REQUESTS / f"convert__{stem}.json").unlink(missing_ok=True)

    def fail_request(self, stem: str) -> None:
        """Set a request aside after a failed conversion, so the watcher doesn't retry it forever.
        Queueing the PDF again from the app makes a fresh request."""
        src = self.root / REQUESTS / f"convert__{stem}.json"
        if src.is_file():
            src.replace(self.root / REQUESTS / f"failed__{stem}.json")

    def pdfs_without_musicxml(self) -> list[Path]:
        """PDFs with no MusicXML of the same name beside them."""
        out = []
        for folder in self.folders():
            if not ID_RE.match(folder.name):
                continue
            for pdf in sorted(folder.glob("*.pdf")):
                if not any((folder / f"{pdf.stem}{ext}").is_file() for ext in (".musicxml", ".mxl", ".xml")):
                    out.append(pdf)
        return out

    def musescore_files(self) -> list[Path]:
        """MuseScore files in piece folders whose MusicXML or PDF is missing or older than they are."""
        from lento_library.musescore import needs_export

        out = []
        for folder in self.folders():
            if ID_RE.match(folder.name):
                out += [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in MUSESCORE and needs_export(p)]
        return out

    def catalog_export(self, pdf: Path) -> None:
        """Adds a catalog row for a PDF exported from MuseScore, if it has none yet."""
        if any(r["file"] == pdf.name for r in self.catalog()):
            return
        row = {c: "" for c in COLUMNS}
        stem = pdf.stem
        row.update(piece_id=pdf.parent.name, file=pdf.name, variant=stem.split("__", 1)[1] if "__" in stem else "",
                   source="MuseScore", pages=count_pages(pdf), added=datetime.date.today().isoformat())
        self.append_catalog([row])

    def pdf_for(self, stem: str) -> Path | None:
        """The PDF called <stem>.pdf, in the piece folder its name starts with.

        Request names come from files anyone with write access to the Drive folder could create, so only a
        well-formed <piece_id>__<variant> is accepted, and the result must be a real file inside pieces/.
        """
        pid, _, variant = stem.partition("__")
        if not ID_RE.match(pid) or not VARIANT_RE.match(variant):
            return None
        p = self.pieces / pid / f"{stem}.pdf"
        try:
            inside = p.resolve().is_relative_to(self.pieces.resolve())
        except OSError:
            return None
        return p if inside and p.is_file() and not p.is_symlink() else None

    def fingerprint(self) -> tuple:
        """What library.json is built from (score files, catalog.csv, tags.md) with their sizes and modified times.
        The watcher compares it between looks, so files added, moved or renamed by hand are picked up."""
        files = [self.catalog_path, self.tags_path]
        for folder in self.folders():
            files += [p for p in folder.iterdir() if p.suffix.lower() in KINDS]
        out = []
        for p in files:
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((str(p.relative_to(self.root)), st.st_size, st.st_mtime_ns))
        return tuple(sorted(out))

    def write_index(self) -> tuple[Path, int]:
        data = self.index()
        path = self.root / INDEX_NAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)  # atomic, so Drive never syncs a half-written index
        return path, len(data["pieces"])


def file_entry(p: Path, row: dict[str, str] | None) -> dict:
    stem = p.name[: -len(p.suffix)]
    entry: dict = {"name": p.name, "kind": KINDS[p.suffix.lower()], "variant": stem.split("__", 1)[1] if "__" in stem else ""}
    if row:
        for k in ("edition", "source"):
            if row[k]:
                entry[k] = row[k]
        if row["pages"].isdigit():
            entry["pages"] = int(row["pages"])
    return entry


def quality_level(path: Path) -> str:
    """OK / REVIEW / UNRELIABLE from Lento_ConvertPDF's quality report, or blank."""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("level") or "")
    except (OSError, ValueError, AttributeError):
        return ""


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
