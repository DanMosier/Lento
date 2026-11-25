"""lento-practice: compare a recording of you playing with its score."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="lento-practice",
        description="Compare a recording with its MusicXML score and report intonation, timing and missed notes.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="analyse one recording")
    a.add_argument("score", type=Path, help=".musicxml, .xml or .mxl file")
    a.add_argument("audio", type=Path, help="recording: .wav, .flac, .ogg or .mp3")
    a.add_argument("--out", type=Path, help="folder for the report (default: <audio name>_feedback next to the recording)")
    a.add_argument("--part", help="part id or name, if the score has several parts (default: the cello part)")
    a.add_argument("--measures", help="the measures you played, e.g. 12-20 (default: found automatically)")
    a.add_argument("--a4", type=float, default=440.0, help="tuning pitch of A4 in Hz (default 440)")
    a.add_argument("--pitch", choices=["strict", "standard", "relaxed"], default="standard",
                   help="how strict about pitch: in tune within 5, 10 or 20 cents (default standard)")
    a.add_argument("--timing", choices=["strict", "standard", "relaxed"], default="standard",
                   help="how strict about timing: flagged beyond 60, 100 or 160 ms (default standard)")
    a.add_argument("--in-tune", type=float, help="exact cents that count as in tune (overrides --pitch)")
    a.add_argument("--slightly-off", type=float, help="exact cents that count as slightly off (overrides --pitch)")
    a.add_argument("--timing-ms", type=float, help="exact ms early or late before a note is flagged (overrides --timing)")
    a.add_argument("--no-labels", action="store_true", help="color the notes but do not write text under them")
    args = p.parse_args(argv)

    from .analyze import PITCH_WINDOWS, TIMING_WINDOWS, AnalysisSettings, analyze
    from .report import summary_markdown, write_report

    for f in (args.score, args.audio):
        if not f.is_file():
            print(f"error: {f} does not exist", file=sys.stderr)
            return 2
    measures = None
    if args.measures:
        first, _, last = args.measures.partition("-")
        measures = (first.strip(), (last or first).strip())
    settings = AnalysisSettings(
        a4=args.a4,
        good_cents=args.in_tune if args.in_tune is not None else PITCH_WINDOWS[args.pitch][0],
        ok_cents=args.slightly_off if args.slightly_off is not None else PITCH_WINDOWS[args.pitch][1],
        timing_ms=args.timing_ms if args.timing_ms is not None else TIMING_WINDOWS[args.timing],
        part=args.part,
        measures=measures,
    )
    try:
        analysis = analyze(args.score, args.audio, settings)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = args.out or args.audio.with_name(args.audio.stem + "_feedback")
    paths = write_report(analysis, out, labels=not args.no_labels)
    print(summary_markdown(analysis))
    print(f"Report written to {out}")
    print(f"Open {paths['score'].name} in MuseScore to see the colored notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
