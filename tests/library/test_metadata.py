import csv
import json
from pathlib import Path

from lento_library import metadata
from lento_library.cli import main
from lento_library.library import COLUMNS, Library


def catalog(root: Path, rows: list[dict[str, str]], columns: list[str] = COLUMNS) -> None:
    for r in rows:
        folder = root / "pieces" / r["piece_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / r["file"]).write_bytes(b"%PDF")
    with (root / "catalog.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


OLD = COLUMNS[: COLUMNS.index("notes") + 1]  # a catalog.csv from before the new columns


def test_details_fills_matching_pieces_only_with_apply(tmp_path: Path) -> None:
    catalog(tmp_path, [
        {"piece_id": "lalo_cello-concerto-in-d-minor", "file": "lalo_cello-concerto-in-d-minor__cello.pdf", "variant": "cello",
         "composer": "Lalo, Edouard", "title": "Cello Concerto in D minor"},
        {"piece_id": "lalo_cello-concerto-in-d-minor", "file": "lalo_cello-concerto-in-d-minor__piano.pdf", "variant": "piano",
         "composer": "Lalo, Edouard", "title": "Cello Concerto in D minor"},
        {"piece_id": "tovey_elegiac-variations_op25", "file": "tovey_elegiac-variations_op25__cello.pdf", "variant": "cello",
         "composer": "Tovey, Donald Francis", "title": "Elegiac Variations, Op. 25"},
        {"piece_id": "nobody_something", "file": "nobody_something__score.pdf", "variant": "score", "composer": "Nobody, A", "title": "Something"},
    ], OLD)
    sheet = tmp_path / "sheet.csv"
    sheet.write_text(
        "Composer,Score Name,Year Written,Genre / Era,Instrumentation / Ensemble,PDF Link\n"
        "Édouard Lalo,Cello Concerto in D minor (Cello Part),1877,Romantic,Cello & Orchestra (Piano Reduction),Open PDF\n"
        "Donald Francis Tovey,\"Elegiac Variations, Op.25 (Piano Score)\",Unknown,Classical / Romantic,Duet (Cello & Piano),Open PDF\n"
        "Someone Else,Something,1900,Baroque,Solo Cello,Open PDF\n",
        encoding="utf-8",
    )
    assert main(["details", str(sheet), "--root", str(tmp_path)]) == 0
    assert "year" not in (tmp_path / "catalog.csv").read_text(encoding="utf-8")  # dry run: nothing written
    report = {r["piece_id"]: r for r in csv.DictReader((tmp_path / metadata.REPORT).open(encoding="utf-8-sig"))}
    assert report["nobody_something"]["filled"] == ""  # a different composer never matches
    assert main(["details", str(sheet), "--root", str(tmp_path), "--apply"]) == 0
    rows = Library(tmp_path).catalog()
    lalo = [r for r in rows if r["piece_id"].startswith("lalo")]
    assert all(r["year"] == "1877" and r["genre"] == "Romantic" and r["instrumentation"].startswith("Cello & Orchestra") for r in lalo)
    tovey = next(r for r in rows if r["piece_id"].startswith("tovey"))
    assert tovey["year"] == "" and tovey["genre"] == "Classical / Romantic"  # "Unknown" is left empty
    pieces = {p["id"]: p for p in json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["pieces"]}
    assert pieces["lalo_cello-concerto-in-d-minor"]["genre"] == "Romantic"
    assert pieces["lalo_cello-concerto-in-d-minor"]["year"] == "1877"
    assert "genre" not in pieces["nobody_something"]


def test_details_keeps_existing_values_and_reads_the_progression_layout(tmp_path: Path) -> None:
    catalog(tmp_path, [
        {"piece_id": "bach-js_minuet-in-c", "file": "bach-js_minuet-in-c__score.pdf", "variant": "score",
         "composer": "Bach, Johann Sebastian", "title": "Minuet in C", "genre": "Baroque (mine)"},
    ])
    sheet = tmp_path / "prog.csv"
    sheet.write_text("#,Phase / Level,Composer & Piece Title,Techniques\n2,Phase 1: Beginner,J.S. Bach - Minuet in C,bowing\n", encoding="utf-8")
    lib = Library(tmp_path)
    rows, report, changed = metadata.match(lib, metadata.read_sheet(sheet))
    assert changed == 1 and rows[0]["level"] == "Phase 1: Beginner" and rows[0]["genre"] == "Baroque (mine)"


def test_adding_to_an_old_catalog_upgrades_its_header(tmp_path: Path) -> None:
    catalog(tmp_path, [{"piece_id": "a_b", "file": "a_b__score.pdf", "variant": "score", "composer": "A, B", "title": "B"}], OLD)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "new.pdf").write_bytes(b"%PDF")
    Library(tmp_path).add(tmp_path / "inbox" / "new.pdf", "a_c", "score")
    with (tmp_path / "catalog.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == COLUMNS and [r["file"] for r in rows] == ["a_b__score.pdf", "a_c__score.pdf"]
    assert rows[0]["title"] == "B"
