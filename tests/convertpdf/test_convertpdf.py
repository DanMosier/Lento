"""Unit tests for folder scanning, MusicXML parser, PDF splitter, open-source VST catalog, and audio player."""

from __future__ import annotations

import wave
import zipfile
from pathlib import Path

import pypdf

from lento_convertpdf.audio_player import synthesize_score_to_wav
from lento_convertpdf.cli import main as cli_main
from lento_convertpdf.musicxml_parser import parse_musicxml, pitch_to_midi_and_name
from lento_convertpdf.omr_engines import extract_mxl_to_musicxml, scan_folder_for_pdfs
from lento_convertpdf.vst_catalog import (
    OPEN_SOURCE_VST_CATALOG,
    classify_instrument_category,
    recommend_vst_for_instrument,
    source_all_recommended_vsts,
    source_open_source_vst_bundle,
)


def _create_dummy_pdf(path: Path, num_pages: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)
    return path


def _write_trio(path: Path) -> None:
    """A small 3-part score: 4 measures of quarter notes each."""
    names = ("Violin", "Violoncello", "Piano")
    note = "<note><pitch><step>{}</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>"
    attributes = (
        "<attributes><divisions>1</divisions><key><fifths>0</fifths></key>"
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
    )
    bar = "".join(note.format(step) for step in "CEGE")
    parts = "".join(
        f"<part id='P{i}'>"
        + "".join(f"<measure number='{m}'>{attributes if m == 1 else ''}{bar}</measure>" for m in range(1, 5))
        + "</part>"
        for i in range(1, 4)
    )
    plist = "".join(f"<score-part id='P{i}'><part-name>{n}</part-name></score-part>" for i, n in enumerate(names, 1))
    path.write_text(
        "<score-partwise><work><work-title>Test Trio</work-title></work>"
        f"<part-list>{plist}</part-list>{parts}</score-partwise>",
        encoding="utf-8",
    )


def test_scan_folder_and_selection_filtering(tmp_path: Path) -> None:
    _create_dummy_pdf(tmp_path / "Bach, Johann Sebastian - Cello Suite No. 1 Cello.pdf", num_pages=2)
    _create_dummy_pdf(tmp_path / "sub" / "Chopin, Frederic - Nocturne Op. 9 No. 2 Piano.pdf", num_pages=3)
    _create_dummy_pdf(tmp_path / "_duplicates" / "ignored.pdf", num_pages=1)

    items = scan_folder_for_pdfs(tmp_path, recursive=True)
    assert len(items) == 2
    assert all(it.selected for it in items)
    assert items[0].page_count == 2
    assert items[1].page_count == 3


def test_open_source_vst_recommendations_for_each_instrument(tmp_path: Path) -> None:
    assert len(OPEN_SOURCE_VST_CATALOG) >= 10

    cases = [
        ("Grand Piano", 1, "piano", "sfizz_salamander_piano"),
        ("Electric Piano", 5, "piano", "dexed_epiano"),
        ("Violin I", 41, "strings", "sfizz_sso_strings"),
        ("Violoncello", 43, "strings", "sfizz_sso_strings"),
        ("Flute", 74, "woodwinds", "sfizz_sso_woodwinds"),
        ("Clarinet in Bb", 72, "woodwinds", "sfizz_sso_woodwinds"),
        ("French Horn", 61, "brass", "sfizz_vpo_brass"),
        ("Trumpet in Bb", 57, "brass", "sfizz_vpo_brass"),
        ("Classical Guitar", 25, "guitar", "sfizz_freepats_plucked"),
        ("Orchestral Harp", 47, "guitar", "sfizz_freepats_plucked"),
        ("Pipe Organ", 20, "organ", "setbfree_organ"),
        ("Choir / Soprano", 53, "choir", "sfizz_sso_choir"),
        ("Timpani & Percussion", 48, "percussion", "geonkick_percussion"),
    ]
    for part_name, midi_prog, expected_cat, expected_vst_id in cases:
        cat = classify_instrument_category(part_name, midi_prog)
        assert cat == expected_cat
        spec = recommend_vst_for_instrument(part_name, midi_prog)
        assert spec.id == expected_vst_id

    # Test sourcing open-source VST bundles to a managed folder
    bundle_path = source_open_source_vst_bundle(
        "sfizz_salamander_piano", target_dir=tmp_path, query_github_release=False
    )
    assert bundle_path.is_file()

    all_bundles = source_all_recommended_vsts(target_dir=tmp_path, query_github_release=False)
    assert len(all_bundles) == len(OPEN_SOURCE_VST_CATALOG)


