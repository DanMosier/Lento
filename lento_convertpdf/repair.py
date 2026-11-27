"""Find and repair marks that start and never end (or end and never start) in a converted score.

homr writes slurs, ties, octave lines (8va) and other lines as separate start and stop marks, and says nothing when
it misses one half. The score renderer in the app then has to cope with a slur that never ends, a stop with no start,
or a slur whose end comes before its start, and one such slur can leave the whole page blank. So every converted
score goes through this check before it is saved:

- slurs: a start is paired with the next stop on the same staff, later in the music; a slur that is started again
  before it ends, never ends, ends before it starts or starts and ends on one note is left out, and so is a stop
  with no start. The slurs that are kept are renumbered so that two slurs open at the same time never share a
  number, which is how readers tell them apart.
- ties: kept only between two notes of the same pitch, on the same staff, where the second starts as the first
  ends. Ties change what is played, so a broken one is also worth a look in Review.
- octave lines, wedges (hairpins), pedal marks, brackets and dashes: paired like slurs; a line that never ends is
  left out, so the notes after it are no longer drawn an octave away.
- tuplet brackets: a start with no stop in the same voice, or a stop with no start, is left out. The notes keep
  their tuplet timing (time-modification), only the bracket goes.
- volta brackets (1st/2nd endings): a start with no end is closed at the end of its measure.

Nothing here touches pitches or rhythms. It is a single pass over the file, a fraction of a second even for a
long score.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

MAX_SLUR_MEASURES = 16  # a slur longer than this is a misread, not a phrase
DIRECTION_LINES = ("octave-shift", "wedge", "pedal", "bracket", "dashes")
LINE_NAMES = {
    "slur": ("slur", "slurs"),
    "tie": ("tie", "ties"),
    "octave-shift": ("octave line (8va)", "octave lines (8va)"),
    "wedge": ("hairpin", "hairpins"),
    "pedal": ("pedal mark", "pedal marks"),
    "bracket": ("bracket line", "bracket lines"),
    "dashes": ("dashed line", "dashed lines"),
    "tuplet": ("tuplet bracket", "tuplet brackets"),
    "ending": ("volta bracket", "volta brackets"),
}


@dataclass
class RepairReport:
    """What was wrong, by kind of mark: how many were left out (or closed, for volta brackets)."""

    fixed: Counter[str] = field(default_factory=Counter)
    measures: dict[str, list[int]] = field(default_factory=dict)  # kind -> measure numbers where something was fixed
    kept: Counter[str] = field(default_factory=Counter)  # how many of each kind were fine
    renumbered: int = 0  # slurs given another number so that open slurs never share one (not a problem to report)

    def add(self, kind: str, measure: int) -> None:
        self.fixed[kind] += 1
        at = self.measures.setdefault(kind, [])
        if measure not in at:
            at.append(measure)

    @property
    def changed(self) -> bool:
        """Whether the file needs saving."""
        return bool(self.fixed) or self.renumbered > 0

    @property
    def summary(self) -> str:
        """'left out 116 slurs and 2 octave lines (8va) that did not end', or ''."""
        out = [_count(kind, n) for kind, n in self.fixed.items() if kind != "ending"]
        text = f"left out {_join(out)} that did not start or end properly" if out else ""
        if self.fixed["ending"]:
            closed = f"closed {_count('ending', self.fixed['ending'])} that did not end"
            text = f"{text}; {closed}" if text else closed
        return text

    @property
    def worth_review(self) -> bool:
        """Whether a person should look: anything that changes what is played or where notes are drawn, or many
        slurs (a sign the reading was poor in places)."""
        slurs = self.fixed["slur"]
        many_slurs = slurs >= 10 and slurs > 0.02 * (slurs + self.kept["slur"])
        return bool(self.fixed["tie"] or self.fixed["octave-shift"] or many_slurs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": dict(self.fixed),
            "measures": {k: sorted(v)[:50] for k, v in self.measures.items()},
            "summary": self.summary,
        }


def _count(kind: str, n: int) -> str:
    one, many = LINE_NAMES.get(kind, (kind, kind + "s"))
    return f"{n} {one if n == 1 else many}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


@dataclass
class _Note:
    el: ET.Element
    measure: int  # position of the measure in the part, from 1
    onset: Fraction  # quarters from the start of the part
    end: Fraction
    doc: int  # position in the file, which is the order readers go by
    staff: str
    voice: str
    grace: bool


def _walk(part: ET.Element) -> tuple[list[_Note], list[tuple[ET.Element, ET.Element, int, Fraction, int]]]:
    """Every note of a part with its place in time, and every <direction> with (measure, onset, doc)."""
    notes: list[_Note] = []
    directions: list[tuple[ET.Element, ET.Element, int, Fraction, int]] = []
    divisions = Fraction(1)
    start = Fraction(0)  # where this measure starts, in quarters
    doc = 0
    for number, measure in enumerate(part.findall("measure"), start=1):
        position = last = longest = Fraction(0)
        for el in measure:
            doc += 1
            if el.tag == "attributes" and el.findtext("divisions"):
                try:
                    divisions = Fraction(el.findtext("divisions") or 1) or Fraction(1)
                except (ValueError, ZeroDivisionError):
                    pass
            try:
                length = Fraction(el.findtext("duration") or 0) / divisions
            except (ValueError, ZeroDivisionError):
                length = Fraction(0)
            if el.tag == "backup":
                position -= length
            elif el.tag == "forward":
                position += length
            elif el.tag == "direction":
                directions.append((measure, el, number, start + position, doc))
            elif el.tag == "note":
                grace = el.find("grace") is not None
                if el.find("chord") is None:
                    last = position
                    if not grace:
                        position += length
                onset = start + last
                notes.append(
                    _Note(el, number, onset, onset + (0 if grace else length), doc,
                          (el.findtext("staff") or "1").strip(), (el.findtext("voice") or "1").strip(), grace)
                )
            longest = max(longest, position)
        start += longest
    return notes, directions


def _pitch(note: ET.Element) -> tuple[str, float, str] | None:
    p = note.find("pitch")
    if p is None:
        return None
    try:
        alter = float(p.findtext("alter") or 0)
    except ValueError:
        alter = 0.0
    return (p.findtext("step") or "", alter, p.findtext("octave") or "")


def _remove(note: ET.Element, parent: ET.Element, child: ET.Element) -> None:
    """Take a mark off a note; a <notations> left empty goes too."""
    if child in parent:
        parent.remove(child)
    if parent.tag == "notations" and len(parent) == 0 and parent in note:
        note.remove(parent)


def _fix_slurs(notes: list[_Note], report: RepairReport) -> None:
    events: list[tuple[tuple[Any, ...], _Note, ET.Element, ET.Element]] = []
    for n in notes:
        for notations in n.el.findall("notations"):
            for s in notations.findall("slur"):
                kind = s.get("type")
                order = 0 if kind == "stop" else 2 if kind == "start" else 1
                events.append(((n.onset, not n.grace, order, n.doc), n, notations, s))
    events.sort(key=lambda e: e[0])
    open_: dict[tuple[str, str], tuple[_Note, ET.Element, ET.Element]] = {}
    pairs: list[tuple[_Note, ET.Element, _Note, ET.Element]] = []
    drop: list[tuple[_Note, ET.Element, ET.Element, bool]] = []  # (..., counts as a broken slur)
    for _, n, notations, s in events:
        key = (n.staff, s.get("number", "1"))
        kind = s.get("type")
        if kind == "continue":
            continue  # a bend point: harmless
        if kind == "start":
            if key in open_:
                drop.append((*open_.pop(key), True))
            open_[key] = (n, notations, s)
        elif kind == "stop":
            begun = open_.pop(key, None)
            if begun is None:
                drop.append((n, notations, s, True))
                continue
            first = begun[0]
            if first.doc < n.doc and (first.onset, not first.grace) < (n.onset, not n.grace) and n.measure - first.measure <= MAX_SLUR_MEASURES:
                pairs.append((first, begun[2], n, s))
            else:
                drop += [(*begun, True), (n, notations, s, False)]
    drop += [(*o, True) for o in open_.values()]
    for n, notations, s, counts in drop:
        _remove(n.el, notations, s)
        if counts:
            report.add("slur", n.measure)
    report.kept["slur"] += len(pairs)
    report.renumbered += _renumber(pairs)


def _renumber(pairs: list[tuple[_Note, ET.Element, _Note, ET.Element]]) -> int:
    """Give slurs that are open at the same point of the file different numbers (readers go in file order)."""
    busy: list[int] = []  # file position where each number becomes free again
    changed = 0
    for first, start, last, stop in sorted(pairs, key=lambda p: p[0].doc):
        for k, free_at in enumerate(busy):
            if free_at < first.doc:
                busy[k] = last.doc
                break
        else:
            busy.append(last.doc)
            k = len(busy) - 1
        number = str(min(k + 1, 16))
        if start.get("number", "1") != number or stop.get("number", "1") != number:
            changed += 1
        start.set("number", number)
        stop.set("number", number)
    return changed


def _fix_ties(notes: list[_Note], report: RepairReport) -> None:
    # The next note of the same pitch on the same staff. Not "the note that starts where this one ends": a misread
    # rhythm elsewhere in the measure moves that point, and the tie is still right.
    following: dict[int, _Note] = {}
    last: dict[tuple[str, Any], list[_Note]] = {}
    for n in sorted(notes, key=lambda n: (n.onset, n.doc)):
        pitch = _pitch(n.el)
        if not pitch or n.grace:
            continue
        waiting = last.setdefault((n.staff, pitch), [])
        for m in [m for m in waiting if m.onset < n.onset]:
            following[id(m.el)] = n
            waiting.remove(m)
        waiting.append(n)

    def marks(n: _Note, kind: str) -> list[tuple[ET.Element, ET.Element]]:
        found = [(n.el, t) for t in n.el.findall("tie") if t.get("type") == kind]
        for notations in n.el.findall("notations"):
            found += [(notations, t) for t in notations.findall("tied") if t.get("type") == kind]
        return found

    keep_stop: set[int] = set()
    for n in notes:
        starts = marks(n, "start")
        if not starts:
            continue
        partner = following.get(id(n.el))
        if partner is None or partner.measure > n.measure + 1 or not marks(partner, "stop"):
            for parent, t in starts:
                _remove(n.el, parent, t)
            report.add("tie", n.measure)
        else:
            keep_stop.add(id(partner.el))
            report.kept["tie"] += 1
    for n in notes:
        stops = marks(n, "stop")
        if stops and id(n.el) not in keep_stop:
            for parent, t in stops:
                _remove(n.el, parent, t)
            report.add("tie", n.measure)


def _fix_tuplets(notes: list[_Note], report: RepairReport) -> None:
    open_: dict[tuple[str, str, str], tuple[_Note, ET.Element, ET.Element]] = {}

    def drop(n: _Note, parent: ET.Element, mark: ET.Element) -> None:
        _remove(n.el, parent, mark)
        report.add("tuplet", n.measure)

    for n in sorted(notes, key=lambda n: n.doc):
        if n.el.find("chord") is not None:
            continue  # homr repeats the mark on every note of a chord; the chord's first note is the one that counts
        for notations in n.el.findall("notations"):
            for t in notations.findall("tuplet"):
                key = (n.staff, n.voice, t.get("number", "1"))
                if t.get("type") == "start":
                    if key in open_:
                        drop(*open_.pop(key))
                    open_[key] = (n, notations, t)
                elif t.get("type") == "stop":
                    begun = open_.pop(key, None)
                    if begun is None:
                        drop(n, notations, t)
                    elif n.measure - begun[0].measure > 1:  # a tuplet spans a beat or two, not measures
                        drop(*begun)
                        _remove(n.el, notations, t)
                    else:
                        report.kept["tuplet"] += 1
    for begun in open_.values():
        drop(*begun)


def _fix_direction_lines(
    directions: list[tuple[ET.Element, ET.Element, int, Fraction, int]], report: RepairReport
) -> None:
    events = []
    for measure, direction, number, onset, doc in directions:
        staff = (direction.findtext("staff") or "1").strip()
        for dt in direction.findall("direction-type"):
            for mark in dt:
                if mark.tag in DIRECTION_LINES:
                    events.append((onset, doc, measure, direction, dt, mark, number, staff))
    events.sort(key=lambda e: (e[0], e[1]))
    open_: dict[tuple[str, str, str], tuple] = {}
    drop: list[tuple] = []

    def starts(mark: ET.Element) -> bool:
        kind = mark.get("type", "")
        if mark.tag == "pedal":
            return kind in ("start", "sostenuto")
        if mark.tag == "wedge":
            return kind in ("crescendo", "diminuendo")
        if mark.tag == "octave-shift":
            return kind in ("up", "down")
        return kind == "start"

    for event in events:
        mark = event[5]
        kind = mark.get("type", "")
        if mark.tag == "pedal" and kind in ("change", "continue", "resume", "discontinue"):
            continue
        key = (mark.tag, event[7], mark.get("number", "1"))
        if starts(mark):
            if key in open_:
                drop.append((*open_.pop(key), True))
            open_[key] = event
        elif kind == "stop":
            begun = open_.pop(key, None)
            if begun is None:
                drop.append((*event, True))
            elif begun[1] > event[1]:
                drop += [(*begun, True), (*event, False)]
            else:
                report.kept[mark.tag] += 1
    # A pedal mark that never ends is how many scores print "Ped." with no release: harmless to the reader,
    # unlike an octave line or hairpin that never ends.
    drop += [(*e, True) for e in open_.values() if e[5].tag != "pedal"]
    for _, _, measure, direction, dt, mark, number, _, counts in drop:
        if mark in dt:
            dt.remove(mark)
        if counts:
            report.add(mark.tag, number)
        if len(dt) == 0 and dt in direction:
            direction.remove(dt)
        if direction.find("direction-type") is None and direction in measure:
            measure.remove(direction)


def _fix_endings(part: ET.Element, report: RepairReport) -> None:
    """A volta bracket (1st/2nd ending) that never ends is closed at the end of the measure it starts in."""
    measures = part.findall("measure")
    for number, measure in enumerate(measures, start=1):
        for ending in [e for b in measure.findall("barline") for e in b.findall("ending") if e.get("type") == "start"]:
            closed = False
            for k, later in enumerate(measures[number - 1 : number - 1 + 8]):
                marks = [e for b in later.findall("barline") for e in b.findall("ending") if e is not ending]
                if any(e.get("type") in ("stop", "discontinue") and e.get("number", "") == ending.get("number", "")
                       for e in marks):
                    closed = True
                    break
                if k and any(e.get("type") == "start" for e in marks):
                    break  # the next bracket begins: this one was never closed
            if closed:
                continue
            right = next((b for b in measure.findall("barline") if b.get("location") == "right"), None)
            if right is None:
                right = ET.SubElement(measure, "barline", location="right")
            if right.find("ending") is None:
                # MusicXML wants <ending> after <bar-style> and before <repeat>
                at = 1 if right.find("bar-style") is not None else 0
                right.insert(at, ET.Element("ending", number=ending.get("number", "1"), type="discontinue"))
                report.add("ending", number)


def repair_tree(root: ET.Element) -> RepairReport:
    report = RepairReport()
    for part in root.findall("part"):
        notes, directions = _walk(part)
        _fix_slurs(notes, report)
        _fix_ties(notes, report)
        _fix_tuplets(notes, report)
        _fix_direction_lines(directions, report)
        _fix_endings(part, report)
    for at in report.measures.values():
        at.sort()
    return report


def repair_spanners(xml_path: Path, write: bool = True) -> RepairReport:
    """Check a MusicXML file and, if anything was broken and write is set, save the repaired file in its place."""
    tree = ET.parse(xml_path)
    report = repair_tree(tree.getroot())
    if report.changed and write:
        partial = xml_path.with_name(xml_path.name + ".repair")
        tree.write(partial, encoding="UTF-8", xml_declaration=True)
        partial.replace(xml_path)
    return report
