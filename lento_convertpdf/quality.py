"""Judge a transcription without a reference: what looks wrong in the result itself?

Two kinds of evidence are combined, because neither is enough alone (see docs/convertpdf-accuracy.md):
- homr's own symbol probabilities, which catch garbled staves but not confident mistakes;
- musical consistency (measure lengths, key changes that undo themselves, empty measures, lost layout).

The estimate is the share of measures with nothing suspicious. It is a screening figure, not a measured accuracy:
wrong notes in a measure that adds up are invisible to it.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from .instruments import unusual_clef, written_range
from .repair import RepairReport, repair_spanners
from .rests import even_out_parts

CHECKS_VERSION = 1  # raise when a check is added that scores converted earlier should go through (see recheck)
REVIEW_BELOW = 0.95  # recommended baseline: below this, flag the export for review
UNRELIABLE_BELOW = 0.80  # below this, or when the layout was lost, do not rely on the export

LOW_SYMBOL = 0.70  # homr's probabilities top out near 0.91, so 0.70 is clearly unsure
LOW_SHARE = 0.015  # share of unsure symbols in a staff line that makes the line suspicious
MAX_UNPLACED = 0.05  # share of staves without an instrument that makes a full score unreliable
MAX_KEY_EXCURSION = 8  # a key change undone within this many measures is usually a missed key signature


@dataclass
class QualityReport:
    estimate: float
    level: str  # "good" | "review" | "unreliable"
    measures: int
    suspicious: dict[int, list[str]] = field(default_factory=dict)  # measure number -> reasons
    problems: list[str] = field(default_factory=list)  # whole-score problems
    symbol_confidence: float | None = None  # None when homr's probabilities were not available
    review_below: float = REVIEW_BELOW
    by_system: bool = False  # a full score, read system by system
    instruments: dict[str, float] = field(default_factory=dict)  # the same estimate per instrument, full scores only
    repairs: dict[str, Any] = field(default_factory=dict)  # broken marks left out before saving (repair.py)

    @property
    def summary(self) -> str:
        label = {"good": "OK", "review": "REVIEW", "unreliable": "UNRELIABLE"}[self.level]
        text = f"{label}: {self.estimate:.0%} of {'notes' if self.by_system else 'measures'} look consistent"
        if self.suspicious:
            text += f", check m. {_ranges(sorted(self.suspicious))}"
        parts = [text, *self.problems]
        if self.by_system:
            parts.append(f"read system by system, {len(self.instruments)} instruments")
            weak = [n for n, share in sorted(self.instruments.items(), key=lambda i: i[1]) if share < self.review_below]
            if weak:
                parts.append(f"weakest: {', '.join(f'{n} {self.instruments[n]:.0%}' for n in weak[:3])}")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "estimate": round(self.estimate, 4),
            "review_below": self.review_below,
            "unreliable_below": UNRELIABLE_BELOW,
            "measures": self.measures,
            "symbol_confidence": self.symbol_confidence,
            "problems": self.problems,
            "read_by_system": self.by_system,
            "instruments": {name: round(share, 4) for name, share in self.instruments.items()},
            "suspicious_measures": {str(k): v for k, v in sorted(self.suspicious.items())},
            "repairs": self.repairs,
            "summary": self.summary,
        }


def _ranges(numbers: list[int], limit: int = 12) -> str:
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    text = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs[:limit])
    return text + (f" and {len(runs) - limit} more places" if len(runs) > limit else "")


def _measure_end(measure: ET.Element, divisions: Fraction) -> Fraction:
    """Length of the measure in quarters: the furthest point any voice reaches."""
    position = end = Fraction(0)
    for el in measure:
        length = Fraction(el.findtext("duration") or 0) / divisions
        if el.tag == "backup":
            position -= length
        elif el.tag == "forward" or (el.tag == "note" and el.find("chord") is None and el.find("grace") is None):
            position += length
            end = max(end, position)
    return end


def _check_part(part: ET.Element, suspicious: dict[int, list[str]]) -> None:
    divisions, expected = Fraction(1), None
    keys: list[tuple[int, int]] = []
    measures = part.findall("measure")
    for number, measure in enumerate(measures, start=1):
        for attributes in measure.findall("attributes"):
            if attributes.findtext("divisions"):
                divisions = Fraction(attributes.findtext("divisions"))
            beats, beat_type = attributes.findtext("time/beats"), attributes.findtext("time/beat-type")
            if beats and beat_type:
                expected = sum(Fraction(b) for b in beats.split("+")) * 4 / Fraction(beat_type)
            fifths = attributes.findtext("key/fifths")
            if fifths is not None and (not keys or keys[-1][1] != int(fifths)):
                keys.append((number, int(fifths)))

        def flag(reason: str, at: int = number) -> None:
            reasons = suspicious.setdefault(at, [])
            if reason not in reasons:
                reasons.append(reason)

        if measure.find("note") is None:
            flag("empty")
            continue
        # A whole-measure rest fills the measure whatever its written value
        notes = measure.findall("note")
        if all(n.find("rest") is not None for n in notes):
            continue
        end = _measure_end(measure, divisions)
        if expected and abs(end - expected) > Fraction(1, 32):
            edge = number in (1, len(measures)) and end < expected  # pickup or cut-off last measure
            if not edge:
                flag("too long" if end > expected else "too short")

    for (start, fifths), (back, returned), before in zip(keys[1:], keys[2:], keys, strict=False):
        if returned == before[1] and fifths != before[1] and back - start <= MAX_KEY_EXCURSION:
            for at in range(start, back):
                suspicious.setdefault(at, []).append("key signature changes and changes back")
    if len(keys) >= 2:
        start, fifths = keys[-1]
        if len(measures) - start < MAX_KEY_EXCURSION and fifths == 0 and keys[-2][1] != 0:
            for at in range(start, len(measures) + 1):
                suspicious.setdefault(at, []).append("key signature disappears at the end")


def check_score(
    xml_path: Path, trace: dict[str, Any] | None = None, review_below: float = REVIEW_BELOW
) -> QualityReport:
    """Repair broken slurs, ties and lines in a fresh transcription (in place), then assess it. Every engine's
    output goes through this before it is saved."""
    repairs = repair_spanners(xml_path)
    report = with_repairs(assess(xml_path, trace, review_below), repairs)
    padded = even_out_parts(xml_path)  # after assess, which reports the parts' lengths
    if padded:
        report.problems.append(_padded(padded))
    return report


def _padded(added: dict[str, int]) -> str:
    return "filled the end of " + ", ".join(f"{name or 'a part'} with {n} empty measures" for name, n in added.items()) + (
        " so the whole score shows"
    )


def with_repairs(report: QualityReport, repairs: RepairReport) -> QualityReport:
    """Add what repair_spanners left out to a report. Ties and octave lines change what is played or where the notes
    are drawn, so they (or many broken slurs) put an otherwise good score up for review."""
    if not repairs.fixed:
        return report
    report.repairs = repairs.to_dict()
    report.problems.append(repairs.summary)
    if repairs.worth_review and report.level == "good":
        report.level = "review"
    return report


def assess(
    xml_path: Path, trace: dict[str, Any] | None = None, review_below: float = REVIEW_BELOW
) -> QualityReport:
    """Assess a transcription. trace is what homr_bridge recorded, if it could."""
    root = ET.parse(xml_path).getroot()
    parts = root.findall("part")
    counts = [len(p.findall("measure")) for p in parts]
    total = max(counts, default=0)
    suspicious: dict[int, list[str]] = {}
    problems: list[str] = []
    by_system = (trace or {}).get("by_system")
    names = [p.findtext("part-name") or p.get("id", "") for p in root.findall("part-list/score-part")]
    instruments: dict[str, float] = {}
    all_notes = good_notes = 0
    for k, part in enumerate(parts):
        own: dict[int, list[str]] = {}
        _check_part(part, own)
        _check_range(part, names[k] if k < len(names) else "", own)
        if by_system:
            name = names[k] if k < len(names) else part.get("id", "")
            _check_reading(by_system, name, own)
            _check_clefs(part, name, own)
            if name in by_system["instruments"]:  # not the extra parts for unplaced staves
                instruments[name] = 1 - len(own) / total if total else 0.0
            for at, measure in enumerate(part.findall("measure"), start=1):
                notes = len(measure.findall("note/pitch"))
                all_notes += notes
                good_notes += notes if at not in own else 0
            own = {at: [f"{name}: {reason}" for reason in reasons] for at, reasons in own.items()}
        for at, reasons in own.items():
            known = suspicious.setdefault(at, [])
            known += [r for r in reasons if r not in known]

    lost_layout = unplaced = False
    if by_system:
        lost = by_system["unplaced"]
        unplaced = bool(lost or by_system["unread"])
        lost_layout = len(lost) > MAX_UNPLACED * max(1, by_system["staves"])
        for key, text in (
            ("unplaced", "{} could not be matched with an instrument and {} in extra parts"),
            ("unread", "{} could not be read"),
            ("by_position", "{} had no label and {} placed by position"),
        ):
            if entries := by_system[key]:
                count = f"{len(entries)} {'staff' if len(entries) == 1 else 'staves'}"
                verb = {"unplaced": "is" if len(entries) == 1 else "are", "by_position": "was" if len(entries) == 1 else "were"}
                where = _ranges(sorted({e["page"] for e in entries}))
                problems.append(f"{text.format(count, verb.get(key, ''))} (page {where})")
    elif (trace or {}).get("layout_changed"):
        problems.append("instruments come and go, but there were too few labels to tell them apart")
    if len(set(counts)) > 1:
        lost_layout = True
        problems.append(f"parts differ in length ({min(counts)} to {max(counts)} measures)")

    confidence: float | None = None
    if trace and not trace.get("error"):
        pages = trace.get("pages", [])
        flattened = [p["page"] for p in pages if p.get("flattened")]
        if flattened:
            lost_layout = True
            problems.append(f"instruments were merged on page {_ranges(flattened)} (staves come and go)")
        if len({p["parts"] for p in pages if p.get("parts")}) > 1:
            lost_layout = True
            problems.append("the number of instruments differs from page to page")
        values = [c for p in pages for read in p.get("reads", []) for c in read]
        if values:
            confidence = round(sum(values) / len(values), 4)
        weak = [p["page"] for p in pages if any(_unsure(read) for read in p.get("reads", []))]
        if weak:
            problems.append(f"homr was unsure about staves on page {_ranges(weak)}")
        share = _unsure_share(pages)
    else:
        share = 0.0

    consistent = 1 - len([m for m in suspicious if m <= total]) / total if total else 0.0
    if by_system:
        # With many instruments nearly every measure has something in it somewhere; what counts is how much
        consistent = good_notes / all_notes if all_notes else 0.0
    # An unsure staff line cannot be tied to exact measures, so it lowers the estimate as a whole
    estimate = max(0.0, consistent * (1 - share))
    if lost_layout or estimate < UNRELIABLE_BELOW:
        level = "unreliable"
    elif unplaced or estimate < review_below:
        level = "review"
    else:
        level = "good"
    return QualityReport(
        estimate, level, total, suspicious, problems, confidence, review_below, bool(by_system), instruments
    )


_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi(pitch: ET.Element) -> int | None:
    try:
        alter = round(float(pitch.findtext("alter") or 0))
        return 12 * (int(pitch.findtext("octave") or "") + 1) + _STEPS[(pitch.findtext("step") or "").strip()] + alter
    except (KeyError, ValueError):
        return None


def _check_range(part: ET.Element, name: str, own: dict[int, list[str]]) -> None:
    """Notes the instrument can't play: usually a misread clef, a missed octave line or a misread ledger line."""
    limits = written_range(name)
    if not limits:
        return
    low, high = limits
    instrument = name.strip().lower() or "this instrument"
    for at, measure in enumerate(part.findall("measure"), start=1):
        found = set()
        for pitch in measure.iter("pitch"):
            midi = _midi(pitch)
            if midi is not None and midi < low:
                found.add(f"notes too low for {instrument}")
            elif midi is not None and midi > high:
                found.add(f"notes too high for {instrument}")
        for reason in sorted(found):
            if reason not in own.setdefault(at, []):
                own[at].append(reason)


