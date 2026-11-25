"""Join systems that were read one at a time into one score, instrument by instrument.

Standard library only: homr_bridge.py loads this file inside homr's environment.

Every system contributes the same number of measures to every instrument, so a staff that lost or gained a barline
cannot shift the instruments against each other further down the score. Whatever had to be patched is reported.
"""

from __future__ import annotations

import copy
import statistics
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

Meter = tuple[str, str]
_ATTRIBUTE_ORDER = ["divisions", "key", "time", "staves", "part-symbol", "clef", "staff-details", "transpose"]


@dataclass
class Read:
    """One instrument's staff in one system, as homr wrote it."""

    measures: list[ET.Element]
    ends: list[float] | None = None  # where each measure ends on the page, if known


@dataclass
class System:
    page: int
    number: int  # on the page, from 1
    reads: dict[int, Read] = field(default_factory=dict)  # instrument -> its staff
    unplaced: list[tuple[int, Read]] = field(default_factory=list)  # staff number in the system, staff
    unread: list[int] = field(default_factory=list)  # instruments shown, but homr found nothing on the staff
    by_position: list[int] = field(default_factory=list)  # instruments placed without a label of their own

    @property
    def all_reads(self) -> list[Read]:
        return [*self.reads.values(), *(read for _, read in self.unplaced)]


def meter_length(meter: Meter) -> Fraction:
    return sum((Fraction(b) for b in meter[0].split("+")), Fraction(0)) * 4 / Fraction(meter[1])


def measure_count(system: System) -> int:
    """What most staves of the system say. On a tie the larger number, as homr rather misses barlines."""
    counts = Counter(len(read.measures) for read in system.all_reads)
    return max(counts, key=lambda n: (counts[n], n)) if counts else 0


def _meter_of(measure: ET.Element) -> Meter | None:
    time = measure.find("attributes/time")
    if time is None:
        return None
    beats, beat_type = time.findtext("beats", ""), time.findtext("beat-type", "")
    try:
        meter_length((beats, beat_type))
    except (ValueError, ZeroDivisionError):
        return None
    return beats, beat_type


def vote_meters(system: System, count: int, current: Meter | None) -> list[Meter | None]:
    """The meter of each measure. All instruments share it, so a staff that misread it is outvoted."""
    votes: list[Counter[Meter]] = [Counter() for _ in range(count)]
    for read in system.all_reads:
        if len(read.measures) != count:
            continue
        weight = 4 if any(m.find("note/pitch") is not None for m in read.measures) else 1
        meter = None
        for k, measure in enumerate(read.measures):
            meter = _meter_of(measure) or meter
            if meter:
                votes[k][meter] += weight
    result: list[Meter | None] = []
    for tally in votes:
        if tally:
            winner, weight = tally.most_common(1)[0]
            if current is None or weight * 2 > tally.total():
                current = winner
        result.append(current)
    return result


def _common_ends(system: System, count: int) -> list[float] | None:
    rows = [r.ends for r in system.all_reads if r.ends and len(r.ends) == len(r.measures) == count]
    return [statistics.median(column) for column in zip(*rows)] if rows else None


def fit_measures(read: Read, count: int, ends: list[float] | None) -> tuple[list[list[ET.Element]], list[int]]:
    """Distribute the measures of a staff over the measures of its system.

    Returns the measures that belong to each place (none: lost, several: a false barline) and the places in doubt.
    """
    n = len(read.measures)
    if n == count:
        return [[m] for m in read.measures], []
    places: list[list[ET.Element]] = [[] for _ in range(count)]
    if ends and read.ends and len(read.ends) == n:
        # A measure ends at the barline nearest to its own
        for measure, end in zip(read.measures, read.ends):
            slot = min(range(count), key=lambda k: abs(ends[k] - end))
            places[slot].append(measure)
        # A lost barline joins a measure with the one before, which is then missing
        doubt = {k for k, p in enumerate(places) if len(p) != 1}
        doubt |= {k + 1 for k in doubt if not places[k] and k + 1 < count}
        return places, sorted(doubt)
    for k, measure in enumerate(read.measures):
        places[min(k, count - 1)].append(measure)
    return places, list(range(count))


# ---- writing -----------------------------------------------------------------------------------


def _set_attribute(attributes: ET.Element, element: ET.Element) -> None:
    """Insert at the place the MusicXML schema wants it."""
    rank = _ATTRIBUTE_ORDER.index(element.tag)
    at = len(attributes)
    for i, child in enumerate(attributes):
        if child.tag in _ATTRIBUTE_ORDER and _ATTRIBUTE_ORDER.index(child.tag) > rank:
            at = i
            break
    attributes.insert(at, element)


