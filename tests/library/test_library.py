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
    (p / "bach_cello-suite-1-prelude_bwv1007__barenreiter.musicxml").write_text("<score-partwise/>")
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
    # the MusicXML beside a PDF (same name) is attached to it, not listed on its own
    assert bach["files"] == [{
        "name": "bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf", "kind": "pdf", "variant": "barenreiter",
        "edition": "Bärenreiter", "pages": 2, "musicxml": "bach_cello-suite-1-prelude_bwv1007__barenreiter.musicxml",
    }]
    assert bach["musicxml"] is True and swan["musicxml"] is True
    assert swan["files"][0]["kind"] == "musicxml"  # MusicXML with no PDF is listed on its own
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


def test_musicxml_flag_quality_and_requests(tmp_path: Path) -> None:
    make_library(tmp_path)
    bach = tmp_path / "pieces" / "bach_cello-suite-1-prelude_bwv1007"
    (bach / "bach_cello-suite-1-prelude_bwv1007__barenreiter.quality.json").write_text(json.dumps({"level": "REVIEW"}))
    faure = tmp_path / "pieces" / "faure_elegie_op24"
    faure.mkdir()
    (faure / "faure_elegie_op24__imslp.pdf").write_bytes(b"%PDF")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "convert__faure_elegie_op24__imslp.json").write_text("{}")
    lib = Library(tmp_path)
    pieces = {p["id"]: p for p in lib.index()["pieces"]}
    assert pieces["bach_cello-suite-1-prelude_bwv1007"]["musicxml"] is True
    assert pieces["bach_cello-suite-1-prelude_bwv1007"]["files"][0]["quality"] == "REVIEW"
    assert pieces["faure_elegie_op24"]["musicxml"] is False
    assert pieces["faure_elegie_op24"]["files"][0]["requested"] is True
    assert [p.name for p in lib.pdfs_without_musicxml()] == ["faure_elegie_op24__imslp.pdf"]


def test_convert_runs_the_converter_and_clears_requests(tmp_path: Path) -> None:
    make_library(tmp_path)
    faure = tmp_path / "pieces" / "faure_elegie_op24"
    faure.mkdir()
    (faure / "faure_elegie_op24__imslp.pdf").write_bytes(b"%PDF")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "convert__faure_elegie_op24__imslp.json").write_text("{}")
    # a stand-in converter: writes <pdf stem>.musicxml next to each PDF in the folder it is given
    fake = tmp_path / "fake_convert.py"
    fake.write_text(
        "import sys, pathlib\n"
        "for p in pathlib.Path(sys.argv[1]).glob('*.pdf'):\n"
        "    p.with_suffix('.musicxml').write_text('<score-partwise/>')\n"
    )
    import sys as _sys
    assert main(["convert", "--root", str(tmp_path), "--converter", f'"{_sys.executable}" "{fake}"']) == 0
    assert (faure / "faure_elegie_op24__imslp.musicxml").is_file()
    assert not (tmp_path / "requests" / "convert__faure_elegie_op24__imslp.json").exists()
    data = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert {p["id"]: p["musicxml"] for p in data["pieces"]}["faure_elegie_op24"] is True


def test_watch_once_converts_queue_and_reports_status(tmp_path: Path) -> None:
    import sys as _sys

    make_library(tmp_path)
    for pid in ("faure_elegie_op24", "fail_piece"):
        (tmp_path / "pieces" / pid).mkdir()
        (tmp_path / "pieces" / pid / f"{pid}__imslp.pdf").write_bytes(b"%PDF")
    (tmp_path / "requests").mkdir()
    for pid in ("faure_elegie_op24", "fail_piece", "gone_piece"):
        (tmp_path / "requests" / f"convert__{pid}__imslp.json").write_text("{}")
    # converts every PDF except those in a folder named fail_piece
    fake = tmp_path / "fake_convert.py"
    fake.write_text(
        "import sys, pathlib\n"
        "d = pathlib.Path(sys.argv[1])\n"
        "if d.name != 'fail_piece':\n"
        "    for p in d.glob('*.pdf'): p.with_suffix('.musicxml').write_text('<score-partwise/>')\n"
    )
    cmd = f'"{_sys.executable}" "{fake}"'
    assert main(["watch", "--root", str(tmp_path), "--once", "--converter", cmd]) == 0
    req = tmp_path / "requests"
    assert not list(req.glob("convert__*.json"))  # nothing left to retry
    assert (req / "failed__fail_piece__imslp.json").is_file()
    assert (req / "failed__gone_piece__imslp.json").is_file()  # its PDF doesn't exist
    status = json.loads((req / "_status.json").read_text(encoding="utf-8"))
    assert status["state"] == "idle" and status["heartbeat"]
    assert {r["pdf"]: r["ok"] for r in status["results"]} == {
        "gone_piece__imslp.pdf": False,
        "faure_elegie_op24__imslp.pdf": True,
        "fail_piece__imslp.pdf": False,
    }
    pieces = {p["id"]: p for p in json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["pieces"]}
    assert pieces["faure_elegie_op24"]["musicxml"] is True
    assert pieces["fail_piece"]["files"][0]["convert_failed"] is True
    # queueing it again from the app makes a fresh request; a success clears the failure too
    (req / "convert__fail_piece__imslp.json").write_text("{}")
    (tmp_path / "pieces" / "fail_piece" / "fail_piece__imslp.musicxml").write_text("<score-partwise/>")
    assert main(["watch", "--root", str(tmp_path), "--once", "--converter", cmd]) == 0
    assert not (req / "failed__fail_piece__imslp.json").exists()