def _check_clefs(part: ET.Element, name: str, own: dict[int, list[str]]) -> None:
    unusual: dict[str, str] = {}
    for at, measure in enumerate(part.findall("measure"), start=1):
        for clef in measure.findall("attributes/clef"):
            sign = f"{clef.findtext('sign')}{clef.findtext('line')}"
            unusual.pop(clef.get("number", "1"), None)
            if unusual_clef(name, sign):
                unusual[clef.get("number", "1")] = sign
        if unusual and measure.find("note/pitch") is not None:
            own.setdefault(at, []).append(f"unusual clef {', '.join(unusual.values())}, the notes may be too high or low")


def _check_reading(by_system: dict[str, Any], name: str, own: dict[int, list[str]]) -> None:
    """What was already doubtful when the systems were joined."""
    for key, reason in (
        ("uneven", "barlines do not match the other instruments"),
        ("unread", "staff could not be read"),
        ("unplaced", "staff could not be matched with an instrument"),
    ):
        for entry in by_system[key]:
            if entry["part"] == name:
                for at in entry["measures"]:
                    own.setdefault(at, []).append(reason)


def _unsure(read: list[float]) -> bool:
    return bool(read) and sum(c < LOW_SYMBOL for c in read) / len(read) > LOW_SHARE


def _unsure_share(pages: list[dict[str, Any]]) -> float:
    """Share of all symbols homr was unsure about."""
    values = [c for p in pages for read in p.get("reads", []) for c in read]
    return sum(c < LOW_SYMBOL for c in values) / len(values) if values else 0.0


