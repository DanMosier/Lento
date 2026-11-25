"""Read one part of a MusicXML score into a flat list of notes with times.

Kept free of any feature code so the converter, the practice tool and later
features can all use it. Each note keeps a reference to its XML element, so a
feature can write results back into a copy of the score (for example colors).
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
DEFAULT_TEMPO = 90.0
CELLO_NAMES = re.compile(r"\b(cello|violoncello|vc|vlc|celli)\b", re.IGNORECASE)
# quarter notes per beat unit, for <metronome>
BEAT_UNITS = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}


def midi_name(midi: float) -> str:
    m = int(round(midi))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


@dataclass
class ScoreNote:
    """One sounding note. Tied notes are merged into the first one."""

    index: int
    midi: int
    measure: str  # measure number as printed in the file
    measure_index: int  # 0-based position of the measure in the part
    beat: float  # quarter notes from the start of the part
    beat_in_measure: float
    duration: float  # quarter notes, ties included
    start_sec: float = 0.0
    duration_sec: float = 0.0
    in_chord: bool = False  # part of a double stop
    voice: str = "1"
    elements: list[ET.Element] = field(default_factory=list, repr=False, compare=False)

    @property
    def name(self) -> str:
        return midi_name(self.midi)


@dataclass
class Score:
    path: Path
    title: str
    part_id: str
    part_name: str
    notes: list[ScoreNote]
    tempos: list[tuple[float, float]]  # (beat, quarter notes per minute), sorted
    measures: list[str]  # printed measure numbers in order
    measure_starts: list[float]  # beat of each measure start
    total_beats: float
    tree: ET.ElementTree = field(repr=False, compare=False)
    warnings: list[str] = field(default_factory=list)

    def seconds_at(self, beat: float) -> float:
        """Seconds from the start at the score's written tempo."""
        secs, last_beat, bpm = 0.0, 0.0, self.tempos[0][1]
        for tb, tbpm in self.tempos[1:]:
            if tb >= beat:
                break
            secs += (tb - last_beat) * 60.0 / bpm
            last_beat, bpm = tb, tbpm
        return secs + (beat - last_beat) * 60.0 / bpm

    def measure_range(self, first: str, last: str) -> tuple[int, int]:
        """Measure indexes for printed measure numbers, inclusive."""
        try:
            return self.measures.index(first), len(self.measures) - 1 - self.measures[::-1].index(last)
        except ValueError as exc:
            raise ValueError(f"measure {exc} is not in the score") from None


