"""Build a standalone Windows PdfToMusicXML.exe using PyInstaller."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build() -> int:
    project_root = Path(__file__).resolve().parent
    entry_script = project_root / "app_entry.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "PdfToMusicXML",
        # These run inside homr's environment, as files
        *(
            arg
            for name in ("homr_bridge", "system_reader", "instruments", "system_merge")
            for arg in ("--add-data", f"{project_root / 'PDF_to_MusicXML' / f'{name}.py'};PDF_to_MusicXML")
        ),
        "--collect-all",
        "pypdfium2",
        "--collect-all",
        "pypdfium2_raw",
        "--collect-data",
        "certifi",
        "--hidden-import",
        "PDF_to_MusicXML",
        "--hidden-import",
        "PDF_to_MusicXML.gui",
        "--hidden-import",
        "PDF_to_MusicXML.cli",
        "--hidden-import",
        "PDF_to_MusicXML.models",
        "--hidden-import",
        "PDF_to_MusicXML.omr_engines",
        "--hidden-import",
        "PDF_to_MusicXML.homr_runner",
        "--hidden-import",
        "PDF_to_MusicXML.staff_detection",
        "--hidden-import",
        "PDF_to_MusicXML.pdf_splitter",
        "--hidden-import",
        "PDF_to_MusicXML.musicxml_parser",
        "--hidden-import",
        "PDF_to_MusicXML.vst_catalog",
        "--hidden-import",
        "PDF_to_MusicXML.audio_player",
        str(entry_script),
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(project_root), check=False)
    if result.returncode == 0:
        exe_path = project_root / "dist" / "PdfToMusicXML.exe"
        print(f"\nBuild succeeded! Executable created at:\n  {exe_path}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(build())
