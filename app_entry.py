"""Desktop entry point for PDF to MusicXML Batch Converter & Open-Source VST Player.

- Double-clicking or running with no arguments launches the full GUI.
- Passing a single folder path opens the GUI pre-populated with all PDFs in that folder.
- Passing CLI arguments runs batch conversion or VST management from the command line.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PDF_to_MusicXML.cli import main as cli_main
from PDF_to_MusicXML.gui import launch_gui


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        return launch_gui()

    if len(args) == 1 and not args[0].startswith("-"):
        candidate = Path(args[0])
        if candidate.is_dir():
            return launch_gui(initial_directory=candidate)

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
