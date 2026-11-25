"""MuseScore files in the library: export each .mscz/.mscx to MusicXML and PDF beside it, with MuseScore itself.

The exports are exact (MuseScore's own engraving and notes), so unlike a scanned PDF nothing is guessed and there
is no quality report. MuseScore 3 or 4 must be installed on the PC; it runs without opening its window.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXTS = (".mscz", ".mscx")
EXPORTS = (".musicxml", ".pdf")

# Where the installers put it, newest first
CANDIDATES = [
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 3\bin\MuseScore3.exe",
    r"C:\Program Files (x86)\MuseScore 3\bin\MuseScore3.exe",
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
    "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
]
ON_PATH = ["MuseScore4", "mscore4portable", "MuseScore3", "mscore", "musescore"]


def find(explicit: str | None = None) -> str | None:
    """The MuseScore program: --musescore, then LENTO_MUSESCORE, then the usual install places and the PATH."""
    for c in (explicit, os.environ.get("LENTO_MUSESCORE")):
        if c:
            return c if Path(c).is_file() or shutil.which(c) else None
    for c in CANDIDATES:
        if Path(c).is_file():
            return c
    for name in ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def needs_export(src: Path) -> bool:
    """True when the MusicXML or PDF of the same name is missing, or older than the MuseScore file."""
    for ext in EXPORTS:
        out = src.with_suffix(ext)
        if not out.is_file() or out.stat().st_mtime < src.stat().st_mtime:
            return True
    return False


def export(musescore: str, sources: list[Path], timeout: float = 600) -> dict[Path, bool]:
    """Exports all sources in one MuseScore run (it is slow to start) using a batch job file.
    Returns which sources now have both a MusicXML and a PDF that are up to date."""
    if not sources:
        return {}
    job = [{"in": str(s.resolve()), "out": [str(s.with_suffix(e).resolve()) for e in EXPORTS]} for s in sources]
    with tempfile.TemporaryDirectory() as tmp:
        jf = Path(tmp) / "job.json"
        jf.write_text(json.dumps(job), encoding="utf-8")
        try:
            subprocess.run([musescore, "-j", str(jf)], check=False, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {s: not needs_export(s) for s in sources}
