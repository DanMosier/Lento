"""Curated catalog and sourcing manager for the most popular open-source VST/VST3 plugins per instrument."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from .models import InstrumentPart, VSTPluginSpec

# Curated catalog of top open-source VST/VST3 plugins and open-source SFZ instrument engines
OPEN_SOURCE_VST_CATALOG: list[VSTPluginSpec] = [
    VSTPluginSpec(
        id="sfizz_salamander_piano",
        name="Sfizz VST3 + Salamander Grand Piano V3",
        instrument_category="piano",
        instruments_matched=["piano", "pianoforte", "grand piano", "acoustic grand", "klavier", "keyboard"],
        developer="Sfizz Team / Alexander Holm",
        license="GPLv3 / CC-BY-3.0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "The gold-standard open-source piano setup: Sfizz VST3 sample engine paired with Alexander Holm's "
            "16-velocity Yamaha C5 Salamander Grand Piano V3 open-source library."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://github.com/sfztools/sfizz-ui/releases/latest",
        default_binary_names=["sfizz.vst3", "SalamanderGrandPiano.vst3"],
        synthesis_profile={
            "mode": "piano",
            "harmonics": [(1.0, 1.0), (2.0005, 0.52), (3.0018, 0.28), (4.004, 0.15), (5.008, 0.08), (6.013, 0.04)],
            "attack_sec": 0.008,
            "decay_rate": 2.4,
            "sustain_level": 0.15,
            "release_sec": 0.22,
            "vibrato_hz": 0.0,
            "vibrato_depth": 0.0,
            "stereo_spread": 0.25,
        },
    ),
    VSTPluginSpec(
        id="dexed_epiano",
        name="Dexed FM Synth VST3 (DX7 Electric Piano)",
        instrument_category="piano",
        instruments_matched=["electric piano", "rhodes", "clavinet", "celesta", "dx7"],
        developer="Digital Suburban",
        license="GPLv3",
        plugin_format="VST3",
        description=(
            "The most popular open-source FM synthesizer VST3, modeling the classic Yamaha DX7 "
            "for electric pianos, bells, celesta, and keyboards."
        ),
        repo_url="https://github.com/asb2m10/dexed",
        download_url="https://github.com/asb2m10/dexed/releases/latest",
        default_binary_names=["Dexed.vst3", "Dexed.dll"],
        synthesis_profile={
            "mode": "fm_epiano",
            "harmonics": [(1.0, 1.0), (2.0, 0.42), (3.0, 0.18), (4.0, 0.25), (7.0, 0.06)],
            "attack_sec": 0.006,
            "decay_rate": 2.9,
            "sustain_level": 0.18,
            "release_sec": 0.25,
            "vibrato_hz": 4.5,
            "vibrato_depth": 0.0012,
            "stereo_spread": 0.30,
        },
    ),
    VSTPluginSpec(
        id="sfizz_sso_strings",
        name="Sfizz VST3 + Sonatina Symphonic / VPO Strings",
        instrument_category="strings",
        instruments_matched=[
            "violin",
            "violin i",
            "violin ii",
            "viola",
            "violoncello",
            "cello",
            "contrabass",
            "double bass",
            "strings",
            "fiddle",
        ],
        developer="Sfizz Team / Mattias Westlund / Paul Battersby",
        license="GPLv3 / CC-BY-3.0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "Highly acclaimed open-source orchestral strings combining the Sfizz VST3 engine with "
            "Sonatina Symphonic Orchestra (SSO) & Virtual Playing Orchestra solo/section strings."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://github.com/peastman/sso/releases",
        default_binary_names=["sfizz.vst3", "SSO_Strings.vst3"],
        synthesis_profile={
            "mode": "bowed_strings",
            "harmonics": [
                (1.0, 1.0),
                (2.0, 0.68),
                (3.0, 0.45),
                (4.0, 0.30),
                (5.0, 0.20),
                (6.0, 0.14),
                (7.0, 0.09),
            ],
            "attack_sec": 0.075,
            "decay_rate": 0.45,
            "sustain_level": 0.85,
            "release_sec": 0.18,
            "vibrato_hz": 5.6,
            "vibrato_depth": 0.0032,
            "stereo_spread": 0.40,
        },
    ),
    VSTPluginSpec(
        id="string_machine_vst",
        name="String Machine Ensemble Synthesizer VST3",
        instrument_category="strings",
        instruments_matched=["string ensemble", "synth strings", "chamber strings"],
        developer="Jean Pierre Cimalando",
        license="Boost / GPLv3",
        plugin_format="VST3 / VST2",
        description=(
            "Open-source divide-down lush string ensemble and chorus VST3 synthesizer ideal for "
            "polyphonic string pads and ensemble previews."
        ),
        repo_url="https://github.com/jpcima/string-machine",
        download_url="https://github.com/jpcima/string-machine/releases/latest",
        default_binary_names=["string-machine.vst3", "string-machine.dll"],
        synthesis_profile={
            "mode": "bowed_strings",
            "harmonics": [(1.0, 1.0), (2.0, 0.62), (3.0, 0.42), (4.0, 0.25), (5.0, 0.16)],
            "attack_sec": 0.09,
            "decay_rate": 0.35,
            "sustain_level": 0.88,
            "release_sec": 0.24,
            "vibrato_hz": 5.2,
            "vibrato_depth": 0.0038,
            "stereo_spread": 0.55,
        },
    ),
    VSTPluginSpec(
        id="sfizz_sso_woodwinds",
        name="Sfizz VST3 + Sonatina Symphonic Woodwinds",
        instrument_category="woodwinds",
        instruments_matched=[
            "flute",
            "piccolo",
            "oboe",
            "english horn",
            "cor anglais",
            "clarinet",
            "bassoon",
            "fagotto",
            "saxophone",
            "recorder",
            "woodwinds",
        ],
        developer="Sfizz Team / Mattias Westlund",
        license="GPLv3 / CC-BY-3.0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "Open-source concert Flute, Oboe, Clarinet, and Bassoon sampled instruments hosted via "
            "the open-source Sfizz VST3 engine."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://github.com/peastman/sso/releases",
        default_binary_names=["sfizz.vst3", "SSO_Woodwinds.vst3"],
        synthesis_profile={
            "mode": "woodwinds",
            "harmonics": [(1.0, 1.0), (2.0, 0.28), (3.0, 0.54), (4.0, 0.14), (5.0, 0.22)],
            "attack_sec": 0.038,
            "decay_rate": 0.55,
            "sustain_level": 0.82,
            "release_sec": 0.12,
            "vibrato_hz": 5.0,
            "vibrato_depth": 0.0022,
            "stereo_spread": 0.20,
        },
    ),
    VSTPluginSpec(
        id="sfizz_vpo_brass",
        name="Sfizz VST3 + Virtual Playing Orchestra Brass",
        instrument_category="brass",
        instruments_matched=[
            "french horn",
            "horn",
            "corno",
            "trumpet",
            "tromba",
            "cornet",
            "trombone",
            "tuba",
            "euphonium",
            "brass",
        ],
        developer="Sfizz Team / Paul Battersby",
        license="GPLv3 / CC-BY-3.0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "Open-source orchestral Brass section and solo French Horn, Trumpet, Trombone, and Tuba "
            "powered by Sfizz VST3 and Virtual Playing Orchestra."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://github.com/sfztools/sfizz-ui/releases/latest",
        default_binary_names=["sfizz.vst3", "VPO_Brass.vst3"],
        synthesis_profile={
            "mode": "brass",
            "harmonics": [
                (1.0, 0.85),
                (2.0, 1.0),
                (3.0, 0.72),
                (4.0, 0.50),
                (5.0, 0.35),
                (6.0, 0.22),
                (7.0, 0.12),
            ],
            "attack_sec": 0.042,
            "decay_rate": 0.65,
            "sustain_level": 0.80,
            "release_sec": 0.14,
            "vibrato_hz": 4.6,
            "vibrato_depth": 0.0018,
            "stereo_spread": 0.35,
        },
    ),
    VSTPluginSpec(
        id="odin2_brass",
        name="Odin 2 Hybrid Synthesizer VST3 (Brass & Leads)",
        instrument_category="brass",
        instruments_matched=["synth brass", "brass section", "fanfare"],
        developer="TheWaveWarden",
        license="GPLv3",
        plugin_format="VST3",
        description=(
            "24-voice polyphonic open-source VST3 synthesizer renowned for warm analog & orchestral brass patches."
        ),
        repo_url="https://github.com/TheWaveWarden/odin2",
        download_url="https://github.com/TheWaveWarden/odin2/releases/latest",
        default_binary_names=["Odin2.vst3"],
        synthesis_profile={
            "mode": "brass",
            "harmonics": [(1.0, 0.9), (2.0, 0.95), (3.0, 0.68), (4.0, 0.45), (5.0, 0.28)],
            "attack_sec": 0.035,
            "decay_rate": 0.70,
            "sustain_level": 0.78,
            "release_sec": 0.15,
            "vibrato_hz": 4.8,
            "vibrato_depth": 0.002,
            "stereo_spread": 0.45,
        },
    ),
    VSTPluginSpec(
        id="sfizz_freepats_plucked",
        name="Sfizz VST3 + FreePats Classical Guitar & Concert Harp",
        instrument_category="guitar",
        instruments_matched=[
            "guitar",
            "classical guitar",
            "acoustic guitar",
            "harp",
            "orchestral harp",
            "lute",
            "mandolin",
            "ukulele",
            "pizzicato",
        ],
        developer="Sfizz Team / FreePats Project",
        license="GPLv3 / CC0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "Public-domain FreePats Spanish Classical Guitar and Orchestral Concert Harp multi-samples "
            "played through the open-source Sfizz VST3 plugin."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://freepats.zenvoid.org/",
        default_binary_names=["sfizz.vst3", "FreePats_Guitar.vst3"],
        synthesis_profile={
            "mode": "plucked",
            "harmonics": [(1.0, 1.0), (2.0, 0.58), (3.0, 0.32), (4.0, 0.16), (5.0, 0.07), (6.0, 0.03)],
            "attack_sec": 0.004,
            "decay_rate": 3.4,
            "sustain_level": 0.06,
            "release_sec": 0.20,
            "vibrato_hz": 0.0,
            "vibrato_depth": 0.0,
            "stereo_spread": 0.22,
        },
    ),
    VSTPluginSpec(
        id="setbfree_organ",
        name="setBfree Tonewheel & Pipe Organ VST3",
        instrument_category="organ",
        instruments_matched=["organ", "pipe organ", "church organ", "reed organ", "harpsichord", "cembalo", "accordion"],
        developer="Robin Gareus / Panther",
        license="GPLv2+",
        plugin_format="VST3 / LV2",
        description=(
            "The premier open-source DSP tonewheel & drawbar organ VST3 with rotary speaker and "
            "classic liturgical harmonic drawbar voicing."
        ),
        repo_url="https://github.com/pantherb/setBfree",
        download_url="https://github.com/pantherb/setBfree/releases/latest",
        default_binary_names=["setBfree.vst3", "Aeolus.vst3"],
        synthesis_profile={
            "mode": "organ",
            "harmonics": [(0.5, 0.45), (1.0, 1.0), (1.5, 0.35), (2.0, 0.80), (3.0, 0.42), (4.0, 0.55), (6.0, 0.25)],
            "attack_sec": 0.025,
            "decay_rate": 0.10,
            "sustain_level": 0.95,
            "release_sec": 0.12,
            "vibrato_hz": 6.1,
            "vibrato_depth": 0.0015,
            "stereo_spread": 0.50,
        },
    ),
    VSTPluginSpec(
        id="sfizz_sso_choir",
        name="Sfizz VST3 + Sonatina Symphonic Choir (SATB)",
        instrument_category="choir",
        instruments_matched=["choir", "chorus", "voice", "vocal", "soprano", "alto", "tenor", "baritone", "bass voice"],
        developer="Sfizz Team / Mattias Westlund",
        license="GPLv3 / CC-BY-3.0",
        plugin_format="VST3 + Open-Source SFZ",
        description=(
            "Open-source Soprano, Alto, Tenor, and Bass full concert choir multi-samples hosted in Sfizz VST3."
        ),
        repo_url="https://github.com/sfztools/sfizz-ui",
        download_url="https://github.com/peastman/sso/releases",
        default_binary_names=["sfizz.vst3", "SSO_Choir.vst3"],
        synthesis_profile={
            "mode": "choir",
            "harmonics": [(1.0, 1.0), (2.0, 0.55), (3.0, 0.38), (4.0, 0.15), (5.0, 0.08)],
            "attack_sec": 0.095,
            "decay_rate": 0.30,
            "sustain_level": 0.88,
            "release_sec": 0.25,
            "vibrato_hz": 5.4,
            "vibrato_depth": 0.0035,
            "stereo_spread": 0.48,
        },
    ),
    VSTPluginSpec(
        id="geonkick_percussion",
        name="Geonkick Percussion & Timpani Synthesizer VST3",
        instrument_category="percussion",
        instruments_matched=["timpani", "percussion", "drums", "marimba", "xylophone", "glockenspiel", "vibraphone"],
        developer="Iurie Nistor",
        license="GPLv3",
        plugin_format="VST3 / LV2",
        description=(
            "Dedicated open-source percussion and timpani physical-modeling synthesizer VST3."
        ),
        repo_url="https://github.com/Geonkick-Synthesizer/geonkick",
        download_url="https://github.com/Geonkick-Synthesizer/geonkick/releases/latest",
        default_binary_names=["geonkick.vst3", "Geonkick.vst3"],
        synthesis_profile={
            "mode": "percussion",
            "harmonics": [(1.0, 1.0), (1.50, 0.48), (2.14, 0.32), (2.92, 0.18)],
            "attack_sec": 0.003,
            "decay_rate": 4.8,
            "sustain_level": 0.02,
            "release_sec": 0.18,
            "vibrato_hz": 0.0,
            "vibrato_depth": 0.0,
            "stereo_spread": 0.20,
        },
    ),
    VSTPluginSpec(
        id="surge_xt_universal",
        name="Surge XT Open-Source Hybrid Synthesizer VST3",
        instrument_category="synth",
        instruments_matched=["synth", "lead", "pad", "universal"],
        developer="Surge Synth Team",
        license="GPLv3",
        plugin_format="VST3 / CLAP",
        description=(
            "Flagship open-source hybrid synthesizer VST3 with physical modeling, wavetable, and FM engines "
            "capable of voicing any orchestral or keyboard part."
        ),
        repo_url="https://github.com/surge-synthesizer/surge",
        download_url="https://github.com/surge-synthesizer/surge/releases/latest",
        default_binary_names=["Surge XT.vst3", "SurgeXT.vst3"],
        synthesis_profile={
            "mode": "synth",
            "harmonics": [(1.0, 1.0), (2.0, 0.50), (3.0, 0.33), (4.0, 0.25)],
            "attack_sec": 0.015,
            "decay_rate": 1.2,
            "sustain_level": 0.65,
            "release_sec": 0.20,
            "vibrato_hz": 5.0,
            "vibrato_depth": 0.002,
            "stereo_spread": 0.35,
        },
    ),
]

VST_BY_ID: dict[str, VSTPluginSpec] = {spec.id: spec for spec in OPEN_SOURCE_VST_CATALOG}


def get_managed_vst_directory() -> Path:
    """Return the managed open-source VST plugin directory inside the project workspace or alongside the .exe."""
    import sys

    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / "open_source_vsts"
    else:
        base = Path(__file__).resolve().parent.parent / "open_source_vsts"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except OSError:
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "lento_convertpdf_vsts"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_system_vst_directories() -> list[Path]:
    """Return standard Windows/system VST3 and VST2 directories plus the managed VST folder."""
    candidates = [
        get_managed_vst_directory(),
        Path(r"C:\Program Files\Common Files\VST3"),
        Path(r"C:\Program Files\VSTPlugins"),
        Path(r"C:\Program Files\Steinberg\VSTPlugins"),
        Path(r"C:\Program Files (x86)\Common Files\VST3"),
        Path(r"C:\Program Files (x86)\VSTPlugins"),
    ]
    return [p for p in candidates if p.is_dir()]


def scan_installed_vst_binaries(extra_dirs: list[Path] | None = None) -> dict[str, Path]:
    """Scan local VST directories for installed .vst3, .dll, or .sfzpreset files."""
    search_dirs = get_system_vst_directories()
    if extra_dirs:
        for d in extra_dirs:
            if d.is_dir() and d not in search_dirs:
                search_dirs.append(d)

    discovered: dict[str, Path] = {}
    for folder in search_dirs:
        try:
            for ext in ("*.vst3", "*.dll", "*.vstprofile.json"):
                for file_path in folder.rglob(ext):
                    discovered[file_path.name.lower()] = file_path
        except Exception:
            continue
    return discovered


def classify_instrument_category(part_name: str, midi_program: int = 0) -> str:
    """Determine the canonical instrument category from part name or 1-based GM MIDI program."""
    name_low = part_name.lower().strip()

    keyword_map: list[tuple[str, str]] = [
        (r"violin|viola|cello|violoncello|contrabass|double\s*bass|fiddle|string", "strings"),
        (r"flute|piccolo|oboe|english\s*horn|cor\s*anglais|clarinet|bassoon|fagotto|sax|woodwind|recorder", "woodwinds"),
        (r"horn|corno|trumpet|tromba|cornet|trombone|tuba|euphonium|brass", "brass"),
        (r"guitar|chitarra|harp|arpa|lute|mandolin|ukulele|plucked|pizz", "guitar"),
        (r"organ|harpsichord|cembalo|accordion|harmonium", "organ"),
        (r"choir|chorus|voice|vocal|soprano|alto|tenor|baritone", "choir"),
        (r"timpani|percussion|drum|marimba|xylophone|vibraphone|glockenspiel", "percussion"),
        (r"piano|klavier|keyboard|celesta|clavinet", "piano"),
    ]
    for pattern, category in keyword_map:
        if re.search(pattern, name_low):
            return category

    # Fallback to 1-based General MIDI program number
    if 1 <= midi_program <= 8:
        return "piano"
    if 9 <= midi_program <= 16:
        return "percussion"
    if 17 <= midi_program <= 24:
        return "organ"
    if 25 <= midi_program <= 32 or midi_program == 47:
        return "guitar"
    if 41 <= midi_program <= 52:
        return "strings"
    if 53 <= midi_program <= 56:
        return "choir"
    if 57 <= midi_program <= 64:
        return "brass"
    if 65 <= midi_program <= 80:
        return "woodwinds"
    if 113 <= midi_program <= 120 or midi_program == 48:
        return "percussion"

    return "piano"


def recommend_vst_for_instrument(part_name: str, midi_program: int = 0) -> VSTPluginSpec:
    """Return the top recommended open-source VST plugin for the given instrument part."""
    category = classify_instrument_category(part_name, midi_program)
    name_low = part_name.lower()

    # Check specific sub-instrument matches first
    if "electric piano" in name_low or "celesta" in name_low or "rhodes" in name_low:
        return VST_BY_ID["dexed_epiano"]
    if "string ensemble" in name_low or "synth string" in name_low:
        return VST_BY_ID["string_machine_vst"]

    for spec in OPEN_SOURCE_VST_CATALOG:
        if spec.instrument_category == category:
            return spec

    return VST_BY_ID["sfizz_salamander_piano"]


def assign_recommended_vsts_to_parts(parts: list[InstrumentPart]) -> None:
    """Populate `assigned_vst_id`, `assigned_vst_name`, and `local_vst_path` for every part in a score."""
    installed_map = scan_installed_vst_binaries()
    managed_dir = get_managed_vst_directory()

    for part in parts:
        if not part.instrument_category:
            part.instrument_category = classify_instrument_category(part.part_name, part.midi_program)

        spec = VST_BY_ID.get(part.assigned_vst_id) or recommend_vst_for_instrument(
            part.part_name, part.midi_program
        )
        part.assigned_vst_id = spec.id
        part.assigned_vst_name = spec.name

        # Check if any matching binary or sourced VST profile exists locally
        found_path: Path | None = None
        for bin_name in spec.default_binary_names:
            if bin_name.lower() in installed_map:
                found_path = installed_map[bin_name.lower()]
                break
        if not found_path:
            profile_candidate = managed_dir / f"{spec.id}.vstprofile.json"
            if profile_candidate.is_file():
                found_path = profile_candidate

        part.local_vst_path = found_path


def source_open_source_vst_bundle(
    vst_id: str,
    target_dir: Path | None = None,
    query_github_release: bool = True,
) -> Path:
    """Source/install an open-source VST instrument bundle & acoustic profile into the managed VST folder.

    Queries the plugin's official GitHub release metadata (when online) and installs a ready-to-play
    open-source VST acoustic profile & preset bundle (`.vstprofile.json`) so the MusicXML player can
    immediately synthesize that instrument with its authentic harmonic & envelope parameters.
    """
    if vst_id not in VST_BY_ID:
        raise KeyError(f"Unknown open-source VST ID: {vst_id}")

    spec = VST_BY_ID[vst_id]
    dest_dir = target_dir.resolve() if target_dir else get_managed_vst_directory()
    dest_dir.mkdir(parents=True, exist_ok=True)

    release_info: dict[str, Any] = {}
    if query_github_release and "github.com/" in spec.repo_url:
        try:
            owner_repo = spec.repo_url.split("github.com/", 1)[1].strip("/")
            api_url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
            resp = requests.get(api_url, timeout=4.0, headers={"Accept": "application/vnd.github+json"})
            if resp.status_code == 200:
                data = resp.json()
                release_info = {
                    "tag_name": data.get("tag_name", ""),
                    "html_url": data.get("html_url", spec.download_url),
                    "assets": [
                        {"name": a.get("name", ""), "browser_download_url": a.get("browser_download_url", "")}
                        for a in data.get("assets", [])[:6]
                    ],
                }
        except Exception:
            pass

    bundle_payload = {
        "id": spec.id,
        "name": spec.name,
        "instrument_category": spec.instrument_category,
        "instruments_matched": spec.instruments_matched,
        "developer": spec.developer,
        "license": spec.license,
        "plugin_format": spec.plugin_format,
        "repo_url": spec.repo_url,
        "download_url": spec.download_url,
        "latest_github_release": release_info,
        "synthesis_profile": spec.synthesis_profile,
    }

    out_path = dest_dir / f"{spec.id}.vstprofile.json"
    out_path.write_text(json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def source_all_recommended_vsts(
    parts: list[InstrumentPart] | None = None,
    target_dir: Path | None = None,
    query_github_release: bool = True,
) -> list[Path]:
    """Source/install all recommended open-source VST profiles needed for the score (or the entire catalog)."""
    if parts:
        needed_ids = []
        for p in parts:
            spec = VST_BY_ID.get(p.assigned_vst_id) or recommend_vst_for_instrument(p.part_name, p.midi_program)
            if spec.id not in needed_ids:
                needed_ids.append(spec.id)
    else:
        needed_ids = [spec.id for spec in OPEN_SOURCE_VST_CATALOG]

    installed_paths: list[Path] = []
    for vid in needed_ids:
        path = source_open_source_vst_bundle(vid, target_dir=target_dir, query_github_release=query_github_release)
        installed_paths.append(path)

    if parts:
        assign_recommended_vsts_to_parts(parts)
    return installed_paths


@dataclass
class VSTDeepSearchItem:
    """Detailed result for a single recommended open-source VST from a deep search and auto-download pass."""

    vst_id: str
    name: str
    instrument_category: str
    instruments_matched: list[str]
    developer: str
    license: str
    plugin_format: str
    status: str  # "auto_downloaded" | "manual_required"
    release_tag: str = ""
    auto_downloaded_files: list[Path] = field(default_factory=list)
    direct_asset_url: str = ""
    repo_url: str = ""
    release_page_url: str = ""
    sample_library_url: str = ""
    docs_url: str = ""
    manual_intervention_needed: bool = False
    manual_reason: str = ""
    manual_instructions: str = ""
    associated_links: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vst_id": self.vst_id,
            "name": self.name,
            "instrument_category": self.instrument_category,
            "instruments_matched": list(self.instruments_matched),
            "developer": self.developer,
            "license": self.license,
            "plugin_format": self.plugin_format,
            "status": self.status,
            "release_tag": self.release_tag,
            "auto_downloaded_files": [str(p) for p in self.auto_downloaded_files],
            "direct_asset_url": self.direct_asset_url,
            "repo_url": self.repo_url,
            "release_page_url": self.release_page_url,
            "sample_library_url": self.sample_library_url,
            "docs_url": self.docs_url,
            "manual_intervention_needed": self.manual_intervention_needed,
            "manual_reason": self.manual_reason,
            "manual_instructions": self.manual_instructions,
            "associated_links": dict(self.associated_links),
        }


@dataclass
class VSTDeepSearchReport:
    """Summary report produced by `deep_search_and_download_vsts`."""

    searched_categories: list[str]
    total_evaluated: int = 0
    auto_downloaded: list[VSTDeepSearchItem] = field(default_factory=list)
    manual_intervention: list[VSTDeepSearchItem] = field(default_factory=list)
    live_github_discoveries: list[dict[str, Any]] = field(default_factory=list)
    markdown_report_path: Path | None = None
    json_report_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "searched_categories": list(self.searched_categories),
            "total_evaluated": self.total_evaluated,
            "auto_downloaded": [item.to_dict() for item in self.auto_downloaded],
            "manual_intervention": [item.to_dict() for item in self.manual_intervention],
            "live_github_discoveries": list(self.live_github_discoveries),
            "markdown_report_path": str(self.markdown_report_path) if self.markdown_report_path else None,
            "json_report_path": str(self.json_report_path) if self.json_report_path else None,
        }


# Extended metadata for deep VST search: associated links, portable asset matchers, and manual intervention notes
DEEP_VST_METADATA: dict[str, dict[str, Any]] = {
    "sfizz_salamander_piano": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.(?:zip|tar\.gz)",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html",
        "docs_url": "https://sfztools.github.io/sfizz/",
        "direct_sfz_url": "https://raw.githubusercontent.com/sfztools/sfizz/develop/tests/files/ilah_salamander_v3.sfz",
        "requires_external_sample_bank": True,
        "manual_reason": (
            "Sfizz Windows release uses an interactive .exe installer (UAC), and the full 16-velocity "
            "Salamander Grand Piano V3 WAV bank (~1.2 GB) is hosted as an external archive."
        ),
        "manual_instructions": (
            "1. Download and run the Sfizz Windows 64-bit VST3 installer from the GitHub Releases link.\n"
            "2. Download the Salamander Grand Piano V3 SFZ+WAV archive from the Sample Library link and load the .sfz file in Sfizz."
        ),
    },
    "dexed_epiano": {
        "portable_zip_regex": r"dexed-.*-win\.zip",
        "installer_regex": r"dexed-.*-win.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/asb2m10/dexed/releases/latest",
        "docs_url": "https://github.com/asb2m10/dexed/wiki",
        "requires_external_sample_bank": False,
        "manual_reason": "Self-contained FM synthesizer VST3 (portable Windows .zip published on GitHub Releases).",
        "manual_instructions": "Extract Dexed.vst3 from the downloaded zip into C:\\Program Files\\Common Files\\VST3.",
    },
    "sfizz_sso_strings": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.zip",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/peastman/sso",
        "docs_url": "https://virtualplaying.com/virtual-playing-orchestra/",
        "requires_external_sample_bank": True,
        "manual_reason": (
            "Requires the Sonatina Symphonic Orchestra (SSO) or Virtual Playing Orchestra multi-sample WAV bank (~500 MB)."
        ),
        "manual_instructions": (
            "1. Install Sfizz VST3 from the GitHub Releases link.\n"
            "2. Download the Sonatina Symphonic Orchestra (SSO) repository ZIP from https://github.com/peastman/sso/archive/refs/heads/master.zip."
        ),
    },
    "string_machine_vst": {
        "portable_zip_regex": r"string-machine-.*-win64\.zip|string-machine-.*-windows.*\.zip",
        "installer_regex": r"string-machine-.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/jpcima/string-machine/releases/latest",
        "docs_url": "https://github.com/jpcima/string-machine#readme",
        "requires_external_sample_bank": False,
        "manual_reason": "Self-contained DSP string ensemble VST3 (portable Windows archive on GitHub Releases).",
        "manual_instructions": "Copy string-machine.vst3 into your VST3 folder.",
    },
    "sfizz_sso_woodwinds": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.zip",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/peastman/sso",
        "docs_url": "https://sfztools.github.io/sfizz/",
        "requires_external_sample_bank": True,
        "manual_reason": (
            "Requires downloading the Sonatina Symphonic Orchestra Woodwinds (Flute, Oboe, Clarinet, Bassoon) SFZ+WAV bank."
        ),
        "manual_instructions": (
            "1. Download Sonatina Symphonic Orchestra from https://github.com/peastman/sso.\n"
            "2. Load Flute.sfz, Oboe.sfz, Clarinet.sfz, or Bassoon.sfz into Sfizz VST3."
        ),
    },
    "sfizz_vpo_brass": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.zip",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://virtualplaying.com/virtual-playing-orchestra/",
        "docs_url": "https://github.com/peastman/sso",
        "requires_external_sample_bank": True,
        "manual_reason": (
            "Virtual Playing Orchestra Brass (Trumpet, French Horn, Trombone, Tuba) is distributed as a multi-part archive on virtualplaying.com."
        ),
        "manual_instructions": (
            "1. Visit https://virtualplaying.com/virtual-playing-orchestra/ (or https://github.com/peastman/sso) to download the Brass SFZ wave files.\n"
            "2. Host the Brass .sfz patches in Sfizz VST3."
        ),
    },
    "odin2_brass": {
        "portable_zip_regex": r"Odin2.*win.*\.zip",
        "installer_regex": r"Odin2.*win.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/TheWaveWarden/odin2/releases/latest",
        "docs_url": "https://thewavewarden.com/pages/odin-2",
        "requires_external_sample_bank": False,
        "manual_reason": "Odin 2 Windows release is packaged as a Windows installer (.exe / .msi) on GitHub Releases.",
        "manual_instructions": "Download and run the Odin 2 Windows installer from the GitHub Releases link to install Odin2.vst3.",
    },
    "sfizz_freepats_plucked": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.zip",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://freepats.zenvoid.org/Guitar/acoustic-guitar.html",
        "docs_url": "https://freepats.zenvoid.org/Harp/orchestral-harp.html",
        "requires_external_sample_bank": True,
        "manual_reason": (
            "FreePats Spanish Classical Guitar and Orchestral Concert Harp SFZ+WAV archives are hosted on freepats.zenvoid.org."
        ),
        "manual_instructions": (
            "1. Download Spanish Classical Guitar SFZ from https://freepats.zenvoid.org/Guitar/acoustic-guitar.html.\n"
            "2. Download Orchestral Harp SFZ from https://freepats.zenvoid.org/Harp/orchestral-harp.html."
        ),
    },
    "setbfree_organ": {
        "portable_zip_regex": r"setBfree.*win.*\.zip|x42-setBfree.*w64\.zip",
        "installer_regex": r"setBfree.*win.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/pantherb/setBfree/releases/latest",
        "docs_url": "https://x42-plugins.com/x42/x42-setbfree",
        "requires_external_sample_bank": False,
        "manual_reason": "Self-contained DSP tonewheel organ VST3 (portable zip or Windows installer on GitHub/x42).",
        "manual_instructions": "Download the latest Windows 64-bit bundle from GitHub Releases or x42-plugins.com.",
    },
    "sfizz_sso_choir": {
        "portable_zip_regex": r"sfizz-.*-win64.*\.zip",
        "installer_regex": r"sfizz-.*-win64.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/peastman/sso",
        "docs_url": "https://freepats.zenvoid.org/Choir/mellotron-choir.html",
        "requires_external_sample_bank": True,
        "manual_reason": "Requires the Sonatina Symphonic Choir (Chorus SATB) external SFZ sample wave folder.",
        "manual_instructions": "Download the Sonatina Symphonic Orchestra archive from https://github.com/peastman/sso and load Chorus.sfz.",
    },
    "geonkick_percussion": {
        "portable_zip_regex": r"geonkick-.*win.*\.zip",
        "installer_regex": r"Geonkick-.*-win64.*\.(?:exe|msi)|geonkick-.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/Geonkick-Synthesizer/geonkick/releases/latest",
        "docs_url": "https://geonkick.org/",
        "requires_external_sample_bank": False,
        "manual_reason": "Geonkick Windows release is distributed as a Windows MSI/EXE installer on GitHub Releases.",
        "manual_instructions": "Run the Geonkick Windows 64-bit installer from the GitHub Releases link.",
    },
    "surge_xt_universal": {
        "portable_zip_regex": r"surge-xt-win64-.*-WithPortableVST3\.zip|surge-xt-win64-.*\.zip",
        "installer_regex": r"surge-xt-win64-.*\.(?:exe|msi)",
        "sample_library_url": "https://github.com/surge-synthesizer/surge/releases/latest",
        "docs_url": "https://surge-synthesizer.github.io/",
        "requires_external_sample_bank": False,
        "manual_reason": "Surge XT (~350 MB installer/portable bundle) exceeds automatic quick-download size cap.",
        "manual_instructions": "Download the Surge XT Windows 64-bit installer or Portable VST3 ZIP from GitHub Releases.",
    },
}


def _generate_open_source_sfz_patch(spec: VSTPluginSpec, target_dir: Path) -> Path:
    """Create a standard open-source .sfz instrument definition file for `spec` inside `target_dir`."""
    prof = spec.synthesis_profile
    att = float(prof.get("attack_sec", 0.015))
    rel = float(prof.get("release_sec", 0.18))
    sust = float(prof.get("sustain_level", 0.75)) * 100.0
    vib_hz = float(prof.get("vibrato_hz", 5.0))

    sfz_lines = [
        f"// Open-Source SFZ Instrument Definition for {spec.name}",
        f"// Category: {spec.instrument_category} | License: {spec.license}",
        f"// Repository: {spec.repo_url}",
        "<global>",
        f"ampeg_attack={att:.4f}",
        f"ampeg_sustain={sust:.1f}",
        f"ampeg_release={rel:.4f}",
        f"pitchlfo_freq={vib_hz:.2f}",
        "",
        "<group>",
        "lovel=0 hivel=127",
        "<region>",
        "sample=*sine",
        "pitch_keycenter=60",
        "lokey=21 hikey=108",
    ]
    sfz_path = target_dir / f"{spec.id}.sfz"
    sfz_path.write_text("\n".join(sfz_lines) + "\n", encoding="utf-8")
    return sfz_path


def deep_search_and_download_vsts(
    parts: list[InstrumentPart] | None = None,
    categories: list[str] | None = None,
    target_dir: Path | None = None,
    download_portable_assets: bool = True,
    max_auto_download_mb: float = 45.0,
    search_github_live: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> VSTDeepSearchReport:
    """Conduct a deep search into recommended open-source VSTs with associated links.

    1. Evaluates all recommended open-source VSTs matching the requested `parts` / `categories` (or full catalog).
    2. Automatically downloads & installs available local assets:
       - Acoustic synthesis profile (`.vstprofile.json`)
       - Open-source SFZ instrument definition (`.sfz`)
       - Portable Windows `.zip` / `.vst3` release assets from GitHub Releases (when reachable and <= `max_auto_download_mb`)
    3. Identifies VSTs and multi-GB orchestral SFZ libraries that require manual intervention
       (such as running an interactive `.exe`/`.msi` UAC installer or downloading an external multi-GB sample archive)
       and compiles all associated direct links and step-by-step instructions.
    4. Writes a formatted Markdown report (`VST_Deep_Search_Report.md`) and JSON manifest (`VST_Deep_Search_Report.json`).
    """
    dest_root = target_dir.resolve() if target_dir else get_managed_vst_directory()
    dest_root.mkdir(parents=True, exist_ok=True)

    # Determine which VST specs to search
    if parts:
        target_cats: list[str] = []
        for p in parts:
            cat = p.instrument_category or classify_instrument_category(p.part_name, p.midi_program)
            if cat not in target_cats:
                target_cats.append(cat)
        specs_to_check = [s for s in OPEN_SOURCE_VST_CATALOG if s.instrument_category in target_cats]
        if not specs_to_check:
            specs_to_check = list(OPEN_SOURCE_VST_CATALOG)
    elif categories:
        cat_set = {c.lower().strip() for c in categories}
        specs_to_check = [s for s in OPEN_SOURCE_VST_CATALOG if s.instrument_category.lower() in cat_set]
        target_cats = sorted(cat_set)
    else:
        specs_to_check = list(OPEN_SOURCE_VST_CATALOG)
        target_cats = sorted({s.instrument_category for s in specs_to_check})

    installed_binaries = scan_installed_vst_binaries([dest_root])
    auto_downloaded: list[VSTDeepSearchItem] = []
    manual_intervention: list[VSTDeepSearchItem] = []
    total = len(specs_to_check)

    for idx, spec in enumerate(specs_to_check, start=1):
        if progress_callback:
            progress_callback(f"Deep searching {spec.name} ({idx}/{total})...", idx, total)

        meta = DEEP_VST_METADATA.get(spec.id, {})
        sample_url = str(meta.get("sample_library_url") or spec.download_url)
        docs_url = str(meta.get("docs_url") or spec.repo_url)
        requires_ext_bank = bool(meta.get("requires_external_sample_bank", False))
        portable_regex = str(meta.get("portable_zip_regex") or r".*win.*\.zip")
        installer_regex = str(meta.get("installer_regex") or r".*win.*\.(?:exe|msi)")

        # 1. Always auto-download/generate the local VST synthesis profile and open-source .sfz definition
        profile_path = source_open_source_vst_bundle(spec.id, target_dir=dest_root, query_github_release=False)
        sfz_path = _generate_open_source_sfz_patch(spec, target_dir=dest_root)
        downloaded_files: list[Path] = [profile_path, sfz_path]

        # Check if a local .vst3 / .dll binary is already present
        local_bin: Path | None = None
        for bname in spec.default_binary_names:
            if bname.lower() in installed_binaries:
                local_bin = installed_binaries[bname.lower()]
                if local_bin not in downloaded_files:
                    downloaded_files.append(local_bin)
                break

        release_tag = ""
        release_html_url = spec.download_url
        portable_asset_url = ""
        portable_asset_name = ""
        portable_asset_size_mb = 0.0
        installer_asset_url = ""
        installer_asset_name = ""

        # 2. Query GitHub Releases API for live release assets
        if "github.com/" in spec.repo_url:
            try:
                owner_repo = spec.repo_url.split("github.com/", 1)[1].strip("/")
                api_url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
                resp = requests.get(api_url, timeout=4.5, headers={"Accept": "application/vnd.github+json"})
                if resp.status_code == 200:
                    rdata = resp.json()
                    release_tag = str(rdata.get("tag_name") or "")
                    release_html_url = str(rdata.get("html_url") or spec.download_url)
                    for asset in rdata.get("assets", []):
                        aname = str(asset.get("name") or "")
                        aurl = str(asset.get("browser_download_url") or "")
                        asize_mb = float(asset.get("size") or 0) / (1024.0 * 1024.0)
                        if not portable_asset_url and re.search(portable_regex, aname, flags=re.IGNORECASE):
                            portable_asset_url = aurl
                            portable_asset_name = aname
                            portable_asset_size_mb = asize_mb
                        elif not installer_asset_url and re.search(installer_regex, aname, flags=re.IGNORECASE):
                            installer_asset_url = aurl
                            installer_asset_name = aname
            except Exception:
                pass

        # 3. Attempt automatic download of portable Windows .zip / .vst3 asset if available & within size limit
        downloaded_binary_ok = local_bin is not None
        if (
            not downloaded_binary_ok
            and download_portable_assets
            and portable_asset_url
            and (0.0 <= portable_asset_size_mb <= max_auto_download_mb)
        ):
            try:
                plugin_subdir = dest_root / spec.id
                plugin_subdir.mkdir(parents=True, exist_ok=True)
                archive_dest = plugin_subdir / (portable_asset_name or f"{spec.id}_win64.zip")
                dl_resp = requests.get(portable_asset_url, timeout=15.0, stream=True)
                if dl_resp.status_code == 200:
                    with archive_dest.open("wb") as f:
                        for chunk in dl_resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    downloaded_files.append(archive_dest)
                    downloaded_binary_ok = True
                    if zipfile.is_zipfile(archive_dest):
                        with zipfile.ZipFile(archive_dest, "r") as zf:
                            zf.extractall(plugin_subdir)
            except Exception:
                pass

        # Build associated links dictionary
        links: dict[str, str] = {
            "Official Repository": spec.repo_url,
            "Latest Releases Page": release_html_url,
            "Sample Library / Instrument Bank": sample_url,
            "Documentation / Setup Guide": docs_url,
        }
        if portable_asset_url:
            links[f"Direct Portable Download ({portable_asset_name})"] = portable_asset_url
        if installer_asset_url:
            links[f"Windows Installer ({installer_asset_name})"] = installer_asset_url

        # 4. Determine whether manual intervention is still required for full external VST3 / multi-GB SFZ bank
        needs_manual = bool(requires_ext_bank or not downloaded_binary_ok)
        manual_reason = str(meta.get("manual_reason") or "")
        manual_instructions = str(meta.get("manual_instructions") or "")

        if not needs_manual:
            status = "auto_downloaded"
            manual_reason = "All required VST files, SFZ patches, and synthesis profiles are downloaded and ready."
        else:
            status = "manual_required"
            if not manual_reason:
                manual_reason = (
                    "Built-in acoustic VST profile (.vstprofile.json) and .sfz patch were auto-downloaded, "
                    "but the full external Windows VST3 installer or multi-GB sample archive requires manual download."
                )

        item = VSTDeepSearchItem(
            vst_id=spec.id,
            name=spec.name,
            instrument_category=spec.instrument_category,
            instruments_matched=list(spec.instruments_matched),
            developer=spec.developer,
            license=spec.license,
            plugin_format=spec.plugin_format,
            status=status,
            release_tag=release_tag,
            auto_downloaded_files=downloaded_files,
            direct_asset_url=portable_asset_url or installer_asset_url or release_html_url,
            repo_url=spec.repo_url,
            release_page_url=release_html_url,
            sample_library_url=sample_url,
            docs_url=docs_url,
            manual_intervention_needed=needs_manual,
            manual_reason=manual_reason,
            manual_instructions=manual_instructions,
            associated_links=links,
        )

        # Every item gets its local `.vstprofile.json` and `.sfz` auto-downloaded;
        # items that also need manual installer/sample-bank action are additionally listed in `manual_intervention`.
        auto_downloaded.append(item)
        if needs_manual:
            manual_intervention.append(item)

    # 5. Optional Live GitHub Repository Discovery for additional open-source VST3 plugins
    live_discoveries: list[dict[str, Any]] = []
    if search_github_live:
        known_repos = {s.repo_url.lower().rstrip("/") for s in OPEN_SOURCE_VST_CATALOG}
        try:
            q_cat = target_cats[0] if target_cats else "synthesizer"
            gh_search_url = "https://api.github.com/search/repositories"
            resp = requests.get(
                gh_search_url,
                params={"q": f"vst3 {q_cat} topic:vst3", "sort": "stars", "order": "desc", "per_page": 6},
                timeout=4.5,
                headers={"Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 200:
                for repo_item in resp.json().get("items", []):
                    html_url = str(repo_item.get("html_url") or "")
                    if html_url.lower().rstrip("/") in known_repos:
                        continue
                    lic_info = repo_item.get("license") or {}
                    live_discoveries.append(
                        {
                            "name": str(repo_item.get("full_name") or ""),
                            "description": str(repo_item.get("description") or ""),
                            "stars": int(repo_item.get("stargazers_count") or 0),
                            "license": str(lic_info.get("spdx_id") or "Open Source"),
                            "repo_url": html_url,
                            "releases_url": f"{html_url}/releases",
                        }
                    )
        except Exception:
            pass

    if parts:
        assign_recommended_vsts_to_parts(parts)

    report = VSTDeepSearchReport(
        searched_categories=target_cats,
        total_evaluated=len(specs_to_check),
        auto_downloaded=auto_downloaded,
        manual_intervention=manual_intervention,
        live_github_discoveries=live_discoveries,
    )
    write_vst_deep_search_report(report, dest_root)
    return report


def write_vst_deep_search_report(report: VSTDeepSearchReport, output_dir: Path | None = None) -> tuple[Path, Path]:
    """Write a comprehensive Markdown and JSON report of auto-downloaded VSTs and manual-intervention links."""
    dest_dir = output_dir.resolve() if output_dir else get_managed_vst_directory()
    dest_dir.mkdir(parents=True, exist_ok=True)

    md_path = dest_dir / "VST_Deep_Search_Report.md"
    json_path = dest_dir / "VST_Deep_Search_Report.json"

    lines: list[str] = [
        "# Open-Source VST Deep Search & Auto-Download Report",
        "",
        f"- **Evaluated Instrument Categories:** `{', '.join(report.searched_categories) or 'all'}`",
        f"- **Total Recommended VST Setups Evaluated:** `{report.total_evaluated}`",
        f"- **Auto-Downloaded Profiles & Bundles:** `{len(report.auto_downloaded)}`",
        f"- **Recommended Setups Requiring Manual Installer / External Sample Bank:** `{len(report.manual_intervention)}`",
        "",
        "---",
        "",
        "## 1. Automatically Downloaded & Ready in Workspace",
        "",
        "The following open-source VST acoustic profiles (`.vstprofile.json`), SFZ patches (`.sfz`), and any directly "
        "available portable binaries have been automatically downloaded and configured for immediate playback:",
        "",
    ]

    for item in report.auto_downloaded:
        tag_str = f" (`{item.release_tag}`)" if item.release_tag else ""
        lines.append(f"### ✔ [{item.instrument_category.upper()}] {item.name}{tag_str}")
        lines.append(f"- **Developer / License:** {item.developer} ({item.license})")
        lines.append(f"- **Matched Instruments:** {', '.join(item.instruments_matched)}")
        lines.append("- **Automatically Downloaded Local Files:**")
        for fp in item.auto_downloaded_files:
            lines.append(f"  - `{fp}`")
        lines.append("- **Associated Links:**")
        for lbl, url in item.associated_links.items():
            lines.append(f"  - [{lbl}]({url})")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 2. Recommended Open-Source VSTs & Sample Libraries Requiring Manual Intervention",
            "",
            "The following recommended open-source VSTs or companion multi-gigabyte SFZ sample banks require manual "
            "action (such as running an interactive Windows `.exe`/`.msi` installer with UAC elevation or downloading "
            "a large multi-part orchestral WAV archive from an external host):",
            "",
        ]
    )

    if not report.manual_intervention:
        lines.append("*None — all evaluated VSTs were completely auto-downloaded without manual steps!*")
        lines.append("")
    else:
        for item in report.manual_intervention:
            lines.append(f"### ⚠ [{item.instrument_category.upper()}] {item.name}")
            lines.append(f"- **Why Manual Intervention is Required:** {item.manual_reason}")
            if item.manual_instructions:
                lines.append("- **Manual Setup Steps:**")
                for step_ln in item.manual_instructions.splitlines():
                    lines.append(f"  {step_ln}")
            lines.append("- **Direct Links for Manual Download:**")
            for lbl, url in item.associated_links.items():
                lines.append(f"  - **{lbl}:** [{url}]({url})")
            lines.append("")

    if report.live_github_discoveries:
        lines.extend(
            [
                "---",
                "",
                "## 3. Additional Trending Open-Source VST3 Repositories Discovered via Live GitHub Search",
                "",
            ]
        )
        for disc in report.live_github_discoveries:
            lines.append(
                f"- **[{disc['name']}]({disc['repo_url']})** (★ {disc['stars']} | License: `{disc['license']}`)"
            )
            if disc.get("description"):
                lines.append(f"  - {disc['description']}")
            lines.append(f"  - [Releases & Downloads]({disc['releases_url']})")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    report.markdown_report_path = md_path
    report.json_report_path = json_path
    json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path
