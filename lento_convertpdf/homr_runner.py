"""Find, check and run homr (https://github.com/liebharc/homr).

homr lives in its own Python environment and is run as a subprocess. There is deliberately no fallback
transcriber and no lookup of a "homr" on PATH: a conversion either comes from the real homr or fails.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .quality import REVIEW_BELOW, QualityReport, assess

BRIDGE = Path(__file__).with_name("homr_bridge.py")
GPU_MODES = ("force", "auto", "no")

# What homr prints when it gives up on the GPU and carries on with the CPU, even under --gpu force.
GPU_FALLBACK_MESSAGES = (
    "Onnxruntime is not using GPU",
    "Going on without GPU support",
    "Error while trying to load model on the GPU",
    "No GPU execution provider available",
    "Failed to create CUDAExecutionProvider",
)

# Runs inside homr's environment. Opens a real session: "CUDA is available" alone does not mean it works,
# and homr hides ONNX Runtime's own warning when it does not.
_PROBE = """
import json, os, sys
import homr.main
import onnxruntime as ort
from homr.onnx_providers import gpu_providers
from homr.segmentation.config import segnet_path_onnx_fp16 as model
out = {"path": os.path.dirname(homr.main.__file__), "onnxruntime": ort.__version__, "cuda": False, "note": ""}
try:
    if sys.argv[1] == "no":
        out["note"] = "GPU turned off"
    elif not os.path.exists(model):
        out["note"] = "GPU models not downloaded yet, run homr --gpu force --init"
    else:
        session = ort.InferenceSession(model, providers=gpu_providers()[0])
        out["cuda"] = "CUDAExecutionProvider" in session.get_providers()
        if not out["cuda"]:
            out["note"] = "ONNX Runtime fell back to the CPU"
except Exception as exc:
    out["note"] = str(exc)
print("PROBE" + json.dumps(out))
"""


@dataclass
class OMRConfig:
    """Configuration for batch PDF -> MusicXML conversion."""

    engine: str = "homr"
    output_dir: Path | None = None  # None = same folder as PDF
    recursive: bool = True
    overwrite_existing: bool = True
    homr_python: str = ""  # python.exe of homr's environment; blank = find it
    gpu: str = "force"  # "force" (fail without CUDA) | "auto" | "no"
    review_below: float = REVIEW_BELOW  # flag exports whose quality estimate is lower
    timeout_base_sec: int = 180
    timeout_per_page_sec: int = 90
    # called with (pdf, page, pages) as homr starts each page of a PDF
    on_page: Callable[[Path, int, int], None] | None = field(default=None, repr=False, compare=False)


@dataclass
class EngineAvailability:
    """Status of homr on this system."""

    engine: str
    installed: bool
    executable_path: str
    details: str
    install_hint: str
    cuda: bool = False


def discover_homr_python(custom_python: str = "") -> Path | None:
    """Find homr's python.exe: explicit setting, then HOMR_PYTHON, then a homr folder beside the project."""
    for explicit in (custom_python, os.environ.get("HOMR_PYTHON", "")):
        if explicit:
            path = Path(explicit)
            return path if path.is_file() else None  # a wrong setting is an error, not a reason to guess
    anchor = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
    for parent in anchor.resolve().parents:
        candidate = parent / "homr" / ".venv" / "Scripts" / "python.exe"
        if candidate.is_file():
            return candidate
    return None