def recheck(xml_path: Path) -> list[str]:
    """Put a score converted before today's checks through them: repair broken slurs, ties and lines in place, and
    look for notes the instrument can't play. Its quality report (name.quality.json) gets the findings as
    "recheck_notes", and a score that was fine but now needs a look goes up for review. Returns the findings."""
    repairs = repair_spanners(xml_path)
    root = ET.parse(xml_path).getroot()
    names = [p.findtext("part-name") or "" for p in root.findall("part-list/score-part")]
    found: dict[str, list[int]] = {}
    for k, part in enumerate(root.findall("part")):
        own: dict[int, list[str]] = {}
        _check_range(part, names[k] if k < len(names) else "", own)
        for at, reasons in own.items():
            for reason in reasons:
                found.setdefault(reason, []).append(at)
    path = xml_path.with_suffix(".quality.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    earlier = (data.get("repairs") or {}).get("summary", "")
    if repairs.fixed:
        notes = [repairs.summary]
    else:  # repaired by an earlier recheck (or at conversion, which already says so in "problems")
        notes = [earlier] if earlier and earlier not in data.get("problems", []) else []
    notes += [f"{reason} in m. {_ranges(sorted(set(at)))}" for reason, at in sorted(found.items())]
    padded = even_out_parts(xml_path)
    if padded:
        notes.append(_padded(padded))
    elif data.get("padded"):
        notes.append(data["padded"])
    level = data.get("level") or "good"
    if (repairs.worth_review or found or padded) and level == "good":
        level = "review"
    if not data and level == "good":
        return notes  # nothing worth a report: a good score has none
    data.update(level=level, recheck_notes=notes, checks_version=CHECKS_VERSION)
    if repairs.fixed:
        data["repairs"] = repairs.to_dict()
    if padded:
        data["padded"] = _padded(padded)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(data, indent=2), encoding="utf-8")
    partial.replace(path)
    return notes
