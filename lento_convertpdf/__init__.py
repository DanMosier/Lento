"""Lento_ConvertPDF: batch PDF to MusicXML OMR converter, Side-by-Side PDF Reader, Multi-Piece PDF Splitter, and Open-Source VST MusicXML Player."""

from .audio_player import MusicXMLAudioPlayer, synthesize_score_to_wav
from .audiveris_runner import check_audiveris
from .legato_runner import check_legato
from .homr_runner import EngineAvailability, OMRConfig, check_homr
from .models import (
    VALID_ENGINES,
    InstrumentPart,
    NoteEvent,
    ParsedScore,
    PdfConversionItem,
    VSTPluginSpec,
)
from .musicxml_parser import parse_musicxml, pitch_to_midi_and_name
from .omr_engines import (
    batch_convert_pdfs,
    check_engine,
    convert_single_pdf,
    scan_folder_for_pdfs,
)
from .pdf_splitter import (
    PdfPieceSegment,
    SplitAnalysisReport,
    analyze_multi_piece_pdf,
    execute_pdf_split,
    find_midpage_cutoff_y_ratio,
    resolve_overlapping_page_cutoffs,
)
from .quality import QualityReport, assess, check_score
from .repair import RepairReport, repair_spanners
from .vst_catalog import (
    OPEN_SOURCE_VST_CATALOG,
    VST_BY_ID,
    VSTDeepSearchItem,
    VSTDeepSearchReport,
    assign_recommended_vsts_to_parts,
    classify_instrument_category,
    deep_search_and_download_vsts,
    recommend_vst_for_instrument,
    source_all_recommended_vsts,
    source_open_source_vst_bundle,
    write_vst_deep_search_report,
)

__version__ = "1.0.0"

__all__ = [
    "EngineAvailability",
    "InstrumentPart",
    "MusicXMLAudioPlayer",
    "NoteEvent",
    "OMRConfig",
    "OPEN_SOURCE_VST_CATALOG",
    "ParsedScore",
    "PdfConversionItem",
    "PdfPieceSegment",
    "QualityReport",
    "SplitAnalysisReport",
    "VALID_ENGINES",
    "VSTDeepSearchItem",
    "VSTDeepSearchReport",
    "VSTPluginSpec",
    "VST_BY_ID",
    "analyze_multi_piece_pdf",
    "assess",
    "check_score",
    "repair_spanners",
    "RepairReport",
    "assign_recommended_vsts_to_parts",
    "batch_convert_pdfs",
    "check_homr",
    "check_audiveris",
    "check_legato",
    "check_engine",
    "classify_instrument_category",
    "convert_single_pdf",
    "deep_search_and_download_vsts",
    "execute_pdf_split",
    "find_midpage_cutoff_y_ratio",
    "parse_musicxml",
    "pitch_to_midi_and_name",
    "recommend_vst_for_instrument",
    "resolve_overlapping_page_cutoffs",
    "scan_folder_for_pdfs",
    "source_all_recommended_vsts",
    "source_open_source_vst_bundle",
    "synthesize_score_to_wav",
    "write_vst_deep_search_report",
]
