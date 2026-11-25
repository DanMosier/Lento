"""lento-library: keep the score library tidy and build the library.json index the app reads.

  lento-library build [--root FOLDER]
      Writes FOLDER/library.json from the piece folders and catalog.csv. Run it after any change.
  lento-library check [--root FOLDER] [--list practice.csv] [--column piece_id]
      Checks that folders, files, catalog.csv and tags.md agree.
  lento-library add FILE PIECE_ID VARIANT [--root FOLDER]
      Moves FILE (from inbox/ if not found as given) to pieces/<piece_id>/<piece_id>__<variant>.<ext>.

FOLDER defaults to the current folder.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from lento_library.library import Library


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lento-library", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check", "add"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".", help="library folder (default: current folder)")
        if name == "check":
            p.add_argument("--list", help="practice list CSV to cross-check")
            p.add_argument("--column", default="piece_id")
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


if __name__ == "__main__":
    sys.exit(main())
