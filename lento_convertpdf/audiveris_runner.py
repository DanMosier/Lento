"""Find, check and run Audiveris (https://github.com/Audiveris/audiveris), the second OMR engine.

Audiveris is a separate Java program with its own installer (the Windows .msi bundles Java). It is run as a
subprocess in batch mode:  Audiveris -batch -transcribe -export -output DIR -- score.pdf
It runs on the CPU, so it can work while homr has the GPU. It reports no per-symbol confidence, so its
quality estimate rests on the musical consistency checks alone.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from .homr_runner import EngineAvailability, OMRConfig, check_output, name_parts, source_suffix, write_report
from .pages import pages_with_staves
from .quality import QualityReport, check_score
from .rests import expand_multirests

INSTALL_HINT = (
    "Install Audiveris from https://github.com/Audiveris/audiveris/releases "
    "(Windows: the windowsConsole .msi shows its log), or set its path."
)
TIMEOUT_BASE_SEC = 300
TIMEOUT_PER_PAGE_SEC = 180
# Audiveris rejects a sheet whose staff lines are closer than about 11 pixels ("try 300 DPI"). A phone photo of
# small print is often 10, so photos smaller than this many pixels on their long side are enlarged first.
MIN_IMAGE_LONG_SIDE = 3000


def _candidates() -> list[Path]:
    found: list[Path] = []
    for env in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            found += [Path(base) / "Audiveris" / "Audiveris.exe", Path(base) / "Programs" / "Audiveris" / "Audiveris.exe"]
    for name in ("Audiveris", "audiveris"):
        on_path = shutil.which(name)
        if on_path:
            found.append(Path(on_path))
    found.append(Path("/opt/audiveris/bin/Audiveris"))
    # an Audiveris folder beside the project, as homr and Legato are (e.g. D:\Coding\Audiveris)
    anchor = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
    for parent in anchor.resolve().parents:
        for name in ("Audiveris", "audiveris"):
            found += [parent / name / "Audiveris.exe", parent / name / "bin" / "Audiveris.exe", parent / name / "bin" / "Audiveris"]
    return found


def discover_audiveris(custom_path: str = "") -> Path | None:
    """Find the Audiveris launcher: explicit setting, then AUDIVERIS, then the usual install folders, PATH and an
    Audiveris folder beside the project."""
    for explicit in (custom_path, os.environ.get("AUDIVERIS", "")):
        if explicit:
            path = Path(explicit)
            return path if path.is_file() else None  # a wrong setting is an error, not a reason to guess
    return next((p for p in _candidates() if p.is_file()), None)


def _run(exe: Path, args: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    """Run Audiveris and return (exit code, output). The plain Windows launcher prints nothing; that is fine."""
    res = subprocess.run(
        [str(exe), *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return res.returncode, res.stdout or ""


def check_audiveris(config: OMRConfig | None = None) -> EngineAvailability:
    """Find Audiveris and ask it for its version (starts Java, so it takes a few seconds)."""
    cfg = config or OMRConfig()
    exe = discover_audiveris(cfg.audiveris_path)
    if exe is None:
        return EngineAvailability("audiveris", False, "", "Audiveris not found: install it or set its path", INSTALL_HINT)
    try:
        with tempfile.TemporaryDirectory(prefix="audiveris_probe_", ignore_cleanup_errors=True) as tmp:
            _, out = _run(exe, ["-batch", "-version"], Path(tmp), timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EngineAvailability("audiveris", False, str(exe), f"Audiveris could not be started: {exc}", INSTALL_HINT)
    found = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", "\n".join(ln for ln in out.splitlines() if "audiveris" in ln.lower()))
    details = f"Ready, CPU, {f'Audiveris {found.group(1)}' if found else 'version not reported'} ({exe})"
    return EngineAvailability("audiveris", True, str(exe), details, INSTALL_HINT)


def _unpack(mxl: Path, dest: Path) -> None:
    """Audiveris writes compressed MusicXML (.mxl): take the score named in META-INF/container.xml."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(mxl) as zf:
        names = zf.namelist()
        root_file = ""
        if "META-INF/container.xml" in names:
            for el in ET.fromstring(zf.read("META-INF/container.xml")).iter():
                if el.tag.endswith("rootfile") and el.get("full-path"):
                    root_file = el.get("full-path", "")
                    break
        if root_file not in names:
            root_file = next((n for n in names if n.lower().endswith((".xml", ".musicxml")) and not n.startswith("META-INF")), "")
        if not root_file:
            raise RuntimeError(f"Audiveris wrote {mxl.name} without a score in it.")
        dest.write_bytes(zf.read(root_file))


