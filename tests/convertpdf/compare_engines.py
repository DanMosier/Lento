"""Run the same PDFs through several OMR set-ups and score each against its reference MusicXML.

Answers two questions with one table:
- Does homr read as well on the CPU as on the GPU? (homr-gpu vs homr-cpu, plus how often the two agree)
- How does Audiveris compare with homr on the same scores?

    python tests/convertpdf/compare_engines.py                      # the fixtures, all three set-ups
    python tests/convertpdf/compare_engines.py --scores "G:\\...\\pieces" --variants homr-gpu audiveris
    python tests/convertpdf/compare_engines.py --keep out\\engines   # keep every MusicXML for a look

A score is any PDF or page image with a reference beside it of the same name (.mxl, .musicxml or .xml), for
example a MuseScore file the library exported to both PDF and MusicXML. In the sheet-music-photos dataset
(github.com/liebharc/sheet-music-photos) that is each hand-checked page (page.pdf + page.musicxml), and each photo
in its photos/ folder is scored against the same page.musicxml. Pages with only homr's own reading
(reference.musicxml) are left out, since they would favour homr. Results go to engine-comparison.csv and .md in
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

from lento_convertpdf.homr_runner import IMAGE_SUFFIXES, OMRConfig  # noqa: E402
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


GENERIC_STEMS = {"page", "score", "print"}  # file names that say nothing: the folder names the score


def score_name(source: Path) -> str:
    return source.parent.name if source.stem.lower() in GENERIC_STEMS else source.stem


def find_scores(folders: list[Path], limit: int) -> list[tuple[str, Path, Path]]:
    """(name, PDF or image, reference) for every score under the folders."""
    found: list[tuple[str, Path, Path]] = []
    suffixes = (".pdf", *IMAGE_SUFFIXES)
    for folder in folders:
        for source in sorted(p for p in folder.rglob("*") if p.suffix.lower() in suffixes and p.is_file()):
            if "_duplicates" in source.parts:
                continue
            ref = reference_for(source)
            if ref:
                found.append((score_name(source), source, ref))
            elif source.parent.name == "photos" and (source.parent.parent / "page.musicxml").is_file():
                found.append((f"{source.parent.parent.name} photo {source.stem}", source, source.parent.parent / "page.musicxml"))
    return found[:limit] if limit else found


def run(args: argparse.Namespace) -> int:
    scores = find_scores(args.scores or [FIXTURES], args.limit)
    if not scores:
        print("No PDFs or page images with a reference MusicXML beside them were found.")
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
    for score, pdf, ref in scores:
        for name, cfg in configs.items():
            cfg.output_dir = work / name / "".join(c if c.isalnum() or c in "-_." else "_" for c in score)
            item = convert_single_pdf(PdfConversionItem(pdf_path=pdf, relative_path=pdf.name), cfg)
            row = Row(score, name, item.status, round(item.duration_sec, 1), detail=item.error_message)
            if item.status == "converted" and item.output_musicxml_path:
                result = compare(ref, item.output_musicxml_path)
                row.pitch_f1, row.strict_f1 = round(result.pitch.f1, 4), round(result.strict.f1, 4)
                row.quality = item.quality.level if item.quality else ""
                outputs[(score, name)] = item.output_musicxml_path
            rows.append(row)
            f1 = f"pitch {row.pitch_f1:.1%}  strict {row.strict_f1:.1%}" if row.pitch_f1 is not None else row.detail
            print(f"{score[:40]:40} {name:10} {row.seconds:7.1f}s  {f1}", flush=True)

    # Where both homr set-ups ran: how much of the GPU reading the CPU reading reproduces
    agreement: dict[str, float] = {}
    for score, _, _ in scores:
        gpu, cpu = outputs.get((score, "homr-gpu")), outputs.get((score, "homr-cpu"))
        if gpu and cpu:
            agreement[score] = round(compare(gpu, cpu).strict.f1, 4)

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
    parser.add_argument("--scores", type=Path, nargs="*",
                        help="folders with PDFs or page images and reference MusicXML (default: the fixtures)")
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--limit", type=int, default=0, help="only the first N scores")
    parser.add_argument("--keep", type=Path, help="folder for every MusicXML written and the report")
    parser.add_argument("--homr-python", default="")
    parser.add_argument("--audiveris", default="")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
