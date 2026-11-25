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


def test_request_names_cannot_point_outside_pieces(tmp_path: Path) -> None:
    make_library(tmp_path)
    lib = Library(tmp_path)
    (tmp_path / "evil__x.pdf").write_bytes(b"%PDF")  # in the library root, not a piece folder
    for stem in ["..__x", "../evil__x", "..\\\\evil__x", "bach_cello-suite-1-prelude_bwv1007__../../evil", "Bad Folder__x", ""]:
        assert lib.pdf_for(stem) is None, stem
    assert lib.pdf_for("bach_cello-suite-1-prelude_bwv1007__barenreiter") is not None


def fake_musescore(tmp_path: Path, broken: str = "") -> str:
    """A stand-in for MuseScore's command line: reads the -j job file and writes each output."""
    script = tmp_path / "fake_mscore.py"
    script.write_text(
        "import json, sys\n"
        "job = json.load(open(sys.argv[sys.argv.index('-j') + 1]))\n"
        "for j in job:\n"
        f"    if {broken!r} and j['in'].endswith({broken!r}): continue\n"
        "    for out in j['out']:\n"
        "        open(out, 'wb').write(b'%PDF /Type /Page' if out.endswith('.pdf') else b'<score-partwise/>')\n"
    )
    import os
    import stat
    import sys as _sys

    exe = tmp_path / "mscore"
    exe.write_text(f"#!/bin/sh\nexec {_sys.executable} {script} \"$@\"\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def test_musescore_files_export_to_musicxml_and_pdf(tmp_path: Path, capsys) -> None:
    import os
    import time

    make_library(tmp_path)
    swan = tmp_path / "pieces" / "saint-saens_the-swan"
    (swan / "saint-saens_the-swan__mine.mscz").write_bytes(b"PK")
    (swan / "saint-saens_the-swan__broken.mscz").write_bytes(b"PK")
    lib = Library(tmp_path)
    assert [p.name for p in lib.musescore_files()] == ["saint-saens_the-swan__broken.mscz", "saint-saens_the-swan__mine.mscz"]

    exe = fake_musescore(tmp_path, broken="broken.mscz")
    assert main(["convert", "--root", str(tmp_path), "--musescore", exe]) == 1  # one failed
    assert (swan / "saint-saens_the-swan__mine.musicxml").is_file() and (swan / "saint-saens_the-swan__mine.pdf").is_file()
    out = capsys.readouterr().out
    assert "1 exported, 1 failed" in out and "failed: saint-saens_the-swan__broken.mscz" in out

    # the index marks the export as MuseScore's (exact: no quality badge), and the catalog has a row for the PDF
    data = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    swan_files = next(p for p in data["pieces"] if p["id"] == "saint-saens_the-swan")["files"]
    mine = next(f for f in swan_files if f["name"] == "saint-saens_the-swan__mine.pdf")
    assert mine["musicxml"] == "saint-saens_the-swan__mine.musicxml" and mine["from"] == "musescore" and "quality" not in mine
    assert any(r["file"] == "saint-saens_the-swan__mine.pdf" and r["source"] == "MuseScore" for r in lib.catalog())
    assert not any(".mscz" in f["name"] for f in swan_files)

    # up to date now; changing the MuseScore file exports it again
    assert [p.name for p in lib.musescore_files()] == ["saint-saens_the-swan__broken.mscz"]
    later = time.time() + 5
    os.utime(swan / "saint-saens_the-swan__mine.mscz", (later, later))
    assert "saint-saens_the-swan__mine.mscz" in [p.name for p in lib.musescore_files()]


def test_musescore_missing_is_reported(tmp_path: Path, capsys, monkeypatch) -> None:
    from lento_library import musescore, watch

    make_library(tmp_path)
    (tmp_path / "pieces" / "saint-saens_the-swan" / "saint-saens_the-swan__mine.mscz").write_bytes(b"PK")
    monkeypatch.setattr(musescore, "find", lambda explicit=None: None)
    assert watch.run(Library(tmp_path), ["true"], "no", interval=0, once=True) == 0
    status = json.loads((tmp_path / "requests" / "_status.json").read_text(encoding="utf-8"))
    assert status["musescore"] is False
    assert status["results"][-1] == {"pdf": "saint-saens_the-swan__mine.mscz", "ok": False, "at": status["results"][-1]["at"]}
    assert "MuseScore isn't installed" in capsys.readouterr().out


def test_watch_rebuilds_index_when_files_change_by_hand(tmp_path: Path, monkeypatch) -> None:
    from lento_library import watch

    make_library(tmp_path)
    lib = Library(tmp_path)
    index = tmp_path / "library.json"
    pieces = lambda: [p["id"] for p in json.loads(index.read_text(encoding="utf-8"))["pieces"]]
    looks = []

    def sleep(_s: float) -> None:  # between looks: check, then change the folder by hand
        looks.append(pieces() if index.exists() else None)
        if len(looks) == 1:
            folder = tmp_path / "pieces" / "bach_suite-1_prelude"
            folder.mkdir()
            (folder / "bach_suite-1_prelude__urtext.pdf").write_bytes(b"%PDF-1.4\n")
        elif len(looks) == 2:
            index.unlink()  # nothing changed, so the next look must not write it again
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr(watch.time, "sleep", sleep)
    assert watch.run(lib, ["true"], "no", interval=0) == 0
    assert "bach_suite-1_prelude" not in looks[0]  # built on the first look
    assert "bach_suite-1_prelude" in looks[1]  # rebuilt after the hand-made change
    assert not index.exists()


def test_runs_as_a_module(tmp_path: Path) -> None:
    import subprocess
    import sys

    make_library(tmp_path)
    out = subprocess.run([sys.executable, "-m", "lento_library", "build", "--root", str(tmp_path)], capture_output=True, text=True,
                         cwd=Path(__file__).parents[2])
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "library.json").exists()