def _element(tag: str, text: str | None = None, **attributes: str) -> ET.Element:
    element = ET.Element(tag, attributes)
    element.text = text
    return element


def _time_element(meter: Meter) -> ET.Element:
    time = ET.Element("time")
    time.append(_element("beats", meter[0]))
    time.append(_element("beat-type", meter[1]))
    return time


def _rest(duration: int, staff: int) -> ET.Element:
    note = ET.Element("note")
    note.append(ET.Element("rest", {"measure": "yes"}))
    note.append(_element("duration", str(duration)))
    note.append(_element("voice", "1" if staff == 1 else "5"))
    note.append(_element("staff", str(staff)))
    return note


def _backup(duration: int) -> ET.Element:
    backup = ET.Element("backup")
    backup.append(_element("duration", str(duration)))
    return backup


def _position(measure: Iterable[ET.Element]) -> int:
    """Where the measure's cursor stands after its last element, in divisions."""
    position = 0
    for el in measure:
        length = int(el.findtext("duration") or 0)
        if el.tag == "backup":
            position -= length
        elif el.tag == "forward" or (el.tag == "note" and el.find("chord") is None and el.find("grace") is None):
            position += length
    return position


def _signature(element: ET.Element) -> tuple[str, ...]:
    return tuple((child.tag + "=" + (child.text or "").strip()) for child in element)


class PartWriter:
    """Writes one instrument from system to system and repeats no clef, key or meter that is still in force."""

    def __init__(self, part_id: str, staves: int) -> None:
        self.part = ET.Element("part", {"id": part_id})
        self.staves = staves
        self.divisions = 0  # in force in what is written
        self.source_divisions = 1  # in force in what homr wrote
        self.key: tuple[str, ...] | None = None
        self.clefs: dict[str, tuple[str, ...]] = {}
        self.meter: Meter | None = None

    def add(self, measures: list[ET.Element], meter: Meter | None, length: Fraction | None = None) -> None:
        """length: how long the measure really is, if it is not what the meter says (a pickup)."""
        measure = ET.Element("measure", {"number": str(len(self.part) + 1)})
        for source in measures:
            measure.extend(copy.deepcopy(el) for el in source)
        self._clean_attributes(measure)
        length = length or (meter_length(meter) if meter else Fraction(4))
        if any(n.find("rest") is None for n in measure.findall("note")):
            divisions = self.source_divisions
        else:
            divisions = self.divisions or length.denominator
            divisions *= (length * divisions).denominator
        if divisions != self.divisions:
            self._attributes(measure).insert(0, _element("divisions", str(divisions)))
            self.divisions = divisions
        self._fill(measure, length * divisions)
        if not len(self.part) and self.staves == 2:
            attributes = self._attributes(measure)
            _set_attribute(attributes, _element("staves", "2"))
            _set_attribute(attributes, _element("part-symbol", "brace"))
        if meter and meter != self.meter:
            _set_attribute(self._attributes(measure), _time_element(meter))
            self.meter = meter
        for attributes in measure.findall("attributes"):
            if not len(attributes):
                measure.remove(attributes)
        self.part.append(measure)

    def _attributes(self, measure: ET.Element) -> ET.Element:
        """The attributes at the start of the measure, made if there are none."""
        if not len(measure) or measure[0].tag != "attributes":
            measure.insert(0, ET.Element("attributes"))
        return measure[0]

    def _clean_attributes(self, measure: ET.Element) -> None:
        for attributes in measure.findall("attributes"):
            for child in list(attributes):
                if child.tag in ("time", "staves", "part-symbol", "measure-style"):
                    attributes.remove(child)
                elif child.tag == "divisions":
                    self.source_divisions = int(child.text or 1)
                    attributes.remove(child)
                elif child.tag == "key":
                    if _signature(child) == self.key:
                        attributes.remove(child)
                    self.key = _signature(child)
                elif child.tag == "clef":
                    staff = child.get("number", "1")
                    if _signature(child) == self.clefs.get(staff):
                        attributes.remove(child)
                    self.clefs[staff] = _signature(child)

    def _fill(self, measure: ET.Element, length: Fraction) -> None:
        """Rests for what is not played. A measure of nothing but rests lasts as long as the measure does."""
        duration = max(1, int(length))
        notes = measure.findall("note")
        if all(n.find("rest") is not None for n in notes):
            for el in list(measure):
                if el.tag in ("note", "backup", "forward"):
                    measure.remove(el)
            notes = []
        for staff in range(1, self.staves + 1):
            if any(n.findtext("staff", "1") == str(staff) for n in notes):
                continue
            content = [_rest(duration, staff)]
            if (position := _position(measure)) > 0:
                content.insert(0, _backup(position))
            ending = [i for i, el in enumerate(measure) if el.tag == "barline" and el.get("location") != "left"]
            at = ending[0] if ending else len(measure)
            for k, el in enumerate(content):
                measure.insert(at + k, el)


