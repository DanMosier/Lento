"""MusicXML (.musicxml / .xml / .mxl) parser that extracts instrument parts, metadata, and timed NoteEvents."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .models import InstrumentPart, NoteEvent, ParsedScore
from .vst_catalog import assign_recommended_vsts_to_parts, classify_instrument_category

STEP_TO_SEMITONE: dict[str, int] = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}

DYNAMIC_TO_VELOCITY: dict[str, int] = {
    "ppp": 35,
    "pp": 48,
    "p": 60,
    "mp": 72,
    "mf": 85,
    "f": 98,
    "ff": 112,
    "fff": 122,
}


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _read_musicxml_root(path: Path) -> ET.Element:
    """Load an ElementTree root from either a raw .musicxml/.xml file or a compressed .mxl archive."""
    if path.suffix.lower() == ".mxl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            rootfile: str | None = None
            if "META-INF/container.xml" in names:
                try:
                    c_root = ET.fromstring(zf.read("META-INF/container.xml"))
                    for el in c_root.iter():
                        if _strip_ns(el.tag) == "rootfile" and el.attrib.get("full-path"):
                            rootfile = el.attrib["full-path"]
                            break
                except Exception:
                    pass
            if not rootfile or rootfile not in names:
                candidates = [
                    n for n in names if n.lower().endswith((".xml", ".musicxml")) and not n.startswith("META-INF")
                ]
                if not candidates:
                    raise ValueError(f"No XML score entry found inside {path}")
                rootfile = candidates[0]
            xml_bytes = zf.read(rootfile)
            root = ET.fromstring(xml_bytes)
    else:
        tree = ET.parse(path)
        root = tree.getroot()

    # Strip XML namespaces in-place for uniform tag lookup
    for el in root.iter():
        el.tag = _strip_ns(el.tag)
    return root


def pitch_to_midi_and_name(step: str, alter: float, octave: int, transpose_chromatic: int = 0) -> tuple[int, str]:
    """Convert MusicXML (step, alter, octave) to MIDI note number (60 = C4) and readable pitch name."""
    step_up = step.strip().upper()
    base_semi = STEP_TO_SEMITONE.get(step_up, 0)
    alter_int = int(round(alter))
    midi = (octave + 1) * 12 + base_semi + alter_int + transpose_chromatic
    midi = max(0, min(127, midi))

    acc = ""
    if alter_int == 1:
        acc = "#"
    elif alter_int == 2:
        acc = "##"
    elif alter_int == -1:
        acc = "b"
    elif alter_int == -2:
        acc = "bb"
    return midi, f"{step_up}{acc}{octave}"


def parse_musicxml(path: Path) -> ParsedScore:
    """Parse a MusicXML (.musicxml, .xml, or .mxl) file into a ParsedScore with open-source VST assignments."""
    path = path.resolve()
    root = _read_musicxml_root(path)

    title = ""
    work_title_el = root.find("./work/work-title")
    if work_title_el is not None and work_title_el.text:
        title = work_title_el.text.strip()
    if not title:
        mov_el = root.find("./movement-title")
        if mov_el is not None and mov_el.text:
            title = mov_el.text.strip()
    if not title:
        for credit_words in root.findall("./credit/credit-words"):
            if credit_words.text and len(credit_words.text.strip()) > 2:
                title = credit_words.text.strip()
                break
    if not title:
        title = path.stem

    composer = "Unknown Composer"
    for creator in root.findall("./identification/creator"):
        if creator.attrib.get("type", "").lower() == "composer" and creator.text:
            composer = creator.text.strip()
            break
    if composer == "Unknown Composer" and " - " in path.stem:
        composer = path.stem.split(" - ", 1)[0].strip()

    # Global defaults
    tempo_bpm = 112.0
    for sound_el in root.findall(".//sound"):
        if "tempo" in sound_el.attrib:
            try:
                val = float(sound_el.attrib["tempo"])
                if 20.0 <= val <= 320.0:
                    tempo_bpm = val
                    break
            except ValueError:
                pass
    if tempo_bpm == 112.0:
        per_min_el = root.find(".//metronome/per-minute")
        if per_min_el is not None and per_min_el.text:
            try:
                val = float(per_min_el.text.strip())
                if 20.0 <= val <= 320.0:
                    tempo_bpm = val
            except ValueError:
                pass

    time_sig = (4, 4)
    beats_el = root.find(".//attributes/time/beats")
    beat_type_el = root.find(".//attributes/time/beat-type")
    if beats_el is not None and beat_type_el is not None and beats_el.text and beat_type_el.text:
        try:
            time_sig = (int(beats_el.text.strip()), int(beat_type_el.text.strip()))
        except ValueError:
            pass

    key_fifths = 0
    fifths_el = root.find(".//attributes/key/fifths")
    if fifths_el is not None and fifths_el.text:
        try:
            key_fifths = int(fifths_el.text.strip())
        except ValueError:
            pass

    # Map score-part definitions
    part_meta: dict[str, tuple[str, int]] = {}
    for idx, sp_el in enumerate(root.findall("./part-list/score-part"), start=1):
        pid = sp_el.attrib.get("id", f"P{idx}")
        pname_el = sp_el.find("part-name")
        inst_name_el = sp_el.find("./score-instrument/instrument-name")
        pname = ""
        if pname_el is not None and pname_el.text and pname_el.text.strip():
            pname = pname_el.text.strip()
        elif inst_name_el is not None and inst_name_el.text and inst_name_el.text.strip():
            pname = inst_name_el.text.strip()
        else:
            pname = f"Part {idx}"

        midi_prog = 0
        mp_el = sp_el.find("./midi-instrument/midi-program")
        if mp_el is not None and mp_el.text:
            try:
                midi_prog = int(mp_el.text.strip())
            except ValueError:
                midi_prog = 0
        part_meta[pid] = (pname, midi_prog)

    sec_per_beat = 60.0 / max(20.0, tempo_bpm)
    parsed_parts: list[InstrumentPart] = []
    max_measures = 0
    max_beats = 0.0

    for p_idx, part_el in enumerate(root.findall("./part"), start=1):
        pid = part_el.attrib.get("id", f"P{p_idx}")
        pname, midi_prog = part_meta.get(pid, (f"Instrument {p_idx}", 0))
        category = classify_instrument_category(pname, midi_prog)

        inst_part = InstrumentPart(
            part_id=pid,
            part_name=pname,
            instrument_category=category,
            midi_program=midi_prog,
        )

        divisions = 1.0
        transpose_chromatic = 0
        current_velocity = 85
        part_cursor_beats = 0.0
        last_note_start_beats = 0.0

        # Track active tied notes by (voice, staff, midi_pitch) -> NoteEvent
        open_ties: dict[tuple[str, int, int], NoteEvent] = {}

        measures = part_el.findall("./measure")
        max_measures = max(max_measures, len(measures))

        for m_idx, m_el in enumerate(measures, start=1):
            m_num_str = m_el.attrib.get("number", str(m_idx))
            try:
                m_num = int("".join(ch for ch in m_num_str if ch.isdigit()) or str(m_idx))
            except ValueError:
                m_num = m_idx

            measure_start_beats = part_cursor_beats
            local_cursor_beats = measure_start_beats
            max_local_cursor_beats = measure_start_beats

            for child in m_el:
                tag = child.tag
                if tag == "attributes":
                    div_el = child.find("divisions")
                    if div_el is not None and div_el.text:
                        try:
                            d_val = float(div_el.text.strip())
                            if d_val > 0:
                                divisions = d_val
                        except ValueError:
                            pass
                    tr_el = child.find("./transpose/chromatic")
                    if tr_el is not None and tr_el.text:
                        try:
                            transpose_chromatic = int(tr_el.text.strip())
                        except ValueError:
                            pass

                elif tag == "direction":
                    dyn_el = child.find("./direction-type/dynamics")
                    if dyn_el is not None:
                        for d_child in dyn_el:
                            if d_child.tag.lower() in DYNAMIC_TO_VELOCITY:
                                current_velocity = DYNAMIC_TO_VELOCITY[d_child.tag.lower()]
                                break

                elif tag == "backup":
                    dur_el = child.find("duration")
                    if dur_el is not None and dur_el.text:
                        try:
                            back_beats = float(dur_el.text.strip()) / divisions
                            local_cursor_beats = max(measure_start_beats, local_cursor_beats - back_beats)
                        except ValueError:
                            pass

                elif tag == "forward":
                    dur_el = child.find("duration")
                    if dur_el is not None and dur_el.text:
                        try:
                            fwd_beats = float(dur_el.text.strip()) / divisions
                            local_cursor_beats += fwd_beats
                            max_local_cursor_beats = max(max_local_cursor_beats, local_cursor_beats)
                        except ValueError:
                            pass

                elif tag == "note":
                    # Ignore grace notes (they have no duration or <grace/> tag)
                    if child.find("grace") is not None:
                        continue

                    dur_el = child.find("duration")
                    dur_divs = 0.0
                    if dur_el is not None and dur_el.text:
                        try:
                            dur_divs = float(dur_el.text.strip())
                        except ValueError:
                            dur_divs = 0.0
                    dur_beats = max(0.05, dur_divs / divisions) if dur_divs > 0 else 0.5

                    is_chord = child.find("chord") is not None
                    is_rest = child.find("rest") is not None
                    voice = (child.findtext("voice") or "1").strip()
                    staff_text = (child.findtext("staff") or "1").strip()
                    try:
                        staff_num = int(staff_text)
                    except ValueError:
                        staff_num = 1

                    note_start_beats = last_note_start_beats if is_chord else local_cursor_beats

                    if is_rest:
                        ev = NoteEvent(
                            pitch_midi=-1,
                            pitch_name="Rest",
                            start_beat=note_start_beats,
                            duration_beats=dur_beats,
                            start_sec=note_start_beats * sec_per_beat,
                            duration_sec=dur_beats * sec_per_beat,
                            velocity=0,
                            measure_number=m_num,
                            is_rest=True,
                            staff=staff_num,
                            voice=voice,
                            is_chord=is_chord,
                        )
                        inst_part.notes.append(ev)
                    else:
                        pitch_el = child.find("pitch")
                        unpitched_el = child.find("unpitched")
                        if pitch_el is not None:
                            step = (pitch_el.findtext("step") or "C").strip()
                            alter_text = (pitch_el.findtext("alter") or "0").strip()
                            oct_text = (pitch_el.findtext("octave") or "4").strip()
                            try:
                                alter = float(alter_text)
                            except ValueError:
                                alter = 0.0
                            try:
                                octave = int(oct_text)
                            except ValueError:
                                octave = 4
                            midi_num, pitch_name = pitch_to_midi_and_name(step, alter, octave, transpose_chromatic)
                        elif unpitched_el is not None:
                            midi_num, pitch_name = 48, "C3"
                        else:
                            midi_num, pitch_name = 60, "C4"

                        tie_types = {t.attrib.get("type", "") for t in child.findall("tie")}
                        tie_key = (voice, staff_num, midi_num)

                        if "stop" in tie_types and tie_key in open_ties:
                            prev_ev = open_ties.pop(tie_key)
                            prev_ev.duration_beats += dur_beats
                            prev_ev.duration_sec = prev_ev.duration_beats * sec_per_beat
                            if "start" in tie_types:
                                open_ties[tie_key] = prev_ev
                        else:
                            ev = NoteEvent(
                                pitch_midi=midi_num,
                                pitch_name=pitch_name,
                                start_beat=note_start_beats,
                                duration_beats=dur_beats,
                                start_sec=note_start_beats * sec_per_beat,
                                duration_sec=dur_beats * sec_per_beat,
                                velocity=current_velocity,
                                measure_number=m_num,
                                is_rest=False,
                                staff=staff_num,
                                voice=voice,
                                is_chord=is_chord,
                            )
                            inst_part.notes.append(ev)
                            if "start" in tie_types:
                                open_ties[tie_key] = ev

                    if not is_chord:
                        last_note_start_beats = local_cursor_beats
                        local_cursor_beats += dur_beats
                        max_local_cursor_beats = max(max_local_cursor_beats, local_cursor_beats)

            part_cursor_beats = max(max_local_cursor_beats, local_cursor_beats)
            max_beats = max(max_beats, part_cursor_beats)

        parsed_parts.append(inst_part)

    # Automatically recommend and assign the best open-source VST per instrument part
    assign_recommended_vsts_to_parts(parsed_parts)

    total_duration_sec = max_beats * sec_per_beat
    return ParsedScore(
        musicxml_path=path,
        title=title,
        composer=composer,
        tempo_bpm=tempo_bpm,
        time_signature=time_sig,
        key_fifths=key_fifths,
        total_measures=max_measures,
        total_duration_sec=total_duration_sec,
        total_beats=max_beats,
        parts=parsed_parts,
    )
