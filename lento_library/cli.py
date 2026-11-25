"""lento-library: keep the score library tidy and build the library.json index the app reads.

  lento-library build [--root FOLDER]
      Writes FOLDER/library.json from the piece folders and catalog.csv. Run it after any change.
  lento-library check [--root FOLDER] [--list practice.csv] [--column piece_id]
      Checks that folders, files, catalog.csv and tags.md agree.
  lento-library add FILE PIECE_ID VARIANT [--root FOLDER]
      Moves FILE (from inbox/ if not found as given) to pieces/<piece_id>/<piece_id>__<variant>.<ext>.

  lento-library convert [PIECE_ID ...] [--missing] [--root FOLDER] [--converter CMD]
      Makes MusicXML from PDFs with Lento_ConvertPDF (homr, on this PC's GPU), saved beside each PDF under the
      same name, then rebuilds library.json. With no PIECE_ID, converts the PDFs requested from the app
      ("Make MusicXML"); --missing converts every PDF that has no MusicXML yet. Existing MusicXML is kept.

  lento-library watch [--root FOLDER] [--interval SECONDS] [--install | --uninstall]
      Keeps running and converts PDFs as soon as they are queued from the app, whenever this PC is on.
      Writes requests/_status.json so the app can show what the PC is doing. --install starts it hidden
      at every Windows sign-in (Startup folder); --uninstall removes that.

FOLDER defaults to the current folder.
"""

from __future__ import annotations

import argparse
import csv
import shlex
import subprocess
import sys
from pathlib import Path

from lento_library.library import Library


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lento-library", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check", "add", "convert", "watch"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".", help="library folder (default: current folder)")
        if name == "check":
            p.add_argument("--list", help="practice list CSV to cross-check")
            p.add_argument("--column", default="piece_id")
        if name in ("convert", "watch"):
            p.add_argument("--converter", help="command that runs Lento_ConvertPDF (default: this Python's lento_convertpdf)")
            p.add_argument("--gpu", default="force", choices=["force", "auto", "no"])
        if name == "convert":
            p.add_argument("piece_ids", nargs="*")
            p.add_argument("--missing", action="store_true", help="every piece with a PDF and no MusicXML")
        if name == "watch":
            p.add_argument("--interval", type=float, default=30, help="seconds between looks at the queue (default 30)")
            p.add_argument("--once", action="store_true", help="look once, convert what is queued, and stop")
            p.add_argument("--install", action="store_true", help="start the watcher at every Windows sign-in")
            p.add_argument("--uninstall", action="store_true", help="stop starting it at sign-in")
        if name == "add":
            p.add_argument("file")
            p.add_argument("piece_id")
            p.add_argument("variant")
    args = ap.parse_args(argv)
    lib = Library(args.root)

    try:
        if args.cmd == "build":
            path, n = lib.write_index()
            print(f"wrote {path} ({n} pieces)")
            return 0
        if args.cmd == "convert":
            return convert(lib, args)
        if args.cmd == "watch":
            from lento_library import watch

            if args.install or args.uninstall:
                print(watch.install(lib.root, args.interval) if args.install else watch.uninstall())
                return 0
            return watch.run(lib, converter_cmd(args), args.gpu, args.interval, once=args.once)
        if args.cmd == "add":
            src = Path(args.file)
            if not src.exists():
                src = lib.root / "inbox" / args.file
            dest = lib.add(src, args.piece_id, args.variant)
            print(f"added {dest.relative_to(lib.root)}")
            if dest.suffix == ".pdf":
                print("fill in composer, title and tags in catalog.csv, then run: lento-library build")
            return 0
        ids = None
        if args.list:
            with open(args.list, newline="", encoding="utf-8-sig") as f:
                ids = {r[args.column].strip() for r in csv.DictReader(f) if r.get(args.column)}
        rep = lib.check(ids)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for n in rep.notes:
        print("note:", n)
    for p in rep.problems:
        print("PROBLEM:", p)
    print(f"{len(rep.problems)} problem(s), {len(rep.notes)} note(s)")
    return 1 if rep.problems else 0


def converter_cmd(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.converter, posix=sys.platform != "win32") if args.converter else [sys.executable, "-m", "lento_convertpdf"]


def convert_pdfs(lib: Library, pdfs: list[Path], cmd: list[str], gpu: str, on_folder=None) -> list[str]:
    """Converts the PDFs' folders one at a time (the converter skips PDFs that already have MusicXML), clears the
    requests that worked, sets failed ones aside, and rebuilds library.json. Returns the names that failed."""
    folders = sorted({p.parent for p in pdfs})
    failed: list[str] = []
    for i, folder in enumerate(folders, 1):
        here = [p for p in pdfs if p.parent == folder]
        if on_folder:
            on_folder(i, len(folders), folder, here)
        print(f"[{i}/{len(folders)}] {folder.name}: converting…", flush=True)
        subprocess.run([*cmd, str(folder), "--no-recursive", "--gpu", gpu], check=False)
        for pdf in here:
            if any((folder / f"{pdf.stem}{ext}").is_file() for ext in (".musicxml", ".mxl", ".xml")):
                lib.clear_request(pdf.stem)
            else:
                lib.fail_request(pdf.stem)
                failed.append(pdf.name)
    return failed


def convert(lib: Library, args: argparse.Namespace) -> int:
    """Runs the converter as a separate program, so the library never depends on the converter's code."""
    if args.piece_ids:
        pdfs = [p for pid in args.piece_ids for p in sorted((lib.pieces / pid).glob("*.pdf"))]
    elif args.missing:
        pdfs = lib.pdfs_without_musicxml()
    else:
        pdfs = [p for p in (lib.pdf_for(stem) for stem in lib.requests()) if p]
    if not pdfs:
        print("nothing to convert" + ("" if args.missing else " (no requests; use --missing for every PDF without MusicXML)"))
        return 0
    failed = convert_pdfs(lib, pdfs, converter_cmd(args), args.gpu)
    path, n = lib.write_index()
    print(f"wrote {path} ({n} pieces); {len(pdfs) - len(failed)} PDF(s) converted, {len(failed)} failed")
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
