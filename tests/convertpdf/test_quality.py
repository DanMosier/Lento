"""Tests for the export quality check."""

from __future__ import annotations

from pathlib import Path

import pytest

from lento_convertpdf.quality import REVIEW_BELOW, _ranges, assess

NOTE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>{}</duration></note>"
BAR = NOTE.format(1) * 4
FIRST = (
    "<attributes><divisions>1</divisions><key><fifths>4</fifths></key>"
    "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
)


def key(fifths: int) -> str:
    return f"<attributes><key><fifths>{fifths}</fifths></key></attributes>"


def score(path: Path, *parts: list[str]) -> Path:
    body = ""
    for i, bars in enumerate(parts, 1):
        bars = [FIRST + bars[0], *bars[1:]]
        body += f"<part id='P{i}'>" + "".join(f"<measure number='{n}'>{b}</measure>" for n, b in enumerate(bars, 1)) + "</part>"
    path.write_text(f"<score-partwise>{body}</score-partwise>", encoding="utf-8")
    return path


def test_clean_score_is_good(tmp_path):
    report = assess(score(tmp_path / "a.xml", [BAR] * 20))
    assert report.level == "good" and report.estimate == 1.0 and not report.suspicious
    assert report.symbol_confidence is None


@pytest.mark.parametrize(
    ("bar", "reason"),
    [(NOTE.format(1) * 5, "too long"), (NOTE.format(1) * 3, "too short"), ("", "empty")],
)
def test_odd_measures_are_flagged(tmp_path, bar, reason):
    bars = [BAR] * 10
    bars[4] = bar
    report = assess(score(tmp_path / "a.xml", bars))
    assert report.suspicious == {5: [reason]}
    assert report.level == "review" and report.estimate == pytest.approx(0.9)


def test_pickup_short_ending_and_measure_rests_are_fine(tmp_path):
    rest = "<note><rest measure='yes'/><duration>2</duration></note>"
    report = assess(score(tmp_path / "a.xml", [NOTE.format(1), *[BAR] * 8, rest, BAR, NOTE.format(3)]))
    assert not report.suspicious


def test_second_voice_written_with_backup_is_not_too_long(tmp_path):
    bar = BAR + "<backup><duration>4</duration></backup>" + BAR
    assert not assess(score(tmp_path / "a.xml", [bar] * 6)).suspicious


def test_lost_key_signature_is_flagged_but_a_real_modulation_is_not(tmp_path):
    bars = [BAR] * 30
    bars[5], bars[8] = key(0) + BAR, key(4) + BAR
    assert sorted(assess(score(tmp_path / "a.xml", bars)).suspicious) == [6, 7, 8]
    bars = [BAR] * 40
    bars[10], bars[25] = key(1) + BAR, key(4) + BAR
    assert not assess(score(tmp_path / "b.xml", bars)).suspicious


def test_parts_of_different_length_are_unreliable(tmp_path):
    report = assess(score(tmp_path / "a.xml", [BAR] * 60, [BAR] * 8))
    assert report.level == "unreliable" and "differ in length" in report.summary


def test_merged_instruments_are_unreliable_even_if_the_measures_add_up(tmp_path):
    trace = {"pages": [{"page": 1, "flattened": True, "parts": 1, "reads": []}]}
    report = assess(score(tmp_path / "a.xml", [BAR] * 20), trace)
    assert report.level == "unreliable" and "page 1" in report.summary


def test_unsure_symbols_lower_the_estimate(tmp_path):
    xml = score(tmp_path / "a.xml", [BAR] * 20)
    trace = {"pages": [{"page": 1, "flattened": False, "parts": 1, "reads": [[0.9] * 90 + [0.4] * 10]}]}
    report = assess(xml, trace)
    assert report.estimate == pytest.approx(0.9) and report.level == "review"
    assert "unsure about staves on page 1" in report.summary
    assert report.symbol_confidence == pytest.approx(0.85)


def test_broken_trace_is_ignored(tmp_path):
    report = assess(score(tmp_path / "a.xml", [BAR] * 20), {"error": "AttributeError", "pages": []})
    assert report.level == "good"


def test_threshold_is_adjustable(tmp_path):
    bars = [BAR] * 10
    bars[4] = ""
    xml = score(tmp_path / "a.xml", bars)
    assert assess(xml).level == "review" and assess(xml, review_below=0.85).level == "good"
    assert 0.8 < REVIEW_BELOW < 1


def test_ranges():
    assert _ranges([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert _ranges([1, 3, 5], limit=2) == "1, 3 and 1 more places"
