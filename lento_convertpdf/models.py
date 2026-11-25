"""Data models for PDF batch import, OMR conversion, MusicXML representation, and open-source VST assignments."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .quality import QualityReport

VALID_ENGINES = ("homr",)


@dataclass
class PdfConversionItem:
    """Represents a single PDF file imported from a folder for batch conversion."""

    pdf_path: Path
    relative_path: str
    selected: bool = True
    page_count: int = 0
    file_size_bytes: int = 0
    status: str = "pending"  # "pending" | "converting" | "converted" | "failed" | "skipped"
    engine_used: str = ""
    output_musicxml_path: Path | None = None
    duration_sec: float = 0.0
    error_message: str = ""
    detected_instruments: list[str] = field(default_factory=list)
    quality: QualityReport | None = None

    @property
    def file_size_kb(self) -> float:
        return round(self.file_size_bytes / 1024.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf_path": str(self.pdf_path),
            "relative_path": self.relative_path,
            "selected": self.selected,
            "page_count": self.page_count,
            "file_size_bytes": self.file_size_bytes,
            "status": self.status,
            "engine_used": self.engine_used,
            "output_musicxml_path": str(self.output_musicxml_path) if self.output_musicxml_path else None,
            "duration_sec": round(self.duration_sec, 2),
            "error_message": self.error_message,
            "detected_instruments": list(self.detected_instruments),
            "quality": self.quality.to_dict() if self.quality else None,
        }


@dataclass
class VSTPluginSpec:
    """Metadata and synthesis profile for a recommended open-source VST/VST3 plugin."""

    id: str
    name: str
    instrument_category: str  # e.g. "piano", "strings", "woodwinds", "brass", "guitar", "organ", "choir", "percussion", "synth"
    instruments_matched: list[str]
    developer: str
    license: str
    plugin_format: str  # "VST3 / SFZ" | "VST3 / VST2"
    description: str
    repo_url: str
    download_url: str
    default_binary_names: list[str]
    synthesis_profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class NoteEvent:
    """A single musical note or rest parsed from a MusicXML part."""

    pitch_midi: int  # 0-127 (60 = C4); -1 for rest
    pitch_name: str  # e.g. "C4", "F#5", or "Rest"
    start_beat: float
    duration_beats: float
    start_sec: float
    duration_sec: float
    velocity: int = 85
    measure_number: int = 1
    is_rest: bool = False
    staff: int = 1
    voice: str = "1"
    is_chord: bool = False


@dataclass
class InstrumentPart:
    """A musical part/staff from a MusicXML score along with its open-source VST assignment."""

    part_id: str
    part_name: str
    instrument_category: str
    midi_program: int = 0
    assigned_vst_id: str = ""
    assigned_vst_name: str = ""
    local_vst_path: Path | None = None
    volume: float = 0.85  # 0.0 to 1.0
    muted: bool = False
    solo: bool = False
    notes: list[NoteEvent] = field(default_factory=list)

    @property
    def playable_notes(self) -> list[NoteEvent]:
        return [n for n in self.notes if not n.is_rest and n.pitch_midi >= 0]


@dataclass
class ParsedScore:
    """A parsed MusicXML document ready for visual display and VST/synthesized playback."""

    musicxml_path: Path
    title: str = "Untitled Score"
    composer: str = "Unknown Composer"
    tempo_bpm: float = 112.0
    time_signature: tuple[int, int] = (4, 4)
    key_fifths: int = 0
    total_measures: int = 0
    total_duration_sec: float = 0.0
    total_beats: float = 0.0
    parts: list[InstrumentPart] = field(default_factory=list)

    @property
    def instrument_names(self) -> list[str]:
        return [p.part_name for p in self.parts]
