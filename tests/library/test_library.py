from __future__ import annotations

import csv
import json
from pathlib import Path

from lento_library.cli import main
from lento_library.library import COLUMNS, Library


def make_library(root: Path) -> None:
    (root / "pieces" / "bach_cello-suite-1-prelude_bwv1007").mkdir(parents=True)
    (root / "pieces" / "saint-saens_the-swan").mkdir(parents=True)
    (root / "pieces" / "empty_piece").mkdir(parents=True)
    (root / "pieces" / "Bad Folder").mkdir(parents=True)
    p = root / "pieces" / "bach_cello-suite-1-prelude_bwv1007"
    (p / "bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf").write_bytes(b"%PDF /Type /Page /Type /Page")
    (p / "bach_cello-suite-1-prelude_bwv1007.musicxml").write_text("<score-partwise/>")
    (p / "notes.txt").write_text("ignored")
    (root / "pieces" / "saint-saens_the-swan" / "saint-saens_the-swan__imslp.mxl").write_bytes(b"PK")
    (root / "tags.md").write_text("- shifting\n- vibrato\n- string-crossings\n")
    with (root / "catalog.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        row = {c: "" for c in COLUMNS}
        row.update(piece_id="bach_cello-suite-1-prelude_bwv1007", file="bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf",
                   variant="barenreiter", composer="J. S. Bach", title="Cello Suite No. 1: Prelude", catalog_no="BWV 1007",
                   edition="Bärenreiter", pages="2", key="G major", tags="string-crossings; shifting")
        w.writerow(row)


def test_index_combines_folders_and_catalog(tmp_path: Path) -> None:
    make_library(tmp_path)
    data = Library(tmp_path).index()
    assert data["format"] == "lento-library" and data["version"] == 1
    ids = [p["id"] for p in data["pieces"]]
    assert ids == ["bach_cello-suite-1-prelude_bwv1007", "saint-saens_the-swan"]  # empty and invalid folders left out
    bach, swan = data["pieces"]
    assert bach["title"] == "Cello Suite No. 1: Prelude" and bach["composer"] == "J. S. Bach"
    assert bach["tags"] == ["shifting", "string-crossings"]
    assert [(f["name"], f["kind"]) for f in bach["files"]] == [
        ("bach_cello-suite-1-prelude_bwv1007.musicxml", "musicxml"),
        ("bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf", "pdf"),
    ]
    assert bach["files"][1]["edition"] == "Bärenreiter" and bach["files"][1]["pages"] == 2
    # uncatalogued pieces still appear, with a readable name from the id
    assert swan["title"] == "The swan" and swan["composer"] == "Saint-Saens"
    assert swan["files"][0]["variant"] == "imslp"


def test_build_writes_json(tmp_path: Path, capsys) -> None:
    make_library(tmp_path)
    assert main(["build", "--root", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert len(data["pieces"]) == 2
    assert "2 pieces" in capsys.readouterr().out


def test_check_and_add(tmp_path: Path) -> None:
    make_library(tmp_path)
    lib = Library(tmp_path)
    rep = lib.check({"bach_cello-suite-1-prelude_bwv1007", "faure_elegie_op24"})
    assert any("Bad Folder" in p for p in rep.problems)
    assert any("faure_elegie_op24: on the practice list" in n for n in rep.notes)
    (tmp_path / "inbox").mkdir()
    src = tmp_path / "inbox" / "download.pdf"
    src.write_bytes(b"%PDF /Type /Page")
    dest = lib.add(src, "faure_elegie_op24", "imslp")
    assert dest == tmp_path / "pieces" / "faure_elegie_op24" / "faure_elegie_op24__imslp.pdf"
    assert lib.catalog()[-1]["file"] == dest.name and lib.catalog()[-1]["pages"] == "1"
