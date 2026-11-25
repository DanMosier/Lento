"""Fills catalog.csv's piece details (year, genre, instrumentation, level) from a spreadsheet exported as CSV.

Made for Daniel's catalog sheet (Composer, Score Name, Year Written, Genre / Era, Instrumentation / Ensemble) and his
progression list (Phase / Level, "Composer & Piece Title"), but any sheet with a composer and a title column works.
Each piece is matched by the composer's surname and the closest title; only empty fields are filled, unless told
to overwrite. Nothing is written without --apply, and a report of every match is saved either way.
"""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from lento_library.library import Library

REPORT = "catalog-import-report.csv"
# sheet header (lowercase, spaces squeezed) -> catalog field
FIELDS = {
    "year written": "year", "year": "year", "composed": "year",
    "genre / era": "genre", "genre": "genre", "era": "genre", "period": "genre",
    "instrumentation / ensemble": "instrumentation", "instrumentation": "instrumentation", "ensemble": "instrumentation",
    "phase / level": "level", "level": "level", "difficulty": "level", "grade": "level",
}
COMPOSER = ("composer", "artist")
TITLE = ("score name", "title", "piece", "piece title", "name")
BOTH = ("composer & piece title", "composer and piece title", "piece")  # "J.S. Bach - Minuet in C"
BLANK = {"", "unknown", "n/a", "na", "-", "?"}
MIN_SCORE = 0.82


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def title_key(s: str) -> str:
    """The title without the part it is ("(Cello Part)", "Piano Score") or noise words, for comparing."""
    s = re.sub(r"\((cello|piano|violoncello)[^)]*\)|\((full )?score\)|\bp\s*&\s*c\b", " ", s, flags=re.IGNORECASE)
    s = fold(s)
    s = re.sub(r"\b(cello|piano) (part|score)$", "", s).strip()
    s = re.sub(r"\bop (\d)", r"op\1", s)
    s = re.sub(r"\bno (\d)", r"no\1", s)
    return s


def surname(composer: str) -> str:
    """'Bach, Johann Sebastian' and 'Johann Sebastian Bach' -> 'bach'; 'J.S. Bach' -> 'bach'."""
    c = composer.strip()
    last = c.split(",")[0] if "," in c else (c.split()[-1] if c.split() else "")
    return fold(last).replace(" ", "-")


@dataclass
class Row:
    composer: str
    title: str
    values: dict[str, str]


def read_sheet(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        keys = [re.sub(r"\s+", " ", h.strip().lower()) for h in header]

        def col(names: tuple[str, ...]) -> int | None:
            return next((keys.index(n) for n in names if n in keys), None)

        ci, ti, bi = col(COMPOSER), col(TITLE), col(BOTH)
        if (ci is None or ti is None) and bi is None:
            raise ValueError(f"{path.name}: needs a Composer and a Title (or 'Composer & Piece Title') column")
        mapped = {i: FIELDS[k] for i, k in enumerate(keys) if k in FIELDS}
        if not mapped:
            raise ValueError(f"{path.name}: no column to import (looked for {', '.join(sorted(set(FIELDS)))})")
        rows = []
        for r in reader:
            cell = lambda i: r[i].strip() if i is not None and i < len(r) else ""  # noqa: E731
            if ci is not None and ti is not None and cell(ci) and cell(ti):
                comp, title = cell(ci), cell(ti)
            elif bi is not None and " - " in cell(bi):
                comp, title = (x.strip() for x in cell(bi).split(" - ", 1))
            else:
                continue
            values = {f: cell(i) for i, f in mapped.items() if cell(i).lower() not in BLANK}
            if values:
                rows.append(Row(comp, title, values))
        return rows


def match(lib: Library, sheet: list[Row], overwrite: bool = False) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
    """Returns (updated catalog rows, report rows, pieces changed)."""
    catalog = lib.catalog()
    by_surname: dict[str, list[Row]] = {}
    for r in sheet:
        by_surname.setdefault(surname(r.composer), []).append(r)
    pieces: dict[str, list[dict[str, str]]] = {}
    for r in catalog:
        pieces.setdefault(r["piece_id"], []).append(r)
    report, changed = [], 0
    for pid, rows in pieces.items():
        comp = next((r["composer"] for r in rows if r["composer"]), "")
        sur = surname(comp) if comp else pid.split("_")[0].split("-")[0]
        cands = by_surname.get(sur, [])
        titles = {title_key(r["title"]) for r in rows if r["title"]} or {title_key(pid.split("_", 1)[-1].replace("-", " "))}
        best, score = None, 0.0
        for c in cands:
            ck = title_key(c.title)
            s = max(difflib.SequenceMatcher(None, ck, t).ratio() for t in titles)
            if s > score:
                best, score = c, s
        line = {"piece_id": pid, "composer": comp, "title": rows[0]["title"], "sheet_composer": "", "sheet_title": "", "score": "", "filled": ""}
        if best and score >= MIN_SCORE:
            line.update(sheet_composer=best.composer, sheet_title=best.title, score=f"{score:.2f}")
            filled = []
            for r in rows:
                for f, v in best.values.items():
                    if overwrite or not r.get(f):
                        if r.get(f) != v:
                            r[f] = v
                            if f not in filled:
                                filled.append(f)
            line["filled"] = " ".join(filled)
            changed += bool(filled)
        elif best:
            line.update(sheet_composer=best.composer, sheet_title=best.title, score=f"{score:.2f}", filled="(too different, skipped)")
        report.append(line)
    return catalog, report, changed


def run(lib: Library, sheet_path: Path, apply: bool = False, overwrite: bool = False) -> int:
    sheet = read_sheet(sheet_path)
    catalog, report, changed = match(lib, sheet, overwrite)
    out = lib.root / REPORT
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0]) if report else ["piece_id"])
        w.writeheader()
        w.writerows(report)
    matched = sum(1 for r in report if r["score"] and not r["filled"].startswith("("))
    print(f"{len(sheet)} sheet rows; {matched} of {len(report)} pieces matched; {changed} would get new details. Report: {out}")
    if apply and changed:
        lib.write_catalog(catalog)
        _, n = lib.write_index()
        print(f"catalog.csv updated; library.json rebuilt ({n} pieces)")
    elif changed:
        print("Nothing written yet. Look over the report, then run again with --apply.")
    return 0
