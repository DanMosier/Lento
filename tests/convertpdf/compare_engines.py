"""Run the same PDFs through several OMR set-ups and score each against its reference MusicXML.

Answers two questions with one table:
- Does homr read as well on the CPU as on the GPU? (homr-gpu vs homr-cpu, plus how often the two agree)
- How does Audiveris compare with homr on the same scores?

    python tests/convertpdf/compare_engines.py                      # the fixtures, all three set-ups
    python tests/convertpdf/compare_engines.py --scores "G:\\...\\pieces" --variants homr-gpu audiveris
    python tests/convertpdf/compare_engines.py --keep out\\engines   # keep every MusicXML for a look

A score is any PDF with a reference beside it of the same name (.mxl, .musicxml or .xml), for example a
MuseScore file the library exported to both PDF and MusicXML. Results go to engine-comparison.csv and .md in
the --keep folder (or the current folder).
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from compare_musicxml import compare  # noqa: E402

from lento_convertpdf.homr_runner import OMRConfig  # noqa: E402
from lento_convertpdf.models import PdfConversionItem  # noqa: E402
from lento_convertpdf.omr_engines import check_engine, convert_single_pdf  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
VARIANTS = {
    "homr-gpu": {"engine": "homr", "gpu": "force"},
    "homr-cpu": {"engine": "homr", "gpu": "no"},
    "audiveris": {"engine": "audiveris"},
}


@dataclass
class Row:
    score: str
    variant: str
    status: str
    seconds: float
    pitch_f1: float | None = None
    strict_f1: float | None = None
    quality: str = ""
    detail: str = ""


def reference_for(pdf: Path) -> Path | None:
    for ext in (".mxl", ".musicxml", ".xml"):
        if pdf.with_suffix(ext).is_file():
            return pdf.with_suffix(ext)
    return None


def find_scores(folders: list[Path], limit: int) -> list[tuple[Path, Path]]:
    found: list[tuple[Path, Path]] = []
    for folder in folders:
        for pdf in sorted(folder.rglob("*.pdf")):
            ref = reference_for(pdf)
            if ref and "_duplicates" not in pdf.parts:
                found.append((pdf, ref))
    return found[:limit] if limit else found


def run(args: argparse.Namespace) -> int:
    scores = find_scores(args.scores or [FIXTURES], args.limit)
    if not scores:
        print("No PDFs with a reference MusicXML beside them were found.")
        return 2
    keep = args.keep.resolve() if args.keep else None
    work = keep or Path(tempfile.mkdtemp(prefix="engines_"))
    report_dir = keep or Path.cwd()

    configs: dict[str, OMRConfig] = {}
    for name in args.variants:
        cfg = OMRConfig(homr_python=args.homr_python, audiveris_path=args.audiveris, instrument="", **VARIANTS[name])
        status = check_engine(cfg)
        print(f"{name:10} {status.details}")
        if not status.installed or (cfg.gpu == "force" and cfg.engine == "homr" and not status.cuda):
            print(f"{name:10} skipped")
            continue
        configs[name] = cfg
    if not configs:
        print("None of the set-ups can run here.")
        return 2

    rows: list[Row] = []
    outputs: dict[tuple[str, str], Path] = {}
    for pdf, ref in scores:
        for name, cfg in configs.items():
            out_dir = work / name
            cfg.output_dir = out_dir
            item = convert_single_pdf(PdfConversionItem(pdf_path=pdf, relative_path=pdf.name), cfg)
            row = Row(pdf.stem, name, item.status, round(item.duration_sec, 1), detail=item.error_message)
            if item.status == "converted" and item.output_musicxml_path:
                result = compare(ref, item.output_musicxml_path)
                row.pitch_f1, row.strict_f1 = round(result.pitch.f1, 4), round(result.strict.f1, 4)
                row.quality = item.quality.level if item.quality else ""
                outputs[(pdf.stem, name)] = item.output_musicxml_path
            rows.append(row)
            f1 = f"pitch {row.pitch_f1:.1%}  strict {row.strict_f1:.1%}" if row.pitch_f1 is not None else row.detail
            print(f"{pdf.stem[:40]:40} {name:10} {row.seconds:7.1f}s  {f1}", flush=True)

    # Where both homr set-ups ran: how much of the GPU reading the CPU reading reproduces
    agreement: dict[str, float] = {}
    for pdf, _ in scores:
        gpu, cpu = outputs.get((pdf.stem, "homr-gpu")), outputs.get((pdf.stem, "homr-cpu"))
        if gpu and cpu:
            agreement[pdf.stem] = round(compare(gpu, cpu).strict.f1, 4)

    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "engine-comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["score", "variant", "status", "seconds", "pitch_f1", "strict_f1", "quality", "detail", "gpu_cpu_agreement"])
        for r in rows:
            writer.writerow([r.score, r.variant, r.status, r.seconds, r.pitch_f1, r.strict_f1, r.quality, r.detail,
                             agreement.get(r.score, "") if r.variant == "homr-cpu" else ""])
    (report_dir / "engine-comparison.md").write_text(markdown(rows, list(configs), agreement), encoding="utf-8")
    print(f"\nWrote {report_dir / 'engine-comparison.md'} and .csv")
    return 0


def markdown(rows: list[Row], variants: list[str], agreement: dict[str, float]) -> str:
    def cell(r: Row | None) -> str:
        if r is None:
            return ""
        if r.pitch_f1 is None:
            return f"failed ({r.seconds:.0f}s)"
        return f"{r.pitch_f1:.1%} / {r.strict_f1:.1%} ({r.seconds:.0f}s)"

    by = {(r.score, r.variant): r for r in rows}
    scores = list(dict.fromkeys(r.score for r in rows))
    lines = [
        f"# Engine comparison, {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "Each cell: pitch F1 / strict F1 (pitch, onset and duration) against the reference, and the time taken.",
        "",
        "| Score | " + " | ".join(variants) + (" | GPU-CPU agreement |" if agreement else " |"),
        "|---|" + "---|" * len(variants) + ("---|" if agreement else ""),
    ]
    for s in scores:
        line = f"| {s} | " + " | ".join(cell(by.get((s, v))) for v in variants) + " |"
        if agreement:
            line += f" {agreement[s]:.1%} |" if s in agreement else " |"
        lines.append(line)
    average = "| **Average** | " + " | ".join(_average(rows, v) for v in variants) + " |"
    if agreement:
        average += f" {sum(agreement.values()) / len(agreement):.1%} |"
    lines.append(average)
    return "\n".join(lines) + "\n"


def _average(rows: list[Row], variant: str) -> str:
    done = [r for r in rows if r.variant == variant and r.pitch_f1 is not None]
    failed = sum(1 for r in rows if r.variant == variant and r.pitch_f1 is None)
    if not done:
        return f"{failed} failed"
    pitch = sum(r.pitch_f1 or 0 for r in done) / len(done)
    strict = sum(r.strict_f1 or 0 for r in done) / len(done)
    secs = sum(r.seconds for r in done) / len(done)
    return f"{pitch:.1%} / {strict:.1%} ({secs:.0f}s avg)" + (f", {failed} failed" if failed else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scores", type=Path, nargs="*", help="folders with PDFs and reference MusicXML (default: the fixtures)")
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--limit", type=int, default=0, help="only the first N scores")
    parser.add_argument("--keep", type=Path, help="folder for every MusicXML written and the report")
    parser.add_argument("--homr-python", default="")
    parser.add_argument("--audiveris", default="")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
