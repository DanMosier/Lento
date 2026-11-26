"""Command-line interface for lento_convertpdf batch conversion and open-source VST audio rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio_player import synthesize_score_to_wav
from .homr_runner import GPU_MODES, OMRConfig
from .models import VALID_ENGINES, PdfConversionItem
from .musicxml_parser import parse_musicxml
from .omr_engines import batch_convert_pdfs, check_engine, scan_folder_for_pdfs
from .pdf_splitter import analyze_multi_piece_pdf, execute_pdf_split
from .quality import REVIEW_BELOW
from .vst_catalog import (
    OPEN_SOURCE_VST_CATALOG,
    deep_search_and_download_vsts,
    source_all_recommended_vsts,
)


def _fraction(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Lento_ConvertPDF",
        description=(
            "Batch convert sheet music PDFs into MusicXML using homr or Audiveris, "
            "and preview/render MusicXML scores with recommended open-source VST instrument profiles."
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        help="Folder containing sheet music PDFs to import and convert (or omit to launch the GUI).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the full desktop GUI.",
    )
    parser.add_argument(
        "--engine",
        choices=VALID_ENGINES,
        default="homr",
        help="OMR engine: homr (default, GPU) or audiveris (CPU, installed separately).",
    )
    parser.add_argument(
        "--audiveris",
        default="",
        help="Path to Audiveris.exe (default: AUDIVERIS, then the usual install folders and PATH).",
    )
    parser.add_argument(
        "--gpu",
        choices=GPU_MODES,
        default="force",
        help="homr only. force = fail unless CUDA is in use (default), auto = use CUDA if available, no = CPU.",
    )
    parser.add_argument(
        "--review-below",
        type=_fraction,
        default=REVIEW_BELOW,
        metavar="0-1",
        help=f"Flag exports whose quality estimate is lower than this (default: {REVIEW_BELOW}).",
    )
    parser.add_argument(
        "--instrument",
        default="Cello",
        help='Name for one-staff parts homr can\'t identify (it calls them "Voice"). Default: Cello. "" keeps "Voice".',
    )
    parser.add_argument(
        "--homr-python",
        default="",
        help="python.exe of the homr environment (default: HOMR_PYTHON, then a homr folder beside the project).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory to save converted .musicxml files (default: alongside each PDF).",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan top-level PDFs in the folder (do not recurse into subfolders).",
    )
    parser.add_argument(
        "--list-vsts",
        action="store_true",
        help="List the recommended open-source VST/VST3 plugins for each instrument category.",
    )
    parser.add_argument(
        "--source-vsts",
        action="store_true",
        help="Source/install all recommended open-source VST profiles into the managed VST directory.",
    )
    parser.add_argument(
        "--deep-search-vsts",
        action="store_true",
        help=(
            "Conduct a deep search into recommended open-source VSTs, auto-download available portable "
            "assets/profiles, and output a report with direct links for any requiring manual intervention."
        ),
    )
    parser.add_argument(
        "--render-wav",
        type=Path,
        default=None,
        help="Render a converted .musicxml/.mxl file to a stereo .wav file using open-source VST synthesis.",
    )
    parser.add_argument(
        "--split-pdf",
        type=Path,
        default=None,
        help="Analyze a multi-piece PDF (auto-recognizing pypdf vs. Vision splitting) and split it into separate PDFs.",
    )
    parser.add_argument(
        "--split-mode",
        choices=("auto", "pypdf", "vision"),
        default="auto",
        help="Split boundary detection mode for --split-pdf (default: auto).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_vsts:
        print("=== Recommended Open-Source VST / VST3 Plugins by Instrument ===")
        for spec in OPEN_SOURCE_VST_CATALOG:
            print(f"- [{spec.instrument_category.upper()}] {spec.name} ({spec.license})")
            print(f"    Matched : {', '.join(spec.instruments_matched)}")
            print(f"    Repo    : {spec.repo_url}")
        return 0

    if args.source_vsts:
        paths = source_all_recommended_vsts(query_github_release=True)
        print(f"Sourced {len(paths)} open-source VST bundle(s):")
        for p in paths:
            print(f"  - {p}")
        return 0

    if args.deep_search_vsts:
        report = deep_search_and_download_vsts(
            download_portable_assets=True,
            search_github_live=True,
        )
        print("=== Open-Source VST Deep Search & Auto-Download Report ===")
        print(f"Evaluated Setups              : {report.total_evaluated}")
        print(f"Auto-Downloaded Profiles/Packs: {len(report.auto_downloaded)}")
        print(f"Requiring Manual Intervention : {len(report.manual_intervention)}")
        print("\n--- 1. Automatically Downloaded Files ---")
        for item in report.auto_downloaded:
            files_str = ", ".join(p.name for p in item.auto_downloaded_files)
            print(f"  [OK] [{item.instrument_category.upper()}] {item.name} -> {files_str}")
        print("\n--- 2. Recommended VSTs / Sample Banks Requiring Manual Intervention ---")
        for item in report.manual_intervention:
            print(f"  [MANUAL] [{item.instrument_category.upper()}] {item.name}")
            print(f"     Reason : {item.manual_reason}")
            for lbl, url in item.associated_links.items():
                print(f"     Link ({lbl}): {url}")
        if report.markdown_report_path:
            print(f"\nFull Markdown Report with clickable links saved to:\n  {report.markdown_report_path}")
        return 0

    if args.render_wav:
        xml_path = args.render_wav.resolve()
        if not xml_path.is_file():
            print(f"Error: MusicXML file not found: {xml_path}", file=sys.stderr)
            return 2
        score = parse_musicxml(xml_path)
        wav_out = xml_path.with_suffix(".wav")
        synthesize_score_to_wav(score, wav_out, sample_rate=44100)
        print(f"Rendered '{score.title}' ({len(score.parts)} part(s)) to: {wav_out}")
        return 0

    if args.split_pdf:
        pdf_p = args.split_pdf.resolve()
        if not pdf_p.is_file():
            print(f"Error: PDF file not found: {pdf_p}", file=sys.stderr)
            return 2
        report = analyze_multi_piece_pdf(pdf_p, mode=args.split_mode)
        print(f"=== Multi-Piece PDF Split Analysis: {pdf_p.name} ===")
        print(f"Recommended Method : {report.recommended_method.upper()}")
        print(f"Method Used        : {report.method_used.upper()}")
        print(f"Assessment         : {report.method_reason}")
        print(f"Pieces Detected    : {len(report.segments)}")
        for seg in report.segments:
            print(
                f"  [{seg.index:02d}] Pages {seg.start_page}-{seg.end_page} ({seg.page_count}p): "
                f"{seg.proposed_filename} (conf={seg.confidence:.2f}, {seg.detection_source}; {seg.notes})"
            )
        out_folder = args.output_dir.resolve() if args.output_dir else pdf_p.parent
        created = execute_pdf_split(pdf_p, report.segments, output_dir=out_folder)
        print(f"\nSplit into {len(created)} PDF file(s) in {out_folder}:")
        for c in created:
            print(f"  - {c.name}")
        return 0

    if args.gui or args.directory is None:
        from .gui import launch_gui

        return launch_gui(initial_directory=args.directory)

    if not args.directory.is_dir():
        print(f"Error: directory does not exist: {args.directory}", file=sys.stderr)
        return 2

    config = OMRConfig(
        engine=args.engine,
        audiveris_path=args.audiveris,
        output_dir=args.output_dir,
        recursive=not args.no_recursive,
        gpu=args.gpu,
        homr_python=args.homr_python,
        review_below=args.review_below,
        instrument=args.instrument,
        # "page 2/5: name.pdf" lines let lento-library show how far a PDF has got
        on_page=lambda pdf, page, pages: print(f"      page {page}/{pages}: {pdf.name}", flush=True),
    )

    avail = check_engine(config)
    print(f"=== Lento_ConvertPDF: PDF to MusicXML ({args.engine}) ===")
    print(f"Engine status: {avail.details}")

    items = scan_folder_for_pdfs(args.directory, recursive=config.recursive, output_dir=config.output_dir)
    print(f"Found {len(items)} PDF file(s) in {args.directory.resolve()}")

    def _on_prog(item: PdfConversionItem, idx: int, total: int) -> None:
        print(
            f"[{idx}/{total}] {item.status.upper()}: {item.pdf_path.name} -> "
            f"{item.output_musicxml_path.name if item.output_musicxml_path else item.error_message} "
            f"({item.duration_sec:.1f}s)"
        )
        if item.quality:
            print(f"      {item.quality.summary}")

    batch_convert_pdfs(items, config=config, progress_callback=_on_prog)
    converted = sum(1 for it in items if it.status == "converted")
    failed = sum(1 for it in items if it.status == "failed")
    flagged = sum(1 for it in items if it.quality and it.quality.level != "good")
    print(f"\nDone: {converted} converted ({flagged} flagged for checking), {failed} failed.")
    return 0 if failed == 0 else 1