def _enlarge_small_image(path: Path) -> bool:
    """Scale a small page image up in place so its staff lines are far enough apart for Audiveris."""
    from PIL import Image

    with Image.open(path) as im:
        long_side = max(im.size)
        if long_side >= MIN_IMAGE_LONG_SIDE:
            return False
        scale = MIN_IMAGE_LONG_SIDE / long_side
        big = im.convert("L").resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)
    big.save(path)
    return True


def _error(log: str, returncode: int) -> str:
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    problems = [ln for ln in lines if "ERROR" in ln or "Exception" in ln]
    last = (problems or lines or ["no output (the Console installer shows Audiveris's log)"])[-1]
    return f"Audiveris wrote no MusicXML (exit {returncode}): {last}"


def run_audiveris(
    pdf_path: Path, target_musicxml: Path, config: OMRConfig, page_count: int = 1
) -> tuple[list[str], QualityReport]:
    """Transcribe a whole PDF with Audiveris, write target_musicxml, and return the part names and a quality estimate.

    Where Audiveris splits a PDF into movements it writes one file per movement; the first is kept and the
    report says so. The target is only replaced once the result has been checked.
    """
    exe = discover_audiveris(config.audiveris_path)
    if exe is None:
        raise FileNotFoundError("Audiveris not found: install it or set the path to Audiveris.exe.")

    timeout = TIMEOUT_BASE_SEC + TIMEOUT_PER_PAGE_SEC * max(1, page_count)
    with tempfile.TemporaryDirectory(prefix="audiveris_work_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        source = work / f"score{source_suffix(pdf_path)}"
        shutil.copyfile(pdf_path, source)
        if source.suffix != ".pdf":
            try:
                _enlarge_small_image(source)
            except OSError:
                pass  # not an image PIL can read: let Audiveris report it
        out = work / "out"
        out.mkdir()
        def attempt(sheets: list[int] | None) -> tuple[int, str, list[Path]]:
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            only = ["-sheets", *map(str, sheets)] if sheets else []
            args = ["-batch", "-transcribe", "-export", "-output", str(out), *only, "--", str(source)]
            try:
                code, text = _run(exe, args, work, timeout)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Audiveris did not finish within {timeout} seconds.") from exc
            files = sorted(out.rglob("*.mxl")) or sorted(out.rglob("*.musicxml")) or sorted(out.rglob("*.xml"))
            return code, text, files

        returncode, log, exported = attempt(None)
        skipped: list[int] = []
        if not exported and source.suffix == ".pdf":
            # Audiveris gives up on the whole PDF when one page has no staff ("No system found"), such as a
            # blank last page. Try again with only the pages that have staves.
            pages, music = pages_with_staves(source)
            if music and len(music) < pages:
                skipped = [n for n in range(1, pages + 1) if n not in music]
                returncode, log, exported = attempt(music)
        if not exported:
            raise RuntimeError(_error(log, returncode))
        produced = work / "score.musicxml"
        if exported[0].suffix.lower() == ".mxl":
            _unpack(exported[0], produced)
        else:
            shutil.copyfile(exported[0], produced)

        name_parts(produced, config.instrument, also_unnamed=True, source_name=pdf_path.stem)
        expand_multirests(produced)
        parts = check_output(produced, "Audiveris")
        report = check_score(produced, None, config.review_below)
        if skipped:
            report.problems.append(f"page {', '.join(map(str, skipped))} had no staves and was left out")
        if len(exported) > 1:
            report.problems.append(f"Audiveris split this PDF into {len(exported)} movements; only the first was kept")
            report.level = "review" if report.level == "good" else report.level

        target_musicxml.parent.mkdir(parents=True, exist_ok=True)
        partial = target_musicxml.with_name(target_musicxml.name + ".part")
        try:
            shutil.copyfile(produced, partial)
            os.replace(partial, target_musicxml)
        finally:
            partial.unlink(missing_ok=True)
        write_report(target_musicxml, report)
        return parts, report


if __name__ == "__main__":  # pragma: no cover - quick manual check
    print(check_audiveris().details)
    sys.exit(0)
