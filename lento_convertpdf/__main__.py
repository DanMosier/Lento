"""Run Lento_ConvertPDF with `python -m lento_convertpdf` (GUI with no arguments, CLI otherwise).

Also the entry script for the PyInstaller build (see build_exe.py).
"""

from __future__ import annotations

import sys

from lento_convertpdf.app import main

if __name__ == "__main__":
    sys.exit(main())
