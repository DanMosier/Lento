"""Tests for the homr integration.

Fast tests use a stand-in for the subprocess call and check that failures stay failures.
Tests marked homr_gpu run the real homr on the GPU:  pytest -m homr_gpu
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pypdf
import pytest
from compare_musicxml import compare, load, report

from lento_convertpdf import homr_runner
from lento_convertpdf.homr_runner import EngineAvailability, OMRConfig, check_homr, discover_homr_python
from lento_convertpdf.models import PdfConversionItem
from lento_convertpdf.omr_engines import batch_convert_pdfs, convert_single_pdf

FIXTURES = Path(__file__).parent.parent / "fixtures"
BASELINES = json.loads((FIXTURES / "baselines.json").read_text(encoding="utf-8"))
EXPECTED_LEVEL = {
    "synthetic_waltz": "good",
    "merry-go-round-of-life": "good",
    "moonlight-sonata-3rd-movement": "review",
    "synthetic_ensemble": "review",
    "piano-concerto-no-2-opus-18-1st-movement-rachmaninoff": "unreliable",
}
READY = EngineAvailability("homr", True, "python.exe", "Ready", "", cuda=True)
SCORE = (
    "<score-partwise><part-list><score-part id='P1'><part-name>Piano</part-name></score-part></part-list>"
    "<part id='P1'><measure number='1'>{}</measure></part></score-partwise>"
)
NOTE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>"


def reference_for(pdf: Path) -> Path | None:
    for ext in (".mxl", ".musicxml", ".xml"):
        if pdf.with_suffix(ext).is_file():
            return pdf.with_suffix(ext)
    return None


SCORES = sorted(p for p in FIXTURES.rglob("*.pdf") if reference_for(p))


def blank_pdf(path: Path) -> Path:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)
    return path


def item_for(pdf: Path) -> PdfConversionItem:
    return PdfConversionItem(pdf_path=pdf, relative_path=pdf.name)


@pytest.fixture
def fake_homr(monkeypatch, tmp_path):
    """Replace the homr subprocess: fake_homr(xml, returncode, stderr)."""
    exe = tmp_path / "homr_python.exe"
    exe.write_bytes(b"")
    calls: list[list[str]] = []

    def install(xml: str | None = None, returncode: int = 0, stderr: str = ""):
        def run(python, args, cwd, timeout, on_line):
            calls.append(args)
            for line in stderr.splitlines():
                on_line(line)
            if xml is not None:
                (cwd / "score.musicxml").write_text(xml, encoding="utf-8")
            return returncode, stderr

        monkeypatch.setattr(homr_runner, "_stream_in_homr_env", run)
        return OMRConfig(homr_python=str(exe)), calls

    return install


def test_success_writes_output_and_reports_parts_from_homr(fake_homr, tmp_path):
    config, calls = fake_homr(SCORE.format(NOTE))
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "Violin Concerto.pdf")), config, READY)
    assert item.status == "converted"
    assert item.detected_instruments == ["Piano"]  # from homr, not guessed from the filename
    assert item.quality is not None and item.quality.level == "good"
    assert not list(tmp_path.glob("*.quality.json"))
    assert item.output_musicxml_path == tmp_path / "Violin Concerto.musicxml"
    assert "--gpu" in calls[0] and calls[0][calls[0].index("--gpu") + 1] == "force"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(
    ("xml", "returncode", "stderr", "expected"),
    [
        (None, 1, "An error occurred while processing C:\\t\\score_2.png: No staffs found", "page 3: No staffs found"),
        (None, 1, "An error occurred while processing C:\\my_2.png dir\\score.png: boom", "page 1: boom"),
        (None, 0, "", "homr failed"),
        (SCORE.format(""), 0, "", "without any notes"),
        (SCORE.format(NOTE), 0, "Onnxruntime is not using GPU and therefore falling back", "fell back to the CPU"),
        (SCORE.format(NOTE), 1, "crash", "homr failed (exit 1): crash"),
    ],
)
def test_failures_are_reported_and_keep_the_earlier_result(fake_homr, tmp_path, xml, returncode, stderr, expected):
    config, _ = fake_homr(xml, returncode, stderr)
    earlier = tmp_path / "a.musicxml"
    earlier.write_text("earlier result", encoding="utf-8")
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "a.pdf")), config, READY)
    assert item.status == "failed"
    assert expected in item.error_message
    assert item.output_musicxml_path is None
    assert earlier.read_text(encoding="utf-8") == "earlier result"


def test_pages_are_reported_as_homr_starts_them(fake_homr, tmp_path):
    config, _ = fake_homr(SCORE.format(NOTE), stderr="LENTO_PAGE 1/2\nsome homr output\nLENTO_PAGE 2/2\n")
    pages = []
    config.on_page = lambda pdf, page, total: pages.append((pdf.name, page, total))
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "a.pdf")), config, READY)
    assert item.status == "converted" and pages == [("a.pdf", 1, 2), ("a.pdf", 2, 2)]


def test_stream_hands_over_lines_as_they_come(tmp_path):
    import sys

    seen = []
    code, log = homr_runner._stream_in_homr_env(Path(sys.executable), ["-c", "print('LENTO_PAGE 1/3'); print('x')"], tmp_path, 30, seen.append)
    assert code == 0 and seen == ["LENTO_PAGE 1/3", "x"] and "x" in log


def test_flagged_export_is_written_with_a_report(fake_homr, tmp_path):
    two_lengths = SCORE.format(NOTE).replace(
        "</part>", "</part><part id='P2'>" + f"<measure number='1'>{NOTE}</measure>" * 5 + "</part>"
    )
    config, _ = fake_homr(two_lengths)
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "a.pdf")), config, READY)
    assert item.status == "converted" and item.quality is not None and item.quality.level == "unreliable"
    assert json.loads((tmp_path / "a.quality.json").read_text(encoding="utf-8"))["level"] == "unreliable"


def test_force_refuses_cpu_before_running(fake_homr, tmp_path):
    config, calls = fake_homr(SCORE.format(NOTE))
    cpu_only = EngineAvailability("homr", True, "", "Ready, CPU only", "", cuda=False)
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "a.pdf")), config, cpu_only)
    assert item.status == "failed" and "GPU required" in item.error_message and not calls


def test_wrong_homr_path_fails_without_guessing(tmp_path):
    config = OMRConfig(homr_python=str(tmp_path / "missing.exe"))
    assert discover_homr_python(config.homr_python) is None
    item = item_for(blank_pdf(tmp_path / "a.pdf"))
    batch_convert_pdfs([item], config)
    assert item.status == "failed" and "homr not found" in item.error_message
    assert not (tmp_path / "a.musicxml").exists()


def test_homr_on_path_is_ignored(tmp_path, monkeypatch):
    """The old code ran any homr.exe on PATH, which is how the fake one was picked up."""
    (tmp_path / "homr.exe").write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("HOMR_PYTHON", raising=False)
    found = discover_homr_python()
    assert found is None or tmp_path not in found.parents


def test_existing_output_is_kept_when_not_overwriting(fake_homr, tmp_path):
    config, calls = fake_homr(SCORE.format(NOTE))
    config.overwrite_existing = False
    (tmp_path / "a.musicxml").write_text("keep", encoding="utf-8")
    item = convert_single_pdf(item_for(blank_pdf(tmp_path / "a.pdf")), config, READY)
    assert item.status == "converted" and not calls
    assert (tmp_path / "a.musicxml").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("pdf", SCORES, ids=lambda p: p.stem)
def test_metric_gives_full_marks_to_the_reference_itself(pdf):
    ref = reference_for(pdf)
    assert ref is not None
    result = compare(ref, ref)
    assert result.strict.f1 == 1.0 and not result.wrong_measures


def test_metric_notices_a_missing_measure_without_shifting_the_rest():
    from compare_musicxml import align

    measures = load(FIXTURES / "synthetic" / "synthetic_waltz.musicxml").measures
    pairs = align(measures, measures[:10] + measures[11:])
    assert [i for i, j in pairs if j is None] == [10]


# ---- real homr ---------------------------------------------------------------------------------


@pytest.mark.homr_gpu
def test_homr_is_real_and_on_cuda():
    status = check_homr()
    assert status.installed, status.details
    assert status.cuda, status.details


@pytest.mark.homr_gpu
def test_gpu_failure_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")
    item = item_for(blank_pdf(tmp_path / "a.pdf"))
    batch_convert_pdfs([item], OMRConfig())
    assert item.status == "failed" and "GPU required" in item.error_message


@pytest.mark.homr_gpu
@pytest.mark.parametrize("kind", ["blank", "corrupt"])
def test_unreadable_pdf_fails_and_writes_nothing(kind, tmp_path):
    pdf = tmp_path / "a.pdf"
    if kind == "blank":
        blank_pdf(pdf)
    else:
        pdf.write_bytes(b"%PDF-1.7 not really a pdf")
    item = item_for(pdf)
    batch_convert_pdfs([item], OMRConfig())
    assert item.status == "failed" and item.error_message
    assert [p.name for p in tmp_path.iterdir()] == ["a.pdf"]


@pytest.mark.homr_gpu
@pytest.mark.parametrize("pdf", SCORES, ids=lambda p: p.stem)
def test_accuracy(pdf, tmp_path):
    ref = reference_for(pdf)
    assert ref is not None
    item = item_for(pdf)
    batch_convert_pdfs([item], OMRConfig(output_dir=tmp_path))  # never beside the fixture
    assert item.status == "converted", item.error_message
    assert item.output_musicxml_path is not None
    result = compare(ref, item.output_musicxml_path)
    print(f"\n{pdf.stem} ({item.duration_sec:.0f}s)\n{report(result)}")

    for other in SCORES:
        if other != pdf:
            wrong_ref = reference_for(other)
            assert wrong_ref is not None
            assert compare(wrong_ref, item.output_musicxml_path).strict.f1 < result.strict.f1 / 2

    assert item.quality is not None
    print(f"quality check: {item.quality.summary}  (symbol confidence {item.quality.symbol_confidence})")
    assert item.quality.symbol_confidence is not None  # homr_bridge still fits homr's internals
    assert item.quality.level == EXPECTED_LEVEL.get(pdf.stem, item.quality.level)

    baseline = BASELINES.get(pdf.stem)
    if baseline is None:
        pytest.skip("no accepted baseline yet")
    assert result.pitch.f1 >= baseline["pitch_f1"]
    assert result.strict.f1 >= baseline["strict_f1"]
    if "placed_pitch_f1" in baseline:  # full scores: in the right instrument, and no instrument missing
        assert result.placed_pitch.f1 >= baseline["placed_pitch_f1"]
        assert result.placed_strict.f1 >= baseline["placed_strict_f1"]
        assert all(pitch.candidate for pitch, _ in result.instruments.values())


def test_parts_homr_calls_voice_are_renamed_to_the_default_instrument(tmp_path):
    import xml.etree.ElementTree as ET
    from lento_convertpdf.homr_runner import name_parts

    xml = tmp_path / "s.musicxml"
    xml.write_text(
        '<score-partwise><part-list>'
        '<score-part id="P1"><part-name>Voice</part-name><score-instrument id="P1-I1"><instrument-name>Voice</instrument-name>'
        '<instrument-sound>voice</instrument-sound></score-instrument><midi-instrument id="P1-I1"><midi-program>54</midi-program></midi-instrument></score-part>'
        '<score-part id="P2"><part-name>Piano</part-name></score-part>'
        '</part-list><part id="P1"/><part id="P2"/></score-partwise>',
        encoding="utf-8",
    )
    assert name_parts(xml, "Cello") == 1
    root = ET.parse(xml).getroot()
    assert [p.findtext("part-name") for p in root.iter("score-part")] == ["Cello", "Piano"]
    assert root.findtext(".//instrument-sound") == "strings.cello"
    assert root.findtext(".//midi-program") == "43"
    assert name_parts(xml, "Cello") == 0  # nothing left to rename
    assert name_parts(xml, "") == 0
