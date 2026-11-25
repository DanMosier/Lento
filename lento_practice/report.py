"""Write an analysis as a summary, a table, JSON, and a colored copy of the score."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .analyze import (
    DOUBLE_STOP,
    IN_TUNE,
    MISSED,
    NOT_PLAYED,
    OUT_OF_TUNE,
    SCORE_SUSPECT,
    SLIGHTLY_OFF,
    WRONG_NOTE,
    Analysis,
    NoteResult,
)

COLORS = {
    IN_TUNE: "#2E9E44",
    SLIGHTLY_OFF: "#D99A00",
    OUT_OF_TUNE: "#D0342C",
    WRONG_NOTE: "#D0342C",
    MISSED: "#8E44AD",
    SCORE_SUSPECT: "#1F6FD0",
    DOUBLE_STOP: "#7F8C8D",
}
SEVERITY = {SLIGHTLY_OFF: 1, OUT_OF_TUNE: 2, WRONG_NOTE: 3, MISSED: 3}
LABELS = {
    IN_TUNE: "in tune",
    SLIGHTLY_OFF: "slightly off",
    OUT_OF_TUNE: "out of tune",
    WRONG_NOTE: "wrong note",
    MISSED: "missed",
    SCORE_SUSPECT: "score may be wrong",
    DOUBLE_STOP: "double stop, not checked",
    NOT_PLAYED: "not in the recording",
}


def label(r: NoteResult) -> str:
    """Short text shown under the note in the colored score."""
    parts = []
    if r.status in (SLIGHTLY_OFF, OUT_OF_TUNE) and r.cents is not None:
        parts.append(f"{r.cents:+.0f}")
    elif r.status == WRONG_NOTE:
        parts.append(f"{r.heard}?")
    elif r.status == MISSED:
        parts.append("miss")
    elif r.status == SCORE_SUSPECT:
        parts.append("score?")
    if r.timing:
        parts.append(r.timing)
    return " ".join(parts)


def _describe(r: NoteResult) -> str:
    bits = []
    if r.status == WRONG_NOTE:
        bits.append(f"played {r.heard}")
    elif r.status in (SLIGHTLY_OFF, OUT_OF_TUNE) and r.cents is not None:
        bits.append(f"{abs(r.cents):.0f} cents {'sharp' if r.cents > 0 else 'flat'}")
    elif r.status == MISSED:
        bits.append("missed")
    if r.timing:
        bits.append(f"{abs(r.timing_ms):.0f} ms {r.timing}")
    return f"{r.written} {' and '.join(bits)}"


def problem_spots(analysis: Analysis, limit: int = 3) -> list[dict]:
    """The worst stretches of one or two measures, with a suggested loop."""
    score = analysis.score
    per_measure: dict[int, float] = {}
    for r in analysis.played:
        if r.note is None:
            continue
        s = SEVERITY.get(r.status, 0) + (1 if r.timing else 0)
        if s:
            per_measure[r.note.measure_index] = per_measure.get(r.note.measure_index, 0) + s
    spots = []
    taken: set[int] = set()
    for m, _ in sorted(per_measure.items(), key=lambda kv: (-kv[1], kv[0])):
        if m in taken:
            continue
        nxt = m + 1 if per_measure.get(m + 1, 0) > 0 and m + 1 not in taken else m
        taken.update({m, nxt})
        rs = [r for r in analysis.played if r.note and m <= r.note.measure_index <= nxt and (SEVERITY.get(r.status) or r.timing)]
        tempo = analysis.tempo_bpm
        loop_bpm = max(40, int(round(tempo * 0.75 / 2) * 2)) if tempo else None
        spots.append(
            {
                "from_measure": score.measures[m],
                "to_measure": score.measures[nxt],
                "issues": sum(SEVERITY.get(r.status, 0) + (1 if r.timing else 0) for r in rs),
                "notes": [_describe(r) for r in rs],
                "loop_bpm": loop_bpm,
            }
        )
        if len(spots) == limit:
            break
    return spots


def summary_markdown(analysis: Analysis) -> str:
    a, s = analysis, analysis.settings
    played = a.played
    counts = {k: sum(1 for r in played if r.status == k) for k in LABELS}
    graded = sum(counts[k] for k in (IN_TUNE, SLIGHTLY_OFF, OUT_OF_TUNE, WRONG_NOTE, MISSED))
    pct = lambda n: f"{100 * n / graded:.0f}%" if graded else "-"
    early = sum(1 for r in played if r.timing == "early")
    late = sum(1 for r in played if r.timing == "late")

    lines = [f"# {a.score.title}: practice feedback", ""]
    span = f"measures {a.first_measure} to {a.last_measure}" if a.first_measure else "no measures"
    lines.append(f"Part: {a.score.part_name}. The recording covers {span}.")
    lines.append("")
    if a.tempo_bpm:
        written = a.score.tempos[0][1]
        drift = ""
        if a.tempo_start_bpm and a.tempo_end_bpm and abs(a.tempo_end_bpm - a.tempo_start_bpm) >= 0.06 * a.tempo_bpm:
            word = "sped up" if a.tempo_end_bpm > a.tempo_start_bpm else "slowed down"
            drift = f" You {word} from about {a.tempo_start_bpm:.0f} to {a.tempo_end_bpm:.0f}."
        lines.append(f"**Tempo:** about {a.tempo_bpm:.0f} quarter notes a minute (the score says {written:g}).{drift}")
    lines.append(
        f"**Pitch** ({graded} notes): {counts[IN_TUNE]} in tune ({pct(counts[IN_TUNE])}), "
        f"{counts[SLIGHTLY_OFF]} slightly off, {counts[OUT_OF_TUNE]} out of tune, "
        f"{counts[WRONG_NOTE]} wrong, {counts[MISSED]} missed."
    )
    lines.append(
        f"In tune means within {s.good_cents:g} cents; slightly off within {s.ok_cents:g}. Judged against A={s.a4:g}."
    )
    lines.append(f"**Timing:** {early} notes early and {late} late by more than {s.timing_ms:g} ms.")
    if counts[SCORE_SUSPECT]:
        lines.append(
            f"**Check the score:** {counts[SCORE_SUSPECT]} notes in a row were all off by the same interval. "
            "That usually means the score was misread (for example a tenor clef read as alto), so they are not counted against you."
        )
    if counts[DOUBLE_STOP]:
        lines.append(f"Double stops: only one note of each is measured ({counts[DOUBLE_STOP]} not checked).")
    lines.append("")

    spots = problem_spots(a)
    if spots:
        lines += ["## Spots to practise", ""]
        for i, sp in enumerate(spots, 1):
            where = sp["from_measure"] if sp["from_measure"] == sp["to_measure"] else f"{sp['from_measure']} to {sp['to_measure']}"
            loop = f" Loop it at {sp['loop_bpm']} bpm." if sp["loop_bpm"] else ""
            lines.append(f"{i}. **Measure {where}:** {'; '.join(sp['notes'][:6])}.{loop}")
        lines.append("")

    issues = [r for r in played if r.status not in (IN_TUNE, DOUBLE_STOP) or r.timing]
    if issues:
        lines += ["## Notes that need attention", "", "| Measure | Beat | Written | Heard | Cents | Timing |", "|---|---|---|---|---|---|"]
        for r in issues:
            cents = f"{r.cents:+.0f}" if r.cents is not None and r.status in (SLIGHTLY_OFF, OUT_OF_TUNE) else ""
            timing = f"{r.timing} {abs(r.timing_ms):.0f} ms" if r.timing else ""
            heard = r.heard or LABELS[r.status]
            lines.append(f"| {r.measure} | {r.beat_in_measure + 1:g} | {r.written} | {heard} | {cents} | {timing} |")
        lines.append("")
    if a.warnings:
        lines += ["## Notes on this analysis", ""] + [f"- {w}" for w in a.warnings] + [""]
    return "\n".join(lines)


def _insert_before(parent: ET.Element, child: ET.Element, before: tuple[str, ...]) -> None:
    for i, el in enumerate(list(parent)):
        if el.tag in before:
            parent.insert(i, child)
            return
    parent.append(child)


def colored_score(analysis: Analysis, path: Path, labels: bool = True) -> Path:
    """A copy of the score with each checked note colored and labelled."""
    for r in analysis.results:
        color = COLORS.get(r.status)
        if not color or r.note is None:
            continue
        for i, el in enumerate(r.note.elements):
            el.set("color", color)
            head = el.find("notehead")
            if head is None:
                head = ET.Element("notehead")
                head.text = "normal"
                _insert_before(el, head, ("notehead-text", "staff", "beam", "notations", "lyric", "play", "listen"))
            head.set("color", color)
            text = label(r)
            if labels and i == 0 and text:
                number = str(len(el.findall("lyric")) + 1)  # below any lyrics already there
                lyric = ET.Element("lyric", {"number": number, "name": "feedback", "color": color})
                ET.SubElement(lyric, "syllabic").text = "single"
                ET.SubElement(lyric, "text").text = text
                _insert_before(el, lyric, ("play", "listen"))
    tree = analysis.score.tree
    ET.indent(tree)
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(
            b'<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            b'"http://www.musicxml.org/dtds/partwise.dtd">\n'
        )
        tree.write(f, encoding="utf-8", xml_declaration=False)
    return path


def write_report(analysis: Analysis, out_dir: str | Path, labels: bool = True) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = analysis.score.path.stem
    paths = {
        "summary": out / "summary.md",
        "notes": out / "notes.csv",
        "json": out / "report.json",
        "score": out / f"{stem}.feedback.musicxml",
    }
    paths["summary"].write_text(summary_markdown(analysis), encoding="utf-8")
    fields = ["index", "measure", "beat_in_measure", "written", "heard", "status", "cents", "onset_sec", "timing_ms", "timing", "in_chord"]
    with open(paths["notes"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in analysis.results:
            w.writerow(r.to_dict())
    a = analysis
    paths["json"].write_text(
        json.dumps(
            {
                "score": str(a.score.path),
                "title": a.score.title,
                "part": a.score.part_name,
                "first_measure": a.first_measure,
                "last_measure": a.last_measure,
                "tempo_bpm": a.tempo_bpm,
                "tempo_start_bpm": a.tempo_start_bpm,
                "tempo_end_bpm": a.tempo_end_bpm,
                "tuning_offset_cents": a.tuning_offset_cents,
                "settings": a.settings.__dict__,
                "spots": problem_spots(a),
                "warnings": a.warnings,
                "notes": [r.to_dict() for r in a.results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    colored_score(analysis, paths["score"], labels=labels)
    return paths
