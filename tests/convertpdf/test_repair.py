"""Tests for repairing marks that start and never end (repair.py), and the checks built on it."""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from lento_convertpdf.quality import CHECKS_VERSION, assess, check_score, recheck
from lento_convertpdf.repair import repair_spanners, repair_tree

ATTRS = "<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves></attributes>"


def note(step: str = "C", octave: int = 4, marks: str = "", tie: str = "", staff: int = 1, voice: int = 1, chord: bool = False) -> str:
    return (
        f"<note>{'<chord/>' if chord else ''}<pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>1</duration>"
        f"{tie}<voice>{voice}</voice><type>quarter</type><staff>{staff}</staff>"
        f"{f'<notations>{marks}</notations>' if marks else ''}</note>"
    )


def slur(kind: str, number: int = 1) -> str:
    return f'<slur type="{kind}" number="{number}"/>'


def tie(kind: str) -> tuple[str, str]:
    return f'<tie type="{kind}"/>', f'<tied type="{kind}"/>'


def score(*measures: str, name: str = "Cello") -> ET.Element:
    body = "".join(f'<measure number="{i}">{ATTRS if i == 1 else ""}{m}</measure>' for i, m in enumerate(measures, 1))
    return ET.fromstring(
        f'<score-partwise><part-list><score-part id="P1"><part-name>{name}</part-name></score-part></part-list>'
        f'<part id="P1">{body}</part></score-partwise>'
    )


def slurs(root: ET.Element) -> list[tuple[str | None, str | None]]:
    return [(s.get("type"), s.get("number")) for s in root.iter("slur")]


def test_good_slurs_are_left_alone():
    root = score(note(marks=slur("start")) + note() + note() + note(marks=slur("stop")))
    report = repair_tree(root)
    assert not report.changed and report.kept["slur"] == 1
    assert slurs(root) == [("start", "1"), ("stop", "1")]


def test_slur_that_never_ends_and_stop_without_start_are_left_out():
    root = score(note(marks=slur("stop")) + note(marks=slur("start")) + note() + note(), note() * 4)
    report = repair_tree(root)
    assert report.fixed["slur"] == 2 and slurs(root) == []
    assert root.find(".//notations") is None  # emptied <notations> go too
    assert "left out 2 slurs" in report.summary


def test_slur_started_twice_keeps_the_second():
    root = score(note(marks=slur("start")) + note(marks=slur("start")) + note(marks=slur("stop")) + note())
    report = repair_tree(root)
    assert report.fixed["slur"] == 1
    notes = root.findall(".//note")
    assert notes[0].find(".//slur") is None and notes[1].find(".//slur").get("type") == "start"


def test_slur_that_ends_before_it_starts_in_the_file_is_left_out():
    # voice 1 starts a slur on beat 3; voice 2 (written after a backup) stops one on beat 1: time and file order disagree
    v1 = note() + note() + note(marks=slur("start")) + note()
    v2 = note("E", 3, slur("stop"), voice=2) + note("E", 3, voice=2) * 3
    root = score(v1 + "<backup><duration>4</duration></backup>" + v2, note() * 4)
    report = repair_tree(root)
    assert slurs(root) == [] and report.fixed["slur"] == 2  # a stop with nothing before it, a start with nothing after


def test_overlapping_slurs_on_two_staves_get_different_numbers():
    # homr numbers slurs by staff, but readers number them across the part and go in file order: the top slur is
    # still open when the bottom one starts, so they must differ
    top = note(marks=slur("start")) + note() * 3
    bottom = "".join(note("C", 3, slur("start") if i == 0 else slur("stop") if i == 3 else "", staff=2, voice=5) for i in range(4))
    root = score(top + "<backup><duration>4</duration></backup>" + bottom, note(marks=slur("stop")) + note() * 3)
    assert slurs(root) == [("start", "1"), ("start", "1"), ("stop", "1"), ("stop", "1")]
    report = repair_tree(root)
    assert not report.fixed and report.renumbered == 1 and report.changed and not report.summary
    assert slurs(root) == [("start", "1"), ("start", "2"), ("stop", "2"), ("stop", "1")]


def test_ties_need_the_same_pitch_next():
    start, started = tie("start")
    stop, stopped = tie("stop")
    good = note("G", 3, started, start) + note("G", 3, stopped, stop)
    wrong = note("A", 3, started, start) + note("B", 3, stopped, stop)
    root = score(good + wrong)
    report = repair_tree(root)
    assert report.kept["tie"] == 1 and report.fixed["tie"] == 2 and report.worth_review
    notes = root.findall(".//note")
    assert [len(n.findall("tie")) for n in notes] == [1, 1, 0, 0]
    assert [len(n.findall(".//tied")) for n in notes] == [1, 1, 0, 0]


def test_tie_across_a_barline_is_kept():
    start, started = tie("start")
    stop, stopped = tie("stop")
    root = score(note() * 3 + note("D", 4, started, start), note("D", 4, stopped, stop) + note() * 3)
    assert not repair_tree(root).changed


def octave(kind: str) -> str:
    return f'<direction><direction-type><octave-shift type="{kind}" size="8"/></direction-type><staff>1</staff></direction>'