def _run_in_homr_env(python: Path, args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    return subprocess.run(
        # -I: import nothing from the working folder or user site; -X utf8: homr prints note symbols
        [str(python), "-I", "-X", "utf8", *args],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


_PAGE = re.compile(r"^LENTO_PAGE (\d+)/(\d+)\s*$")


def _stream_in_homr_env(python: Path, args: list[str], cwd: Path, timeout: float, on_line: Callable[[str], None]) -> tuple[int, str]:
    """Like _run_in_homr_env, but hands each output line to on_line as it comes. Returns (exit code, all output)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    proc = subprocess.Popen(
        [str(python), "-I", "-X", "utf8", *args],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []

    def read() -> None:
        assert proc.stdout
        for line in proc.stdout:
            lines.append(line)
            try:
                on_line(line.rstrip("\r\n"))
            except Exception:  # a display problem must not stop the conversion
                pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        reader.join(timeout=5)
        raise
    reader.join(timeout=5)
    return code, "".join(lines)


def check_homr(config: OMRConfig | None = None) -> EngineAvailability:
    """Import homr in its own environment and open a real session on the GPU. Takes a few seconds."""
    cfg = config or OMRConfig()
    hint = "Clone https://github.com/liebharc/homr and run: poetry install --only main --extras cuda"
    python = discover_homr_python(cfg.homr_python)
    if python is None:
        return EngineAvailability("homr", False, "", "homr not found: set the path to its python.exe", hint)
    try:
        with tempfile.TemporaryDirectory(prefix="homr_probe_", ignore_cleanup_errors=True) as tmp:
            res = _run_in_homr_env(python, ["-c", _PROBE, cfg.gpu], Path(tmp), timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EngineAvailability("homr", False, str(python), f"homr could not be started: {exc}", hint)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("PROBE")), "")
    if not line:
        reason = (res.stderr.strip().splitlines() or ["no output"])[-1]
        return EngineAvailability("homr", False, str(python), f"homr does not work in {python}: {reason}", hint)
    info = json.loads(line[len("PROBE"):])
    state = "CUDA active" if info["cuda"] else f"CPU only: {info['note']}"
    details = f"Ready, {state}, onnxruntime {info['onnxruntime']} ({info['path']})"
    return EngineAvailability("homr", True, str(python), details, hint, cuda=info["cuda"])


def _page_of(image_name: str) -> int:
    """homr renders page 1 to score.png and page n to score_<n-1>.png."""
    match = re.search(r"_(\d+)\.png$", image_name)
    return int(match.group(1)) + 1 if match else 1


def _homr_error(log: str, returncode: int) -> str:
    match = re.search(r"An error occurred while processing (.+?\.png): (.*)", log)
    if match:
        return f"homr could not read page {_page_of(Path(match.group(1)).name)}: {match.group(2).strip()}"
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    return f"homr failed (exit {returncode}): {lines[-1] if lines else 'no output'}"


def _check_output(xml_path: Path) -> list[str]:
    """Return the part names homr wrote; raise if the file holds no music."""
    root = ET.parse(xml_path).getroot()
    if root.find("part/measure/note/pitch") is None and root.find("part/measure/note/unpitched") is None:
        raise RuntimeError("homr produced a score without any notes.")
    names = [(p.findtext("part-name") or "").strip() for p in root.findall("part-list/score-part")]
    return [name or f"Part {i}" for i, name in enumerate(names, start=1)]


def _read_trace(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_report(target_musicxml: Path, report: QualityReport) -> None:
    """Leave name.quality.json beside a flagged export; clear an outdated one beside a good export."""
    path = target_musicxml.with_suffix(".quality.json")
    if report.level == "good":
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")


def run_homr(
    pdf_path: Path, target_musicxml: Path, config: OMRConfig, page_count: int = 1
) -> tuple[list[str], QualityReport]:
    """Transcribe a whole PDF with homr, write target_musicxml, and return the part names and a quality estimate.

    homr gets the complete PDF in one call: it renders at 300 DPI, carries time signatures from page to page
    and merges the pages itself. The target is only replaced once the result has been checked.
    """
    if config.gpu not in GPU_MODES:
        raise ValueError(f"gpu must be one of {GPU_MODES}, not {config.gpu!r}")
    python = discover_homr_python(config.homr_python)
    if python is None:
        raise FileNotFoundError("homr not found: set the path to the python.exe of its environment.")

    timeout = config.timeout_base_sec + config.timeout_per_page_sec * max(1, page_count)
    with tempfile.TemporaryDirectory(prefix="homr_work_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        source = work / "score.pdf"
        shutil.copyfile(pdf_path, source)  # homr writes beside its input
        trace_path = work / "trace.json"
        args = [str(BRIDGE), str(trace_path), "--gpu", config.gpu, str(source)]
        def on_line(line: str) -> None:
            m = _PAGE.match(line)
            if m and config.on_page:
                config.on_page(pdf_path, int(m.group(1)), int(m.group(2)))

        try:
            returncode, log = _stream_in_homr_env(python, args, work, timeout, on_line)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"homr did not finish within {timeout} seconds.") from exc
        if config.gpu == "force":
            for message in GPU_FALLBACK_MESSAGES:
                if message in log:
                    raise RuntimeError(f"GPU required, but homr fell back to the CPU: {message}")
        produced = work / "score.musicxml"
        if returncode != 0 or not produced.is_file():
            raise RuntimeError(_homr_error(log, returncode))
        parts = _check_output(produced)
        report = assess(produced, _read_trace(trace_path), config.review_below)

        target_musicxml.parent.mkdir(parents=True, exist_ok=True)
        partial = target_musicxml.with_name(target_musicxml.name + ".part")
        try:
            shutil.copyfile(produced, partial)
            os.replace(partial, target_musicxml)
        finally:
            partial.unlink(missing_ok=True)
        _write_report(target_musicxml, report)
        return parts, report