def test_run_converter_reports_each_pdf_and_ticks(tmp_path: Path) -> None:
    import sys as _sys

    from lento_library.cli import run_converter

    fake = tmp_path / "fake.py"
    fake.write_text(
        "import time\n"
        "print('Found 2 PDF file(s)', flush=True)\n"
        "time.sleep(0.3)\n"
        "print('[1/2] CONVERTED: a__x.pdf -> a__x.musicxml (12.5s)', flush=True)\n"
        "print('      quality: good \\u266f', flush=True)\n"
        "print('[2/2] FAILED: b__x.pdf -> homr could not read page 1 (3.0s)', flush=True)\n"
    )
    lines, ticks = [], []
    code = run_converter([_sys.executable, str(fake)], lambda *a: lines.append(a), lambda: ticks.append(1), tick=0.1)
    assert code == 0
    assert lines == [("a__x.pdf", "converted", 12.5), ("b__x.pdf", "failed", 3.0)]
    assert ticks  # the heartbeat kept going while it worked


def test_batch_status_shows_current_next_and_progress(tmp_path: Path) -> None:
    from lento_library import watch

    make_library(tmp_path)
    status = watch.Status(Library(tmp_path), 30)
    pdfs = [tmp_path / "pieces" / f / f"{f}__x.pdf" for f in ("a", "a", "b")]
    pdfs[1] = pdfs[1].with_name("a__y.pdf")
    batch = watch.Batch(status, pdfs)
    def read() -> dict:
        return json.loads(status.path.read_text(encoding="utf-8"))

    batch.folder(1, 2, pdfs[0].parent, pdfs[:2])
    s = read()
    assert s["state"] == "converting" and s["current_files"] == ["a__x.pdf", "a__y.pdf"] and s["queue"] == ["b__x.pdf"]
    assert s["batch"]["total"] == 3 and s["batch"]["done"] == 0 and s["started"]
    batch.line("a__x.pdf", "converted", 40.0)
    batch.line("other__z.pdf", "converted", 5.0)  # a sibling nobody asked for doesn't count
    s = read()
    assert s["current_files"] == ["a__y.pdf"] and s["batch"]["done"] == 1
    batch.line("a__y.pdf", "converted", 60.0)
    batch.folder(2, 2, pdfs[2].parent, pdfs[2:])
    assert read()["queue"] == [] and read()["current_files"] == ["b__x.pdf"]
    batch.finish({"b__x.pdf"})
    status.write("idle", [])
    s = read()
    assert "batch" not in s and "current_files" not in s
    assert [(r["pdf"], r["ok"], r.get("seconds")) for r in s["results"]] == [("a__x.pdf", True, 40.0), ("a__y.pdf", True, 60.0), ("b__x.pdf", False, None)]
    assert s["avg_s"] == 60.0  # median of the converted ones


def test_watch_skips_pdfs_removed_from_the_queue_before_their_turn(tmp_path: Path) -> None:
    import sys as _sys

    from lento_library import watch

    make_library(tmp_path)
    req = tmp_path / "requests"
    req.mkdir()
    for pid in ("a_first", "b_second"):
        (tmp_path / "pieces" / pid).mkdir()
        (tmp_path / "pieces" / pid / f"{pid}__x.pdf").write_bytes(b"%PDF")
        (req / f"convert__{pid}__x.json").write_text("{}")
    # converting the first folder removes the second one's request, as the app would while it waits
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import sys, pathlib\n"
        "d = pathlib.Path(sys.argv[1])\n"
        "(d.parent.parent / 'requests' / 'convert__b_second__x.json').unlink(missing_ok=True)\n"
        "for p in d.glob('*.pdf'): p.with_suffix('.musicxml').write_text('<score-partwise/>')\n"
    )
    assert watch.run(Library(tmp_path), [_sys.executable, str(fake)], "no", interval=0, once=True) == 0
    assert (tmp_path / "pieces" / "a_first" / "a_first__x.musicxml").is_file()
    assert not (tmp_path / "pieces" / "b_second" / "b_second__x.musicxml").exists()
    assert not (req / "failed__b_second__x.json").exists()  # removed, not failed
    status = json.loads((req / "_status.json").read_text(encoding="utf-8"))
    assert [r["pdf"] for r in status["results"]] == ["a_first__x.pdf"]
    pieces = {p["id"]: p for p in json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["pieces"]}
    assert not pieces["b_second"]["files"][0].get("requested")


def test_fingerprint_changes_when_a_request_is_removed(tmp_path: Path) -> None:
    make_library(tmp_path)
    (tmp_path / "requests").mkdir()
    r = tmp_path / "requests" / "convert__x__y.json"
    r.write_text("{}")
    lib = Library(tmp_path)
    before = lib.fingerprint()
    r.unlink()
    assert lib.fingerprint() != before
