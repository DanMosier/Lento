"""The PDF splitter as a quick tool of its own, without the converter.

  python -m lento_convertpdf.split_tool [PDF ...]     opens the splitter on each PDF (or empty, to browse for one)
  python -m lento_convertpdf.split_tool --install     adds "Split sheet music PDF" to Explorer's Send to menu and
                                                      the desktop (drop a PDF on the icon)
  python -m lento_convertpdf.split_tool --uninstall   removes both
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .split_window import build_split_window

SHORTCUT = "Split sheet music PDF.lnk"
# Paths go in through the environment, so no quoting can go wrong. Prints where each shortcut is.
_PS = r"""
$ErrorActionPreference = 'Stop'
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in [Environment]::GetFolderPath('SendTo'), [Environment]::GetFolderPath('Desktop')) {
  $lnk = Join-Path $dir $env:LENTO_LNK
  if ($env:LENTO_EXE) {
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $env:LENTO_EXE
    $s.Arguments = '-m lento_convertpdf.split_tool'
    $s.WorkingDirectory = $env:LENTO_DIR
    $s.Description = 'Split a PDF of several pieces into one PDF each'
    $s.Save()
    $lnk
  } elseif (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk; $lnk }
}
"""


def _shortcuts(install: bool) -> list[str]:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    env = {**os.environ, "LENTO_LNK": SHORTCUT, "LENTO_EXE": str(pyw) if install else "", "LENTO_DIR": str(Path(__file__).resolve().parent.parent)}
    done = subprocess.run(["powershell", "-NoProfile", "-Command", _PS], env=env, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(done.stderr.strip())
    return done.stdout.split("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="split_tool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", type=Path)
    ap.add_argument("--install", action="store_true", help="add it to the Send to menu and the desktop")
    ap.add_argument("--uninstall", action="store_true", help="remove it from both")
    args = ap.parse_args(argv)
    if args.install or args.uninstall:
        if sys.platform != "win32":
            print("error: the shortcuts are for Windows", file=sys.stderr)
            return 2
        for line in _shortcuts(install=args.install):
            if line.strip():
                print(("added " if args.install else "removed ") + line.strip())
        return 0

    root = tk.Tk()
    root.withdraw()  # each PDF gets a window of its own; the program ends with the last one
    open_windows: list[tk.Toplevel] = []

    def open_one(pdf: Path | None) -> None:
        dlg = tk.Toplevel(root)
        open_windows.append(dlg)

        def closed(e: tk.Event) -> None:  # type: ignore[type-arg]
            if e.widget is dlg:
                open_windows.remove(dlg)
                if not open_windows:
                    root.after_idle(root.destroy)

        dlg.bind("<Destroy>", closed)
        build_split_window(dlg, pdf, browse_dir=lambda: str(Path.home() / "Downloads"))

    good = [p for p in args.pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
    bad = [p.name for p in args.pdfs if p not in good]
    if bad:  # started from an icon there is no console to say it in
        messagebox.showwarning("Not a PDF", "Skipped, not a PDF file:\n" + "\n".join(bad), parent=root)
    for pdf in good or ([] if bad else [None]):
        open_one(pdf)
    if open_windows:
        root.mainloop()
    else:
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
