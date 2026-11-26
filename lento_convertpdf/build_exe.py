"""Build a standalone Windows Lento_ConvertPDF.exe using PyInstaller.

Run from the repository root: python -m lento_convertpdf.build_exe
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build() -> int:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent
    entry_script = package_dir / "__main__.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--paths",
        str(project_root),
        "--specpath",
        str(project_root / "build"),
        "--name",
        "Lento_ConvertPDF",
        # These run inside homr's environment, as files
        *(
            arg
            for name in ("homr_bridge", "system_reader", "instruments", "system_merge")
            for arg in ("--add-data", f"{package_dir / f'{name}.py'};lento_convertpdf")
        ),
        "--collect-all",
        "pypdfium2",
        "--collect-all",
        "pypdfium2_raw",
        "--collect-data",
        "certifi",
        "--hidden-import",
        "lento_convertpdf",
        "--hidden-import",
        "lento_convertpdf.gui",
        "--hidden-import",
        "lento_convertpdf.cli",
        "--hidden-import",
        "lento_convertpdf.models",
        "--hidden-import",
        "lento_convertpdf.omr_engines",
        "--hidden-import",
        "lento_convertpdf.homr_runner",
        "--hidden-import",
        "lento_convertpdf.audiveris_runner",
        "--hidden-import",
        "lento_convertpdf.staff_detection",
        "--hidden-import",
        "lento_convertpdf.pdf_splitter",
        "--hidden-import",
        "lento_convertpdf.musicxml_parser",
        "--hidden-import",
        "lento_convertpdf.vst_catalog",
        "--hidden-import",
        "lento_convertpdf.audio_player",
        "--hidden-import",
        "lento_convertpdf.app",
        str(entry_script),
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(project_root), check=False)
    if result.returncode == 0:
        exe_path = project_root / "dist" / "Lento_ConvertPDF.exe"
        print(f"\nBuild succeeded! Executable created at:\n  {exe_path}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(build())