def test_musicxml_parser_and_mxl_extraction_and_wav_synthesis(tmp_path: Path) -> None:
    midi_c4, name_c4 = pitch_to_midi_and_name("C", 0, 4)
    assert midi_c4 == 60
    assert name_c4 == "C4"

    midi_fs5, name_fs5 = pitch_to_midi_and_name("F", 1, 5)
    assert midi_fs5 == 78
    assert name_fs5 == "F#5"

    xml1 = tmp_path / "trio.musicxml"
    _write_trio(xml1)

    # Create a compressed .mxl archive and test unpacking + parsing
    mxl_path = tmp_path / "packed_score.mxl"
    with zipfile.ZipFile(mxl_path, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container><rootfiles><rootfile full-path="score.musicxml"/></rootfiles></container>',
        )
        zf.write(xml1, arcname="score.musicxml")

    parsed_from_mxl = parse_musicxml(mxl_path)
    assert parsed_from_mxl.title == "Test Trio"
    assert len(parsed_from_mxl.parts) == 3  # Violin, Violoncello, Piano

    unpacked_xml = extract_mxl_to_musicxml(mxl_path, tmp_path / "unpacked.musicxml")
    assert unpacked_xml.is_file()

    assert parse_musicxml(unpacked_xml).total_measures == parsed_from_mxl.total_measures == 4

    # Synthesize multi-instrument WAV audio using the assigned open-source VST profiles
    wav_path = tmp_path / "trio_preview.wav"
    synthesize_score_to_wav(parsed_from_mxl, wav_path, sample_rate=22050, max_duration_sec=4.0)
    assert wav_path.is_file()

    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 22050
        assert wf.getnframes() > 22050


def test_cli_list_vsts() -> None:
    assert cli_main(["--list-vsts"]) == 0


def test_side_by_side_pdf_reader_page_rendering(tmp_path: Path) -> None:
    from lento_convertpdf.gui import render_pdf_page_image

    pdf_path = _create_dummy_pdf(tmp_path / "Debussy - Clair de Lune Piano.pdf", num_pages=3)
    img0, clamped0, total = render_pdf_page_image(pdf_path, page_index=0, fit_width=400, highlight_y_ratio=0.35)
    assert clamped0 == 0
    assert total == 3
    assert img0.width == 400
    assert img0.height > 400

    # Test clamping out-of-range page index and zoom factor
    img_last, clamped_last, total2 = render_pdf_page_image(pdf_path, page_index=99, zoom=1.25, fit_width=400)
    assert clamped_last == 2
    assert total2 == 3
    assert img_last.width == 500


