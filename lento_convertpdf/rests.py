"""Expand multi-bar rests so that bar numbers match the printed score.

MusicXML marks a multi-bar rest with <measure-style><multiple-rest>N</multiple-rest> in its first measure, and the
N-1 measures it covers still follow as ordinary rest measures. homr writes only the first measure, so a part
with a 12-bar rest comes out 11 bars short and drifts out of line with the other parts and with the recording.
This puts the missing measures back, in every part, and renumbers what follows.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def _rest_only(measure: ET.Element) -> bool:
    notes = measure.findall("note")
    return bool(notes) and all(n.find("rest") is not None for n in notes)


def _count(measure: ET.Element) -> int:
    text = measure.findtext("attributes/measure-style/multiple-rest") or ""
    try:
        return int(text.strip())
    except ValueError:
        return 0


def _already_expanded(measures: list[ET.Element], i: int, n: int) -> bool:
    following = measures[i + 1 : i + n]
    return len(following) == n - 1 and all(_rest_only(m) for m in following)


class _Meter:
    """The divisions, time signature and staff count in force, as a part is read from left to right."""

    def __init__(self) -> None:
        self.divisions, self.beats, self.beat_type, self.staves = 1, 4, 4, 1

    def read(self, measure: ET.Element) -> None:
        for attrs in measure.findall("attributes"):
            for tag, field in (("divisions", "divisions"), ("time/beats", "beats"), ("time/beat-type", "beat_type"), ("staves", "staves")):
                text = (attrs.findtext(tag) or "").strip()
                if text.isdigit() and int(text) > 0:
                    setattr(self, field, int(text))

    def rest_measure(self, number: str) -> ET.Element:
        measure = ET.Element("measure", number=number)
        duration = str(self.divisions * self.beats * 4 // self.beat_type)
        for staff in range(1, self.staves + 1):
            if staff > 1:
                ET.SubElement(ET.SubElement(measure, "backup"), "duration").text = duration
            note = ET.SubElement(measure, "note")
            ET.SubElement(note, "rest", measure="yes")
            ET.SubElement(note, "duration").text = duration
            ET.SubElement(note, "voice").text = str(1 + 4 * (staff - 1))
            if self.staves > 1:
                ET.SubElement(note, "staff").text = str(staff)
        return measure


def expand_multirests(xml_path: Path) -> int:
    """Insert the measures that homr left out after each multi-bar rest. Returns how many were added."""
    tree = ET.parse(xml_path)
    parts = tree.getroot().findall("part")
    if not parts:
        return 0
    columns = [p.findall("measure") for p in parts]

    # Where to insert, by measure position: a multi-bar rest in any part covers the whole score at that point
    inserts: dict[int, int] = {}
    for measures in columns:
        for i, measure in enumerate(measures):
            n = _count(measure)
            if n > 1 and not _already_expanded(measures, i, n):
                inserts[i] = max(inserts.get(i, 0), n - 1)
    if not inserts:
        return 0

    for part, measures in zip(parts, columns):
        meter = _Meter()
        shift = 0
        for i, measure in enumerate(measures):
            meter.read(measure)
            if shift and (measure.get("number") or "").isdigit():
                measure.set("number", str(int(measure.get("number", "0")) + shift))
            extra = inserts.get(i, 0)
            if not extra:
                continue
            base = int(measure.get("number")) if (measure.get("number") or "").isdigit() else 0
            # a part without the multi-bar rest here still gets the bars, as plain rests after its own music
            position = list(part).index(measure)
            for k in range(1, extra + 1):
                part.insert(position + k, meter.rest_measure(str(base + k)))
            shift += extra
    tree.write(xml_path, encoding="UTF-8", xml_declaration=True)
    return sum(inserts.values())


def even_out_parts(xml_path: Path) -> dict[str, int]:
    """Fill parts that came out shorter than the longest with rest measures. Returns {part name: measures added}.

    homr sometimes reads fewer measures for one instrument than another (a missed system, merged staves). The
    renderer in the app stops at the end of the shortest part, so the rest of every other part would vanish: in a
    sonata with a 380-measure piano part and a 1,167-measure cello part, only 380 measures showed. Padding keeps
    everything visible and playable; the measures still don't line up, which the quality report already says.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    parts = root.findall("part")
    counts = [len(p.findall("measure")) for p in parts]
    if len(set(counts)) <= 1:
        return {}
    longest = max(counts)
    names = {sp.get("id"): (sp.findtext("part-name") or "").strip() for sp in root.findall("part-list/score-part")}
    added: dict[str, int] = {}
    for part, count in zip(parts, counts):
        if count == longest:
            continue
        meter = _Meter()
        measures = part.findall("measure")
        for measure in measures:
            meter.read(measure)
        last = measures[-1].get("number", "") if measures else ""
        number = int(last) if last.isdigit() else count
        for k in range(1, longest - count + 1):
            part.append(meter.rest_measure(str(number + k)))
        name = names.get(part.get("id")) or part.get("id", "")
        added[name] = added.get(name, 0) + longest - count
    tree.write(xml_path, encoding="UTF-8", xml_declaration=True)
    return added