def _read_root(path: Path) -> ET.ElementTree:
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as zf:
            name = None
            try:
                container = ET.fromstring(zf.read("META-INF/container.xml"))
                rootfile = container.find(".//{*}rootfile")
                if rootfile is not None:
                    name = rootfile.attrib.get("full-path")
            except KeyError:
                pass
            if not name:
                name = next(n for n in zf.namelist() if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
            return ET.ElementTree(ET.fromstring(zf.read(name)))
    return ET.parse(path)


def _num(text: str | None, default: float = 0.0) -> float:
    try:
        return float((text or "").strip())
    except ValueError:
        return default


def _pick_part(root: ET.Element, wanted: str | None) -> tuple[ET.Element, str, str]:
    names: dict[str, str] = {}
    for sp in root.findall("./part-list/score-part"):
        pid = sp.attrib.get("id", "")
        names[pid] = (sp.findtext("part-name") or sp.findtext("./score-instrument/instrument-name") or pid).strip()
    parts = root.findall("./part")
    if not parts:
        raise ValueError("the score has no parts (is it a timewise MusicXML file?)")

    def label(p: ET.Element) -> str:
        return names.get(p.attrib.get("id", ""), p.attrib.get("id", ""))

    if wanted:
        for p in parts:
            if wanted == p.attrib.get("id") or wanted.lower() in label(p).lower():
                return p, p.attrib.get("id", ""), label(p)
        raise ValueError(f"no part matches {wanted!r}; parts are: {', '.join(label(p) for p in parts)}")
    for p in parts:
        if CELLO_NAMES.search(label(p)):
            return p, p.attrib.get("id", ""), label(p)
    return parts[0], parts[0].attrib.get("id", ""), label(parts[0])


def load_score(path: str | Path, part: str | None = None) -> Score:
    """Read one part of a .musicxml, .xml or .mxl file.

    `part` is a part id or part of its name. Without it, the first part named
    like a cello is used, else the first part.
    """
    path = Path(path)
    tree = _read_root(path)
    root = tree.getroot()
    # drop namespaces so plain tag names work
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = el.tag.split("}", 1)[1]
    if root.tag == "score-timewise":
        raise ValueError("timewise MusicXML is not supported; export as partwise")

    title = (root.findtext("./work/work-title") or root.findtext("./movement-title") or path.stem).strip()
    part_el, part_id, part_name = _pick_part(root, part)

    warnings: list[str] = []
    notes: list[ScoreNote] = []
    tempos: list[tuple[float, float]] = []
    measures: list[str] = []
    measure_starts: list[float] = []
    divisions = 1.0
    transpose = 0
    cursor = 0.0
    open_ties: dict[tuple[str, int], ScoreNote] = {}
    saw_repeat = False

    for m_idx, m_el in enumerate(part_el.findall("./measure")):
        m_num = m_el.attrib.get("number", str(m_idx + 1))
        measures.append(m_num)
        measure_starts.append(cursor)
        pos = cursor
        furthest = cursor
        last_onset = cursor
        for child in m_el:
            tag = child.tag
            if tag == "attributes":
                divisions = _num(child.findtext("divisions"), divisions) or divisions
                tr = child.find("transpose")
                if tr is not None:
                    transpose = int(_num(tr.findtext("chromatic"))) + 12 * int(_num(tr.findtext("octave-change")))
            elif tag == "direction":
                snd = child.find("sound")
                if snd is not None and "tempo" in snd.attrib:
                    tempos.append((pos, _num(snd.attrib["tempo"], DEFAULT_TEMPO)))
                else:
                    met = child.find("./direction-type/metronome")
                    if met is not None and met.findtext("per-minute"):
                        unit = BEAT_UNITS.get((met.findtext("beat-unit") or "quarter").strip(), 1.0)
                        if met.find("beat-unit-dot") is not None:
                            unit *= 1.5
                        bpm = _num(re.sub(r"[^0-9.]", "", met.findtext("per-minute") or ""), 0.0)
                        if bpm > 0:
                            tempos.append((pos, bpm * unit))
            elif tag == "sound" and "tempo" in child.attrib:
                tempos.append((pos, _num(child.attrib["tempo"], DEFAULT_TEMPO)))
            elif tag == "barline" and child.find("repeat") is not None:
                saw_repeat = True
            elif tag == "backup":
                pos -= _num(child.findtext("duration")) / divisions
            elif tag == "forward":
                pos += _num(child.findtext("duration")) / divisions
                furthest = max(furthest, pos)
            elif tag == "note":
                if child.find("grace") is not None or child.find("cue") is not None:
                    continue
                dur = _num(child.findtext("duration")) / divisions
                chord = child.find("chord") is not None
                onset = last_onset if chord else pos
                if not chord:
                    last_onset = pos
                    pos += dur
                    furthest = max(furthest, pos)
                pitch = child.find("pitch")
                if child.find("rest") is not None or pitch is None:
                    continue
                midi = (
                    12 * (int(_num(pitch.findtext("octave"), 4)) + 1)
                    + STEP_SEMITONES.get((pitch.findtext("step") or "C").strip().upper(), 0)
                    + int(round(_num(pitch.findtext("alter"))))
                    + transpose
                )
                voice = (child.findtext("voice") or "1").strip()
                tie_types = {t.attrib.get("type") for t in child.findall("tie")}
                key = (voice, midi)
                if "stop" in tie_types and key in open_ties:
                    held = open_ties[key]
                    held.duration = onset + dur - held.beat
                    held.elements.append(child)
                    if "start" not in tie_types:
                        del open_ties[key]
                    continue
                if chord and notes and abs(notes[-1].beat - onset) < 1e-6:
                    notes[-1].in_chord = True
                note = ScoreNote(
                    index=len(notes),
                    midi=midi,
                    measure=m_num,
                    measure_index=m_idx,
                    beat=onset,
                    beat_in_measure=onset - cursor,
                    duration=dur,
                    in_chord=chord,
                    voice=voice,
                    elements=[child],
                )
                notes.append(note)
                if "start" in tie_types:
                    open_ties[key] = note
        cursor = furthest if furthest > cursor else cursor

    if saw_repeat:
        warnings.append("The score has repeat signs. Notes are read once, as written; play repeats only once.")
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0.0, tempos[0][1] if tempos else DEFAULT_TEMPO))
        if len(tempos) == 1:
            warnings.append(f"No tempo marking found; assuming {DEFAULT_TEMPO:g} quarter notes per minute.")
    tempos.sort()

    # chord notes share an onset; mark every member, not just the later ones
    by_onset: dict[float, list[ScoreNote]] = {}
    for n in notes:
        by_onset.setdefault(round(n.beat, 6), []).append(n)
    for group in by_onset.values():
        if len(group) > 1:
            for n in group:
                n.in_chord = True
    notes.sort(key=lambda n: (n.beat, -n.midi))
    for i, n in enumerate(notes):
        n.index = i

    score = Score(
        path=path,
        title=title,
        part_id=part_id,
        part_name=part_name,
        notes=notes,
        tempos=tempos,
        measures=measures,
        measure_starts=measure_starts,
        total_beats=cursor,
        tree=tree,
        warnings=warnings,
    )
    for n in notes:
        n.start_sec = score.seconds_at(n.beat)
        n.duration_sec = score.seconds_at(n.beat + n.duration) - n.start_sec
    return score
