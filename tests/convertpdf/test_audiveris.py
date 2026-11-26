"""Tests for the Audiveris integration, with a stand-in for the Audiveris program."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from lento_convertpdf import audiveris_runner
from lento_convertpdf.audiveris_runner import check_audiveris, discover_audiveris
from lento_convertpdf.homr_runner import OMRConfig
from lento_convertpdf.models import PdfConversionItem
from lento_convertpdf.omr_engines import batch_convert_pdfs, convert_single_pdf

NOTE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>"


def score(name: str = "", staves: int = 1, notes: str = NOTE) -> str:
    staves_el = f"<staves>{staves}</staves>" if staves > 1 else ""
    return (
        "<score-partwise version='4.0'><part-list><score-part id='P1'>"
        f"<part-name>{name}</part-name></score-part></part-list><part id='P1'><measure number='1'>"
        f"<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time>{staves_el}</attributes>"
        f"{notes}</measure></part></score-partwise>"
    )


def mxl(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            "<container><rootfiles><rootfile full-path='score.xml'/></rootfiles></container>",
        )
        zf.writestr("score.xml", xml)
    return buf.getvalue()


@pytest.fixture
def fake_audiveris(monkeypatch, tmp_path):
    """Replace the Audiveris program: fake(files={relative name: bytes}, returncode, log)."""
    exe = tmp_path / "Audiveris.exe"
    exe.write_bytes(b"")
    calls: list[list[str]] = []

    def install(files: dict[str, bytes] | None = None, returncode: int = 0, log: str = ""):
        def run(path, args, cwd, timeout):
            calls.append(args)
            if "-output" in args:
                out = Path(args[args.index("-output") + 1])
                for name, data in (files or {}).items():
                    (out / name).parent.mkdir(parents=True, exist_ok=True)
                    (out / name).write_bytes(data)
            return returncode, log

        monkeypatch.setattr(audiveris_runner, "_run", run)
        return OMRConfig(engine="audiveris", audiveris_path=str(exe)), calls

    return install


def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "piece.pdf"
    path.write_bytes(b"%PDF-1.4 stand-in")
    return path


def test_converts_and_unpacks_the_mxl(fake_audiveris, tmp_path):
    config, calls = fake_audiveris({"score/score.mxl": mxl(score())})
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted", item.error_message
    assert item.engine_used == "audiveris"
    out = tmp_path / "piece.musicxml"
    assert item.output_musicxml_path == out and out.is_file()
    assert calls[-1][:4] == ["-batch", "-transcribe", "-export", "-output"]
    assert item.detected_instruments == ["Cello"]  # one unnamed staff takes the default instrument
    assert item.quality is not None and item.quality.symbol_confidence is None


def test_unnamed_piano_part_is_not_renamed(fake_audiveris, tmp_path):
    config, _ = fake_audiveris({"score.mxl": mxl(score(staves=2))})
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted", item.error_message
    root = ET.parse(tmp_path / "piece.musicxml").getroot()
    assert (root.findtext("part-list/score-part/part-name") or "") == ""


def test_nothing_written_is_a_failure_and_keeps_the_old_file(fake_audiveris, tmp_path):
    config, _ = fake_audiveris({}, returncode=1, log="INFO start\nERROR Could not load sheet\n")
    old = tmp_path / "piece.musicxml"
    old.write_text("earlier", encoding="utf-8")
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed"
    assert "Could not load sheet" in item.error_message
    assert old.read_text(encoding="utf-8") == "earlier"


def test_score_without_notes_fails(fake_audiveris, tmp_path):
    config, _ = fake_audiveris({"score.mxl": mxl(score(notes=""))})
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed" and "Audiveris produced a score without any notes" in item.error_message


def test_movements_keep_the_first_and_flag_it(fake_audiveris, tmp_path):
    config, _ = fake_audiveris({"score.mvt1.mxl": mxl(score()), "score.mvt2.mxl": mxl(score())})
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted"
    assert item.quality is not None and item.quality.level != "good"
    assert any("2 movements" in p for p in item.quality.problems)


def test_batch_checks_audiveris_once(fake_audiveris, tmp_path, monkeypatch):
    config, calls = fake_audiveris({"score.mxl": mxl(score())})
    items = []
    for name in ("a", "b"):
        p = tmp_path / f"{name}.pdf"
        p.write_bytes(b"%PDF-1.4")
        items.append(PdfConversionItem(pdf_path=p, relative_path=p.name))
    batch_convert_pdfs(items, config)
    assert [i.status for i in items] == ["converted", "converted"]
    assert sum(1 for c in calls if "-version" in c) == 1


def test_missing_audiveris_fails_clearly(tmp_path):
    config = OMRConfig(engine="audiveris", audiveris_path=str(tmp_path / "nope.exe"))
    assert discover_audiveris(config.audiveris_path) is None
    status = check_audiveris(config)
    assert not status.installed and "not found" in status.details
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed" and "not found" in item.error_message


def test_version_is_reported(fake_audiveris):
    config, _ = fake_audiveris(log="Audiveris version 5.11.0\n")
    status = check_audiveris(config)
    assert status.installed and "5.11.0" in status.details and not status.cuda


def test_page_image_is_passed_on_as_an_image(fake_audiveris, tmp_path):
    config, calls = fake_audiveris({"score.mxl": mxl(score())})
    photo = tmp_path / "01.jpg"
    photo.write_bytes(b"\xff\xd8 stand-in")
    item = convert_single_pdf(PdfConversionItem(pdf_path=photo, relative_path="01.jpg"), config)
    assert item.status == "converted", item.error_message
    assert calls[-1][-1].endswith("score.jpg")
    assert (tmp_path / "01.musicxml").is_file()


def test_audiveris_folder_beside_the_project_is_found(monkeypatch, tmp_path):
    exe = tmp_path / "Audiveris" / "Audiveris.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.delenv("AUDIVERIS", raising=False)
    monkeypatch.setattr(audiveris_runner, "__file__", str(tmp_path / "Lento" / "lento_convertpdf" / "audiveris_runner.py"))
    monkeypatch.setattr(audiveris_runner.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert discover_audiveris() == exe


def test_page_without_staves_is_left_out_on_a_second_try(monkeypatch, tmp_path):
    exe = tmp_path / "Audiveris.exe"
    exe.write_bytes(b"")
    calls: list[list[str]] = []

    def run(path, args, cwd, timeout):
        calls.append(args)
        if "-sheets" in args:
            out = Path(args[args.index("-output") + 1])
            (out / "score.mxl").write_bytes(mxl(score()))
            return 0, ""
        return 1, "java.lang.Exception: Error in reaching step PAGE"

    monkeypatch.setattr(audiveris_runner, "_run", run)
    monkeypatch.setattr(audiveris_runner, "pages_with_staves", lambda _pdf: (3, [1, 2]))
    config = OMRConfig(engine="audiveris", audiveris_path=str(exe))
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted", item.error_message
    assert calls[-1][calls[-1].index("-sheets") + 1 : calls[-1].index("--")] == ["1", "2"]
    assert item.quality is not None and any("page 3 had no staves" in p for p in item.quality.problems)


def test_version_ignores_other_log_lines(fake_audiveris):
    config, _ = fake_audiveris(log="INFO [] TesseractOCR 137 | Creating OCR folder\nAudiveris 5.11.0\n")
    assert "Audiveris 5.11.0" in check_audiveris(config).details
