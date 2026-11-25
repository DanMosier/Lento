"""Lento_SplitPDF: the quick side tool for splitting a book of pieces into one PDF per piece.

  Lento_SplitPDF [FILE.pdf]     opens just the split window (pick a PDF there if none is given). Nothing is written
                                until you press Split; the pieces go to a new "<name> - split" folder beside the PDF.
  Lento_SplitPDF --install-sendto
                                adds "Lento Split PDF" to the right-click Send to menu in Windows Explorer.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SENDTO_NAME = "Lento Split PDF.cmd"


def sendto_file() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("--install-sendto works on Windows only")
    return Path(appdata) / "Microsoft" / "Windows" / "SendTo" / SENDTO_NAME


def install_sendto() -> Path:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    f = sendto_file()
    f.write_text(f'@start "" "{pyw}" -m lento_convertpdf.split_tool %1\r\n', encoding="utf-8")
    return f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="Lento_SplitPDF", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?", type=Path, help="the PDF to split")
    ap.add_argument("--install-sendto", action="store_true", help="add it to Explorer's right-click Send to menu")
    ap.add_argument("--uninstall-sendto", action="store_true", help="remove it from the Send to menu")
    args = ap.parse_args(argv)
    if args.install_sendto:
        print(f"added {install_sendto()}: right-click a PDF > Send to > Lento Split PDF")
        return 0
    if args.uninstall_sendto:
        f = sendto_file()
        f.unlink(missing_ok=True)
        print(f"removed {f}")
        return 0
    if args.pdf and not args.pdf.is_file():
        print(f"error: {args.pdf} not found", file=sys.stderr)
        return 2
    from lento_convertpdf.gui import launch_splitter

    return launch_splitter(args.pdf)


if __name__ == "__main__":
    sys.exit(main())
