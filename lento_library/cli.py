"""lento-library: keep the score library tidy and build the library.json index the app reads.

  lento-library build [--root FOLDER]
      Writes FOLDER/library.json from the piece folders and catalog.csv. Run it after any change.
  lento-library check [--root FOLDER] [--list practice.csv] [--column piece_id]
      Checks that folders, files, catalog.csv and tags.md agree.
  lento-library add FILE PIECE_ID VARIANT [--root FOLDER]
      Moves FILE (from inbox/ if not found as given) to pieces/<piece_id>/<piece_id>__<variant>.<ext>.

  lento-library convert [PIECE_ID ...] [--missing] [--root FOLDER] [--converter CMD] [--musescore EXE]
      Makes MusicXML from PDFs with Lento_ConvertPDF (homr, on this PC's GPU), saved beside each PDF under the
      same name, then rebuilds library.json. With no PIECE_ID, converts the PDFs requested from the app
      ("Make MusicXML"); --missing converts every PDF that has no MusicXML yet. Existing MusicXML is kept.
      It also exports every MuseScore file (.mscz/.mscx) in the library to MusicXML and PDF beside it, using
      MuseScore itself (found automatically, or give --musescore). Those exports are exact, and redone when the
      MuseScore file changes.

  lento-library watch [--root FOLDER] [--interval SECONDS] [--install | --uninstall]
      Keeps running and converts PDFs as soon as they are queued from the app, whenever this PC is on, and
      exports MuseScore files as soon as they appear in the library.
      Writes requests/_status.json so the app can show what the PC is doing. --install starts it hidden
      at every Windows sign-in (Startup folder); --uninstall removes that.

  lento-library organize plan | status | apply BATCH | undo BATCH [--root FOLDER]
      Files an existing, unorganized score folder into pieces/, one batch (top folder) at a time. "plan" writes
      organize-plan.csv (nothing moves; edit ids there, or set action to skip); "status" lists the batches;
      "apply" moves one batch and logs it to organize-log.csv; "undo" puts a batch back.

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
    for name in ("build", "check", "add", "convert", "watch", "organize"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".", help="library folder (default: current folder)")
        if name == "check":
            p.add_argument("--list", help="practice list CSV to cross-check")
            p.add_argument("--column", default="piece_id")
        if name in ("convert", "watch"):
            p.add_argument("--converter", help="command that runs Lento_ConvertPDF (default: this Python's lento_convertpdf)")
            p.add_argument("--gpu", default="force", choices=["force", "auto", "no"])
            p.add_argument("--musescore", help="the MuseScore program (default: found in the usual places)")
        if name == "convert":
            p.add_argument("piece_ids", nargs="*")
            p.add_argument("--missing", action="store_true", help="every piece with a PDF and no MusicXML")
        if name == "watch":
            p.add_argument("--interval", type=float, default=30, help="seconds between looks at the queue (default 30)")
            p.add_argument("--once", action="store_true", help="look once, convert what is queued, and stop")
            p.add_argument("--install", action="store_true", help="start the watcher at every Windows sign-in")
            p.add_argument("--uninstall", action="store_true", help="stop starting it at sign-in")
        if name == "organize":
            p.add_argument("step", choices=["plan", "status", "apply", "undo"])
            p.add_argument("batch", nargs="?", help="the batch (top folder name) for apply and undo")
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
            return watch.run(lib, converter_cmd(args), args.gpu, args.interval, once=args.once, musescore=args.musescore)
        if args.cmd == "organize":
            return organize(lib, args.step, args.batch)
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


def organize(lib: Library, step: str, batch: str | None) -> int:
    from lento_library import organize as org

    if step == "plan":
        path, n = org.plan(lib)
        print(f"wrote {path} ({n} files). Check it, then: lento-library organize status")
        step = "status"
    if step == "status":
        rows = org.batches(lib)
        if not rows:
            print("nothing planned: run lento-library organize plan")
        for name, (todo, done) in sorted(rows.items()):
            print(f"{todo:4d} to move  {done:4d} moved   {name}")
        return 0
    if not batch:
        print(f"error: say which batch to {step}, e.g. lento-library organize {step} \"Villa-Lobos, Heitor\"", file=sys.stderr)
        return 2
    if step == "undo":
        back = org.undo(lib, batch)
        print(f"put back {len(back)} file(s) from '{batch}'")
        return 0
    moved, problems = org.apply(lib, batch)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        print(f"nothing moved: fix these in {org.PLAN} and run it again", file=sys.stderr)
        return 1
    for m in moved:
        print("moved", m)
    print(f"{len(moved)} file(s) filed from '{batch}'; library.json rebuilt. To put them back: lento-library organize undo \"{batch}\"")
    return 0


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


def export_musescore(lib: Library, explicit: str | None = None, only: list[str] | None = None) -> tuple[list[str], list[str], bool]:
    """Exports MuseScore files that need it. Returns (exported, failed, musescore_found)."""
    from lento_library import musescore

    files = [p for p in lib.musescore_files() if not only or p.parent.name in only]
    if not files:
        return [], [], True
    exe = musescore.find(explicit)
    if not exe:
        print(f"{len(files)} MuseScore file(s) to export, but MuseScore isn't installed (or give --musescore)", flush=True)
        return [], [p.name for p in files], False
    print(f"exporting {len(files)} MuseScore file(s) to MusicXML and PDF…", flush=True)
    done = musescore.export(exe, files)
    for src, ok in done.items():
        if ok:
            lib.catalog_export(src.with_suffix(".pdf"))
    return [s.name for s, ok in done.items() if ok], [s.name for s, ok in done.items() if not ok], True


def convert(lib: Library, args: argparse.Namespace) -> int:
    """Runs the converter as a separate program, so the library never depends on the converter's code."""
    exported, ms_failed, _ = export_musescore(lib, args.musescore, args.piece_ids or None)
    if exported or ms_failed:
        print(f"MuseScore: {len(exported)} exported, {len(ms_failed)} failed" + "".join(f"\n  failed: {n}" for n in ms_failed))
    if args.piece_ids:
        pdfs = [p for pid in args.piece_ids for p in sorted((lib.pieces / pid).glob("*.pdf"))]
    elif args.missing:
        pdfs = lib.pdfs_without_musicxml()
    else:
        pdfs = [p for p in (lib.pdf_for(stem) for stem in lib.requests()) if p]
    if not pdfs:
        if exported or ms_failed:
            lib.write_index()
            return 1 if ms_failed else 0
        print("nothing to convert" + ("" if args.missing else " (no requests; use --missing for every PDF without MusicXML)"))
        return 0
    failed = convert_pdfs(lib, pdfs, converter_cmd(args), args.gpu)
    path, n = lib.write_index()
    print(f"wrote {path} ({n} pieces); {len(pdfs) - len(failed)} PDF(s) converted, {len(failed)} failed")
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed or ms_failed else 0


if __name__ == "__main__":
    sys.exit(main())
