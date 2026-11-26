"""Tests for the Legato integration, with stand-ins for Legato's environment."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lento_convertpdf import legato_runner
from lento_convertpdf.homr_runner import OMRConfig
from lento_convertpdf.legato_runner import check_legato, discover_legato_python
from lento_convertpdf.models import PdfConversionItem
from lento_convertpdf.omr_engines import convert_single_pdf

NOTE = "<note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>"


def score(name: str = "", measures: int = 1, notes: str = NOTE) -> str:
    body = "".join(
        f"<measure number='{n}'><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type>"
        f"</time></attributes>{notes}</measure>"
        for n in range(1, measures + 1)
    )
    return (
        "<score-partwise version='4.0'><part-list><score-part id='P1'>"
        f"<part-name>{name}</part-name></score-part></part-list><part id='P1'>{body}</part></score-partwise>"
    )


@pytest.fixture
def legato_env(monkeypatch, tmp_path):
    """A fake Legato environment: legato/.venv/Scripts/python.exe, with the probe and the bridge stood in for."""
    python = tmp_path / "legato" / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    calls: list[list[str]] = []

    def install(xml: str | None = None, returncode: int = 0, log: str = "LENTO_DONE", probe: dict | None = None):
        info = {"torch": "2.6.0", "cuda": True, "gpu": "RTX", "pipeline": True, "signed_in": True, "note": ""}
        info.update(probe or {})

        def fake_probe(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "PROBE" + json.dumps(info), "")

        def fake_bridge(py, args, cwd, timeout, on_line):
            calls.append(args)
            for line in log.splitlines():
                on_line(line)
            if xml is not None:
                Path(args[2]).write_text(xml, encoding="utf-8")
            Path(args[args.index("--abc") + 1]).write_text("X:1\nK:C\nC4|", encoding="utf-8")
            return returncode, log

        monkeypatch.setattr(legato_runner.subprocess, "run", fake_probe)
        monkeypatch.setattr(legato_runner, "_stream_in_homr_env", fake_bridge)
        return OMRConfig(engine="legato", legato_python=str(python)), calls

    return install


def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "piece.pdf"
    path.write_bytes(b"%PDF-1.4 stand-in")
    return path


def test_converts_on_the_gpu(legato_env, tmp_path):
    config, calls = legato_env(score(), log="LENTO_READER legato2-pipeline\nLENTO_PAGE 1/1\nLENTO_DONE")
    pages: list[tuple[int, int]] = []
    config.on_page = lambda _pdf, page, total: pages.append((page, total))
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted", item.error_message
    assert item.engine_used == "legato" and item.detected_instruments == ["Cello"]
    args = calls[-1]
    assert args[args.index("--device") + 1] == "cuda"
    assert args[args.index("--model") + 1] == "guangyangmusic/legato-2"
    assert Path(args[args.index("--root") + 1]).name == "legato"
    assert pages == [(1, 1)]
    assert (tmp_path / "piece.musicxml").is_file()


def test_gpu_required_but_missing_fails_before_running(legato_env, tmp_path):
    config, calls = legato_env(score(), probe={"cuda": False})
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed" and "GPU required" in item.error_message
    assert calls == []


def test_cpu_mode_runs_on_the_cpu(legato_env, tmp_path):
    config, calls = legato_env(score(), probe={"cuda": False})
    config.gpu = "no"
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "converted", item.error_message
    assert calls[-1][calls[-1].index("--device") + 1] == "cpu"


def test_gated_model_error_says_what_to_do(legato_env, tmp_path):
    config, _ = legato_env(None, returncode=1, log="LENTO_ERROR OSError: 401 Client Error: access to model is restricted (gated repo)")
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed"
    assert "hf auth login" in item.error_message


def test_empty_result_fails_and_keeps_the_abc(legato_env, tmp_path):
    config, _ = legato_env(score(notes=""))
    item = convert_single_pdf(PdfConversionItem(pdf_path=pdf(tmp_path), relative_path="piece.pdf"), config)
    assert item.status == "failed" and "Legato produced a score without any notes" in item.error_message
    assert (tmp_path / "piece.legato.abc").is_file()
    assert not (tmp_path / "piece.musicxml").exists()


def test_status_mentions_a_missing_sign_in(legato_env):
    config, _ = legato_env(probe={"signed_in": False, "pipeline": False})
    status = check_legato(config)
    assert status.installed and status.cuda
    assert "page-by-page" in status.details and "hf auth login" in status.details


def test_missing_legato_is_reported(tmp_path):
    config = OMRConfig(engine="legato", legato_python=str(tmp_path / "nope.exe"))
    assert discover_legato_python(config.legato_python) is None
    assert not check_legato(config).installed


def load_bridge():
    path = Path(__file__).resolve().parents[2] / "lento_convertpdf" / "legato_bridge.py"
    spec = importlib.util.spec_from_file_location("legato_bridge_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_pages_are_joined_and_renumbered():
    bridge = load_bridge()
    first, second = ET.fromstring(score(measures=2)), ET.fromstring(score(measures=3))
    joined = bridge.join([first, second])
    numbers = [m.get("number") for m in joined.findall("part/measure")]
    assert numbers == ["1", "2", "3", "4", "5"]
