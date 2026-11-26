"""Tests for putting back the measures of multi-bar rests."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lento_convertpdf.rests import expand_multirests

NOTE = "<note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>"
REST = "<note><rest measure='yes'/><duration>4</duration></note>"
MULTI = "<attributes><measure-style><multiple-rest>{n}</multiple-rest></measure-style></attributes>" + REST
HEAD = "<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"


def part(pid: str, bodies: list[str]) -> str:
    measures = "".join(f"<measure number='{i}'>{HEAD if i == 1 else ''}{b}</measure>" for i, b in enumerate(bodies, start=1))
    return f"<part id='{pid}'>{measures}</part>"


def write(tmp_path: Path, *parts: str) -> Path:
    path = tmp_path / "s.musicxml"
    ids = "".join(f"<score-part id='P{i}'><part-name/></score-part>" for i in range(1, len(parts) + 1))
    path.write_text(f"<score-partwise><part-list>{ids}</part-list>{''.join(parts)}</score-partwise>", encoding="utf-8")
    return path


def numbers(path: Path, pid: str = "P1") -> list[str]:
    p = next(p for p in ET.parse(path).getroot().findall("part") if p.get("id") == pid)
    return [m.get("number") for m in p.findall("measure")]


def test_collapsed_rest_gets_its_measures_back(tmp_path):
    path = write(tmp_path, part("P1", [NOTE, MULTI.format(n=4), NOTE]))
    assert expand_multirests(path) == 3
    assert numbers(path) == ["1", "2", "3", "4", "5", "6"]
    root = ET.parse(path).getroot()
    added = root.findall("part/measure")[2]
    assert added.find("note/rest").get("measure") == "yes" and added.findtext("note/duration") == "4"
    assert root.findall("part/measure")[5].find("note/pitch") is not None


def test_already_expanded_rest_is_left_alone(tmp_path):
    path = write(tmp_path, part("P1", [NOTE, MULTI.format(n=3), REST, REST, NOTE]))
    assert expand_multirests(path) == 0
    assert numbers(path) == ["1", "2", "3", "4", "5"]


def test_other_parts_get_the_same_bars(tmp_path):
    path = write(tmp_path, part("P1", [NOTE, MULTI.format(n=3), NOTE]), part("P2", [NOTE, NOTE, NOTE]))
    expand_multirests(path)
    assert numbers(path, "P1") == numbers(path, "P2") == ["1", "2", "3", "4", "5"]


def test_rest_length_follows_the_time_signature(tmp_path):
    three = "<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
    path = write(tmp_path, part("P1", [NOTE, three + NOTE, MULTI.format(n=2)]))
    expand_multirests(path)
    assert ET.parse(path).getroot().findall("part/measure")[3].findtext("note/duration") == "3"
