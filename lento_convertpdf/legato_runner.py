"""Find, check and run LEGATO (https://github.com/guang-yng/legato), the third OMR engine.

Like homr, Legato lives in its own Python environment (PyTorch, transformers) and is run as a subprocess through
legato_bridge.py, which writes MusicXML. Its models on Hugging Face are gated: accept the terms on
huggingface.co/guangyangmusic/legato-2 and sign in once in Legato's environment (hf auth login) before the
first conversion downloads them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .homr_runner import (
    EngineAvailability,
    OMRConfig,
    _stream_in_homr_env,
    check_output,
    name_parts,
    source_suffix,
    write_report,
)
from .quality import QualityReport, check_score
from .rests import expand_multirests

BRIDGE = Path(__file__).with_name("legato_bridge.py")
DEFAULT_MODEL = "guangyangmusic/legato-2"
INSTALL_HINT = (
    "Clone https://github.com/guang-yng/legato beside Lento, make a .venv there with its requirements plus "
    "pypdfium2, accept the model's terms on Hugging Face and run: hf auth login"
)
TIMEOUT_BASE_SEC = 300
TIMEOUT_PER_PAGE_SEC = 240
_PAGE = re.compile(r"^LENTO_PAGE (\d+)/(\d+)\s*$")

_PROBE = """
import json, sys
out = {"torch": "", "cuda": False, "pipeline": False, "signed_in": False, "note": ""}
try:
    import torch
    out["torch"] = torch.__version__
    out["cuda"] = bool(torch.cuda.is_available()) and sys.argv[1] != "no"
    if out["cuda"]:
        out["gpu"] = torch.cuda.get_device_name(0)
    import legato.models
    try:
        import legato.pipeline
        out["pipeline"] = True
    except ImportError:
        pass
    try:
        from huggingface_hub import get_token
        out["signed_in"] = bool(get_token())
    except Exception:
        pass
except Exception as exc:
    out["note"] = f"{type(exc).__name__}: {exc}"
print("PROBE" + json.dumps(out))
"""


def discover_legato_python(custom_python: str = "") -> Path | None:
    """Find Legato's python.exe: explicit setting, then LEGATO_PYTHON, then a legato folder beside the project."""
    for explicit in (custom_python, os.environ.get("LEGATO_PYTHON", "")):
        if explicit:
            path = Path(explicit)
            return path if path.is_file() else None
    anchor = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
    for parent in anchor.resolve().parents:
        for venv in (".venv", "venv"):
            for exe in ("Scripts/python.exe", "bin/python"):
                candidate = parent / "legato" / venv / exe
                if candidate.is_file():
                    return candidate
    return None


def legato_root(python: Path) -> Path:
    """The repository holding the environment: legato/.venv/Scripts/python.exe -> legato."""
    return python.parent.parent.parent


def _device(config: OMRConfig, cuda: bool) -> str:
    return "cuda" if cuda and config.gpu != "no" else "cpu"


def check_legato(config: OMRConfig | None = None) -> EngineAvailability:
    """Import Legato and PyTorch in Legato's environment and see whether CUDA and a Hugging Face sign-in are there."""
    cfg = config or OMRConfig()
    python = discover_legato_python(cfg.legato_python)
    if python is None:
        return EngineAvailability("legato", False, "", "Legato not found: set the path to its python.exe", INSTALL_HINT)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    try:
        res = subprocess.run(
            [str(python), "-X", "utf8", "-c", _PROBE, cfg.gpu],
            cwd=str(legato_root(python)), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EngineAvailability("legato", False, str(python), f"Legato could not be started: {exc}", INSTALL_HINT)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("PROBE")), "")
    if not line:
        reason = (res.stderr.strip().splitlines() or ["no output"])[-1]
        return EngineAvailability("legato", False, str(python), f"Legato does not work in {python}: {reason}", INSTALL_HINT)
    info = json.loads(line[len("PROBE"):])
    if info["note"]:
        return EngineAvailability("legato", False, str(python), f"Legato is not installed right: {info['note']}", INSTALL_HINT)
    where = f"CUDA ({info.get('gpu', 'GPU')})" if info["cuda"] else "CPU only (slow)"
    reader = "Legato-2 pipeline" if info["pipeline"] else "page-by-page model"
    details = f"Ready, {where}, {reader}, torch {info['torch']}"
    if not info["signed_in"]:
        details += "; not signed in to Hugging Face (needed once to download the gated model: hf auth login)"
    return EngineAvailability("legato", True, str(python), details, INSTALL_HINT, cuda=info["cuda"])


def _error(log: str, returncode: int) -> str:
    for line in reversed(log.splitlines()):
        if line.startswith("LENTO_ERROR"):
            text = line[len("LENTO_ERROR"):].strip()
            if "gated" in text.lower() or "401" in text or "403" in text:
                text += " (accept the terms on huggingface.co/guangyangmusic/legato-2, then run hf auth login)"
            return f"Legato failed: {text}"
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    return f"Legato failed (exit {returncode}): {lines[-1] if lines else 'no output'}"


def run_legato(
    pdf_path: Path, target_musicxml: Path, config: OMRConfig, page_count: int = 1, cuda: bool = True
) -> tuple[list[str], QualityReport]:
    """Transcribe a PDF or page image with Legato, write target_musicxml, and return the part names and a quality
    estimate. The raw ABC is kept beside the export as name.legato.abc only when the result fails its checks."""
    python = discover_legato_python(config.legato_python)
    if python is None:
        raise FileNotFoundError("Legato not found: set the path to the python.exe of its environment.")
    timeout = TIMEOUT_BASE_SEC + TIMEOUT_PER_PAGE_SEC * max(1, page_count)
    with tempfile.TemporaryDirectory(prefix="legato_work_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        source = work / f"score{source_suffix(pdf_path)}"
        shutil.copyfile(pdf_path, source)
        produced = work / "score.musicxml"
        abc = work / "score.abc"
        args = [str(BRIDGE), str(source), str(produced), "--model", config.legato_model or DEFAULT_MODEL,
                "--device", _device(config, cuda), "--abc", str(abc), "--root", str(legato_root(python))]

        def on_line(line: str) -> None:
            m = _PAGE.match(line)
            if m and config.on_page:
                config.on_page(pdf_path, int(m.group(1)), int(m.group(2)))

        try:
            returncode, log = _stream_in_homr_env(python, args, work, timeout, on_line)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Legato did not finish within {timeout} seconds.") from exc
        if returncode != 0 or not produced.is_file():
            raise RuntimeError(_error(log, returncode))
        name_parts(produced, config.instrument, also_unnamed=True, source_name=pdf_path.stem)
        expand_multirests(produced)
        try:
            parts = check_output(produced, "Legato")
        except Exception:
            if abc.is_file():
                shutil.copyfile(abc, target_musicxml.with_suffix(".legato.abc"))
            raise
        report = check_score(produced, None, config.review_below)

        target_musicxml.parent.mkdir(parents=True, exist_ok=True)
        partial = target_musicxml.with_name(target_musicxml.name + ".part")
        try:
            shutil.copyfile(produced, partial)
            os.replace(partial, target_musicxml)
        finally:
            partial.unlink(missing_ok=True)
        write_report(target_musicxml, report)
        return parts, report