def test_octave_line_that_never_ends_is_left_out():
    root = score(octave("down") + note() * 4, octave("down") + note() * 4, note() * 3 + octave("stop") + note())
    report = repair_tree(root)
    shifts = [o.get("type") for o in root.iter("octave-shift")]
    assert shifts == ["down", "stop"] and report.fixed["octave-shift"] == 1 and report.worth_review
    assert len(root.findall(".//direction")) == 2  # the emptied direction is gone


def test_tuplet_bracket_without_stop_is_left_out_but_chord_copies_are_ignored():
    t = '<tuplet type="{}"/>'
    root = score(
        note(marks=t.format("start")) + note("E", marks=t.format("start"), chord=True) + note() + note(marks=t.format("stop")) + note(),
        note(marks=t.format("start")) + note() * 3,
    )
    report = repair_tree(root)
    assert report.fixed["tuplet"] == 1 and report.kept["tuplet"] == 1


def test_volta_bracket_that_never_ends_is_closed():
    volta = '<barline location="left"><ending number="1" type="start"/></barline>'
    root = score(note() * 4, volta + note() * 4, note() * 4)
    report = repair_tree(root)
    assert report.fixed["ending"] == 1
    assert [e.get("type") for e in root.iter("ending")] == ["start", "discontinue"]


def test_many_broken_slurs_put_a_good_score_up_for_review(tmp_path: Path):
    bars = [note(marks=slur("start")) + note() * 3 for _ in range(12)]
    path = tmp_path / "a.musicxml"
    ET.ElementTree(score(*bars)).write(path)
    assert assess(path).level == "good"
    report = check_score(path)
    assert report.level == "review" and report.repairs["fixed"] == {"slur": 12}
    assert "left out 12 slurs" in report.summary and "slur" not in path.read_text()
    assert report.to_dict()["summary"] == report.summary


def test_a_few_broken_slurs_only_get_mentioned(tmp_path: Path):
    path = tmp_path / "a.musicxml"
    ET.ElementTree(score(note(marks=slur("stop")) + note() * 3, *[note() * 4] * 5)).write(path)
    report = check_score(path)
    assert report.level == "good" and "left out 1 slur " in report.summary


def test_notes_out_of_range_are_suspicious(tmp_path: Path):
    path = tmp_path / "a.musicxml"
    ET.ElementTree(score(note("C", 4) * 4, note("A", 1) + note() * 3, note("C", 7) + note() * 3)).write(path)
    report = assess(path)
    assert report.suspicious == {2: ["notes too low for cello"], 3: ["notes too high for cello"]}
    ET.ElementTree(score(note("A", 1) * 4, name="Voice")).write(path)  # an instrument it doesn't know: no check
    assert not assess(path).suspicious


def test_recheck_updates_an_earlier_report(tmp_path: Path):
    path = tmp_path / "a.musicxml"
    ET.ElementTree(score(octave("down") + note() * 4, note("A", 1) + note() * 3)).write(path)
    report_path = tmp_path / "a.quality.json"
    notes = recheck(path)
    assert notes == ["left out 1 octave line (8va) that did not start or end properly", "notes too low for cello in m. 2"]
    data = json.loads(report_path.read_text())
    assert data["level"] == "review" and data["recheck_notes"] == notes and data["checks_version"] == CHECKS_VERSION
    # a second run finds nothing new to repair but keeps saying what was done
    assert recheck(path) == notes
    # a clean score gets no report
    clean = tmp_path / "b.musicxml"
    ET.ElementTree(score(note() * 4)).write(clean)
    assert recheck(clean) == [] and not (tmp_path / "b.quality.json").exists()


def test_repair_is_fast(tmp_path: Path):
    bar = note(marks=slur("start")) + note() + note(marks=slur("stop")) + note("D", 4, slur("stop"))
    path = tmp_path / "big.musicxml"
    ET.ElementTree(score(*[bar] * 3000)).write(path)  # 12,000 notes, 3,000 broken slurs
    started = time.perf_counter()
    report = repair_spanners(path)
    assert report.fixed["slur"] == 3000 and time.perf_counter() - started < 3


def test_short_parts_are_filled_with_rests(tmp_path: Path):
    two = score(note() * 4, note() * 4, note() * 4)
    piano = ET.fromstring(f'<score-part id="P2"><part-name>Piano</part-name></score-part>')
    two.find("part-list").append(piano)
    two.append(ET.fromstring(f'<part id="P2"><measure number="1">{ATTRS}{note()*4}</measure></part>'))
    path = tmp_path / "a.musicxml"
    ET.ElementTree(two).write(path)
    report = check_score(path)
    assert report.level == "unreliable" and "parts differ in length (1 to 3 measures)" in report.problems
    assert "filled the end of Piano with 2 empty measures so the whole score shows" in report.problems
    root = ET.parse(path).getroot()
    assert [len(p.findall("measure")) for p in root.findall("part")] == [3, 3]
    assert [m.get("number") for m in root.findall("part")[1]] == ["1", "2", "3"]
    assert assess(path).measures == 3