def test_multi_piece_pdf_splitter_recognizes_pypdf_vs_vision(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw
    from lento_convertpdf.pdf_splitter import analyze_multi_piece_pdf, execute_pdf_split

    # 1. Create a 4-page PDF with pypdf Bookmark Outlines -> Reader must recognize "pypdf" as recommended_method
    bookmarked_pdf = tmp_path / "Bookmarked_Anthology.pdf"
    writer = pypdf.PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=612, height=792)
    writer.add_outline_item(title="Bach - Prelude No. 1 in C Major", page_number=0)
    writer.add_outline_item(title="Bach - Fugue No. 1 in C Major", page_number=2)
    with bookmarked_pdf.open("wb") as f:
        writer.write(f)

    rep_pypdf = analyze_multi_piece_pdf(bookmarked_pdf, mode="auto")
    assert rep_pypdf.recommended_method == "pypdf"
    assert rep_pypdf.method_used == "pypdf"
    assert rep_pypdf.has_bookmarks is True
    assert len(rep_pypdf.segments) == 2
    assert rep_pypdf.segments[0].start_page == 1
    assert rep_pypdf.segments[0].end_page == 2
    assert rep_pypdf.segments[1].start_page == 3
    assert rep_pypdf.segments[1].end_page == 4

    out_dir_1 = tmp_path / "split_pypdf"
    created_1 = execute_pdf_split(bookmarked_pdf, rep_pypdf.segments, output_dir=out_dir_1)
    assert len(created_1) == 2
    assert all(p.is_file() and len(pypdf.PdfReader(str(p)).pages) == 2 for p in created_1)

    # 2. Create a 4-page scanned/image-only PDF (0% embedded text, no bookmarks) where:
    #    - Page 1 & Page 3 have a centered dark title block at the top and the first 5-line staff starts lower (y=28%)
    #    - Page 2 & Page 4 are continuation pages where the first 5-line staff starts near the top (y=10%)
    #    -> Reader must recognize "vision" as recommended_method and split at Page 1 (1-2) and Page 3 (3-4)!
    page_imgs: list[Image.Image] = []
    for p_idx in range(4):
        img = Image.new("RGB", (600, 800), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        is_new_piece_page = p_idx in (0, 2)
        if is_new_piece_page:
            # Draw bold centered title block in top header zone
            draw.rectangle((180, 55, 420, 85), fill=(20, 20, 20))
            draw.rectangle((220, 95, 380, 110), fill=(40, 40, 40))
            first_staff_y = 225  # 28% down the page
        else:
            first_staff_y = 85  # 10.6% down the page

        # Draw 3 systems of 5-line staves
        for sys_i in range(3):
            base_y = first_staff_y + sys_i * 170
            for line_i in range(5):
                ly = base_y + line_i * 10
                draw.line((60, ly, 540, ly), fill=(10, 10, 10), width=2)
        page_imgs.append(img)

    scanned_pdf = tmp_path / "Scanned_MultiPiece_Collection.pdf"
    page_imgs[0].save(str(scanned_pdf), "PDF", resolution=72.0, save_all=True, append_images=page_imgs[1:])

    rep_vision = analyze_multi_piece_pdf(scanned_pdf, mode="auto", use_winrt_ocr=False)
    assert rep_vision.recommended_method == "vision"
    assert rep_vision.method_used == "vision"
    assert len(rep_vision.segments) == 2
    assert rep_vision.segments[0].start_page == 1
    assert rep_vision.segments[0].end_page == 2
    assert rep_vision.segments[1].start_page == 3
    assert rep_vision.segments[1].end_page == 4

    out_dir_2 = tmp_path / "split_vision"
    created_2 = execute_pdf_split(scanned_pdf, rep_vision.segments, output_dir=out_dir_2)
    assert len(created_2) == 2
    assert all(p.is_file() and len(pypdf.PdfReader(str(p)).pages) == 2 for p in created_2)


def test_overlapping_pages_and_midpage_cutoff_splitting(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw
    from lento_convertpdf.gui import render_pdf_page_image
    from lento_convertpdf.pdf_splitter import (
        PdfPieceSegment,
        analyze_multi_piece_pdf,
        execute_pdf_split,
        find_midpage_cutoff_y_ratio,
        resolve_overlapping_page_cutoffs,
    )

    # Create a 3-page PDF where Page 2 is a SHARED / OVERLAPPING page:
    # - Piece 1 starts on Page 1 and ends midway down Page 2 (staves at y=85 and y=205)
    # - Piece 2 starts midway down Page 2 (large gap after y=245, title banner at y=420, first staff of Piece 2 at y=500)
    #   and continues through Page 3.
    pages: list[Image.Image] = []
    for p_idx in range(3):
        img = Image.new("RGB", (600, 800), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        if p_idx == 0:
            # Page 1: Title at top + 3 staves
            draw.rectangle((180, 55, 420, 85), fill=(20, 20, 20))
            staff_ys = [220, 390, 560]
        elif p_idx == 1:
            # Page 2 (SHARED OVERLAPPING PAGE):
            # Upper piece finishes with 2 staves at y=85 and y=205 (bottom line at y=245)
            # Then a wide gap [245..500] with a clean whitespace separator [250..400] and Piece 2's title block at [415..455]
            # Then Piece 2's first staff at y=500 and second staff at y=630
            draw.rectangle((190, 415, 410, 450), fill=(20, 20, 20))
            staff_ys = [85, 205, 500, 630]
        else:
            # Page 3: Continuation of Piece 2 (4 normal staves)
            staff_ys = [85, 240, 395, 550]

        for base_y in staff_ys:
            for line_i in range(5):
                ly = base_y + line_i * 10
                draw.line((60, ly, 540, ly), fill=(10, 10, 10), width=2)
        pages.append(img)

    shared_pdf = tmp_path / "Overlapping_MidPage_Scores.pdf"
    pages[0].save(str(shared_pdf), "PDF", resolution=72.0, save_all=True, append_images=pages[1:])

    # 1. Verify `find_midpage_cutoff_y_ratio` finds the cutoff partway through Page 2 (between y=245/800=0.31 and y=415/800=0.52)
    cutoff_y, is_strong_midpage, reason = find_midpage_cutoff_y_ratio(shared_pdf, page_number=2)
    assert is_strong_midpage is True, f"Expected confident mid-page cutoff on Page 2, got: {cutoff_y} ({reason})"
    assert 0.30 <= cutoff_y <= 0.52

    # 2. Verify `analyze_multi_piece_pdf` in vision mode automatically detects the mid-page split on Page 2
    #    producing Piece 1 = pages 1-2 (ending at cutoff_y) and Piece 2 = pages 2-3 (starting at cutoff_y)
    rep = analyze_multi_piece_pdf(shared_pdf, mode="vision", use_winrt_ocr=False)
    assert len(rep.segments) == 2
    seg1, seg2 = rep.segments[0], rep.segments[1]
    assert seg1.start_page == 1 and seg1.end_page == 2
    assert seg2.start_page == 2 and seg2.end_page == 3
    assert seg1.has_midpage_end is True
    assert seg2.has_midpage_start is True
    assert seg1.end_y_ratio == seg2.start_y_ratio == cutoff_y

    # 3. Also verify manual overlapping segments (e.g. user specifies 1-2 and 2-3 without ratios) auto-resolve the cutoff
    manual_segs = [
        PdfPieceSegment(index=1, title="Prelude", start_page=1, end_page=2),
        PdfPieceSegment(index=2, title="Fugue", start_page=2, end_page=3),
    ]
    resolve_overlapping_page_cutoffs(shared_pdf, manual_segs)
    assert manual_segs[0].end_y_ratio == manual_segs[1].start_y_ratio == cutoff_y

    # 4. Execute split and verify both output PDFs have 2 pages, and Page 2 is physically cropped at the cutoff point!
    out_dir = tmp_path / "split_overlapping"
    created = execute_pdf_split(shared_pdf, manual_segs, output_dir=out_dir)
    assert len(created) == 2

    r1 = pypdf.PdfReader(str(created[0]))
    r2 = pypdf.PdfReader(str(created[1]))
    assert len(r1.pages) == 2
    assert len(r2.pages) == 2

    full_h = float(r1.pages[0].mediabox.height)
    p1_last_h = float(r1.pages[1].mediabox.height)
    p2_first_h = float(r2.pages[0].mediabox.height)

    # Piece 1's page 2 height should be ~cutoff_y * full_h, and Piece 2's page 1 height should be ~(1 - cutoff_y) * full_h
    assert abs(p1_last_h - (full_h * cutoff_y)) < 5.0
    assert abs(p2_first_h - (full_h * (1.0 - cutoff_y))) < 5.0

    # 5. Verify GUI preview renderer renders the cutoff line and active region overlay cleanly
    preview_img, _, _ = render_pdf_page_image(
        shared_pdf,
        page_index=1,
        fit_width=360,
        cutoff_y_ratio=cutoff_y,
        active_region=(0.0, cutoff_y),
    )
    assert preview_img.width == 360


def test_deep_search_and_download_vsts_auto_vs_manual_links(tmp_path: Path) -> None:
    from lento_convertpdf.vst_catalog import deep_search_and_download_vsts

    # Pre-place a simulated local portable binary for Dexed so Dexed is 100% satisfied without manual intervention,
    # while orchestra/SFZ libraries (like Sfizz + Salamander Piano / Sonatina Strings) report manual intervention links.
    (tmp_path / "Dexed.vst3").write_bytes(b"FAKE_VST3_BINARY")

    report = deep_search_and_download_vsts(
        categories=["piano", "strings"],
        target_dir=tmp_path,
        download_portable_assets=False,
        search_github_live=False,
    )

    assert report.total_evaluated == 4  # 2 piano + 2 strings
    assert len(report.auto_downloaded) == 4

    # Every evaluated VST should have auto-downloaded its .vstprofile.json and .sfz patch
    for item in report.auto_downloaded:
        assert any(p.suffix == ".json" and p.is_file() for p in item.auto_downloaded_files)
        assert any(p.suffix == ".sfz" and p.is_file() for p in item.auto_downloaded_files)
        assert "Official Repository" in item.associated_links
        assert "Latest Releases Page" in item.associated_links
        assert "Sample Library / Instrument Bank" in item.associated_links

    # Dexed had its .vst3 binary present and doesn't require an external sample bank -> manual_intervention_needed is False
    dexed_item = next(it for it in report.auto_downloaded if it.vst_id == "dexed_epiano")
    assert dexed_item.manual_intervention_needed is False
    assert dexed_item.status == "auto_downloaded"

    # Sfizz Salamander Grand Piano & Sonatina Strings require external multi-GB SFZ banks -> listed in manual_intervention
    manual_ids = {it.vst_id for it in report.manual_intervention}
    assert "sfizz_salamander_piano" in manual_ids
    assert "sfizz_sso_strings" in manual_ids

    # Verify Markdown and JSON report files were generated with clickable links
    assert report.markdown_report_path is not None and report.markdown_report_path.is_file()
    assert report.json_report_path is not None and report.json_report_path.is_file()
    md_text = report.markdown_report_path.read_text(encoding="utf-8")
    assert "Automatically Downloaded & Ready in Workspace" in md_text
    assert "Recommended Open-Source VSTs & Sample Libraries Requiring Manual Intervention" in md_text
    assert "https://github.com/sfztools/sfizz-ui" in md_text
    assert "https://github.com/peastman/sso" in md_text