def _first_measure_length(system: System, meter: Meter | None) -> Fraction | None:
    """The length of a pickup: what is played in the first measure, if every staff is short."""
    ends = []
    for read in system.all_reads:
        if read.measures and read.measures[0].find("note/pitch") is not None:
            divisions = int(read.measures[0].findtext("attributes/divisions") or 1)
            end = position = 0
            for el in read.measures[0]:
                position += _position([el])
                end = max(end, position)
            ends.append(Fraction(end, divisions))
    return max(ends) if ends and meter and max(ends) < meter_length(meter) else None


def merge(systems: list[System], instruments: list[dict[str, Any]], title: str = "") -> tuple[ET.Element, dict[str, Any]]:
    """Build the score. Returns it with a report of everything that was not straightforward."""
    extra = max((len(s.unplaced) for s in systems), default=0)
    parts = [*instruments, *({"name": f"Unplaced staff {k + 1}", "staves": 2, "labels": []} for k in range(extra))]
    for k in range(extra):
        two = any(
            n.findtext("staff") == "2"
            for s in systems
            if len(s.unplaced) > k
            for m in s.unplaced[k][1].measures
            for n in m.findall("note")
        )
        parts[len(instruments) + k]["staves"] = 2 if two else 1

    writers = [PartWriter(f"P{i + 1}", part["staves"]) for i, part in enumerate(parts)]
    report: dict[str, Any] = {
        "instruments": [p["name"] for p in instruments],
        "systems": len(systems),
        "staves": sum(len(s.all_reads) + len(s.unread) for s in systems),
        "unplaced": [],
        "unread": [],
        "by_position": [],
        "uneven": [],
    }
    meter: Meter | None = None
    done = 0
    for system in systems:
        count = measure_count(system)
        if count == 0:
            report["unread"].append({"page": system.page, "system": system.number, "part": None, "measures": []})
            continue
        meters = vote_meters(system, count, meter)
        ends = _common_ends(system, count)
        pickup = _first_measure_length(system, meters[0]) if done == 0 else None
        where = {"page": system.page, "system": system.number}
        span = list(range(done + 1, done + count + 1))
        shown: dict[int, Read] = dict(system.reads)
        for k, (staff, read) in enumerate(system.unplaced):
            shown[len(instruments) + k] = read
            report["unplaced"].append({**where, "staff": staff, "part": parts[len(instruments) + k]["name"], "measures": span})
        for index in system.unread:
            report["unread"].append({**where, "part": parts[index]["name"], "measures": span})
        for index in system.by_position:
            report["by_position"].append({**where, "part": parts[index]["name"], "measures": span})
        for index, writer in enumerate(writers):
            read = shown.get(index)
            if read is None:
                places: list[list[ET.Element]] = [[] for _ in range(count)]
            else:
                places, doubt = fit_measures(read, count, ends)
                if doubt:
                    report["uneven"].append(
                        {
                            **where,
                            "part": parts[index]["name"],
                            "found": len(read.measures),
                            "expected": count,
                            "measures": [done + k + 1 for k in doubt],
                        }
                    )
            for k, measures in enumerate(places):
                writer.add(measures, meters[k], pickup if done + k == 0 else None)
        meter = meters[-1]
        done += count

    root = ET.Element("score-partwise", {"version": "4.0"})
    if title:
        work = ET.SubElement(root, "work")
        work.append(_element("work-title", title))
    part_list = ET.SubElement(root, "part-list")
    for i, part in enumerate(parts):
        score_part = ET.SubElement(part_list, "score-part", {"id": f"P{i + 1}"})
        score_part.append(_element("part-name", part["name"]))
        short = min(part["labels"], key=len, default="")
        if short and short != part["name"]:
            score_part.append(_element("part-abbreviation", short))
    root.extend(writer.part for writer in writers)
    return root, report
