"""Practice analyzer, checked on synthetic cello-like recordings with planted mistakes."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

from practice_synth import Take, write_score, write_take  # noqa: E402

from lento_core.score import load_score  # noqa: E402
from lento_practice import AnalysisSettings, analyze  # noqa: E402
from lento_practice.analyze import (  # noqa: E402
    DOUBLE_STOP,
    IN_TUNE,
    MISSED,
    NOT_PLAYED,
    OUT_OF_TUNE,
    SCORE_SUSPECT,
    SLIGHTLY_OFF,
    WRONG_NOTE,
)
from lento_practice.cli import main  # noqa: E402
from lento_practice.report import summary_markdown  # noqa: E402


@pytest.fixture(scope="module")
def score_path(tmp_path_factory):
    return write_score(tmp_path_factory.mktemp("score") / "etude.musicxml")


@pytest.fixture(scope="module")
def score(score_path):
    return load_score(score_path)


def run(score_path, score, tmp_path, take, settings=None):
    wav = write_take(tmp_path / "take.wav", score, take)
    return analyze(score_path, wav, settings)


def test_score_reads_the_cello_part(score):
    assert score.part_name == "Violoncello"
    assert score.tempos[0] == (0.0, 80.0)
    assert len(score.measures) == 9
    tied = next(n for n in score.notes if n.name == "F#4" and n.measure == "6")
    assert tied.duration == 4.0 and len(tied.elements) == 2
    chord = [n for n in score.notes if n.in_chord]
    assert sorted(n.name for n in chord) == ["A3", "D3"]
    assert score.notes[0].start_sec == 0.0 and score.notes[1].start_sec == pytest.approx(0.75)


def test_clean_take_is_in_tune_and_on_time(score_path, score, tmp_path):
    a = run(score_path, score, tmp_path, Take())
    statuses = [r.status for r in a.results]
    assert statuses.count(DOUBLE_STOP) == 1
    graded = [r for r in a.results if r.status != DOUBLE_STOP]
    assert all(r.status == IN_TUNE for r in graded), [(r.index, r.status, r.cents) for r in graded]
    assert all(abs(r.cents) < 4 for r in graded)
    assert not any(r.timing for r in graded), [(r.index, r.timing_ms) for r in graded if r.timing]
    assert a.tempo_bpm == pytest.approx(68, abs=1.5)
    assert (a.first_measure, a.last_measure) == ("1", "9")


def test_slowing_down_in_an_echoey_room(score_path, score, tmp_path):
    take = Take(tempo=76, slow_down=0.2, reverb_sec=0.6, detune={9: -30})
    a = run(score_path, score, tmp_path, take)
    graded = [r for r in a.results if r.status != DOUBLE_STOP]
    assert {r.index for r in graded if r.status != IN_TUNE} == {9}, [(r.index, r.status, r.cents) for r in graded if r.status != IN_TUNE]
    assert not any(r.timing for r in graded), [(r.index, r.timing_ms) for r in graded if r.timing]
    assert a.tempo_start_bpm > a.tempo_end_bpm + 6
    assert "slowed down" in summary_markdown(a)


def test_planted_mistakes_are_found(score_path, score, tmp_path):
    take = Take(detune={2: 30, 7: -15, 16: 100}, skip={23}, shift_ms={18: 150})
    a = run(score_path, score, tmp_path, take)
    r = {x.index: x for x in a.results}
    assert r[2].status == OUT_OF_TUNE and r[2].cents == pytest.approx(30, abs=4)
    assert r[7].status == SLIGHTLY_OFF and r[7].cents == pytest.approx(-15, abs=4)
    assert r[16].status == WRONG_NOTE and r[16].heard == "Eb3"
    assert r[23].status == MISSED
    assert r[18].timing == "late" and r[18].timing_ms == pytest.approx(150, abs=50)
    others = [x for i, x in r.items() if i not in (2, 7, 16, 23, 18) and x.status != DOUBLE_STOP]
    assert all(x.status == IN_TUNE and not x.timing for x in others), [(x.index, x.status, x.timing) for x in others]


def test_repeated_notes_are_split_by_rhythm(score_path, score, tmp_path):
    a = run(score_path, score, tmp_path, Take())
    spb = 60 / 68
    # measure 2: A3 quarter, A3 eighth, A3 eighth
    starts = [x.onset_sec for x in a.results if x.index in (4, 5, 6)]
    assert starts[1] - starts[0] == pytest.approx(spb, abs=0.06)
    assert starts[2] - starts[1] == pytest.approx(spb / 2, abs=0.06)


def test_a_few_measures_are_found_without_being_told(score_path, score, tmp_path):
    a = run(score_path, score, tmp_path, Take(first_measure=2, last_measure=5))
    assert (a.first_measure, a.last_measure) == ("3", "6")
    outside = [x for x in a.results if x.note.measure_index < 2 or x.note.measure_index > 5]
    assert all(x.status == NOT_PLAYED for x in outside)
    inside = [x for x in a.results if x.status not in (NOT_PLAYED, DOUBLE_STOP)]
    assert all(x.status == IN_TUNE for x in inside), [(x.index, x.status) for x in inside]


def test_measure_range_can_be_given(score_path, score, tmp_path):
    settings = AnalysisSettings(measures=("3", "6"))
    a = run(score_path, score, tmp_path, Take(first_measure=2, last_measure=5), settings)
    assert {x.measure for x in a.results} == {"3", "4", "5", "6"}


def test_consistent_interval_points_at_the_score(score_path, score, tmp_path):
    # measure 5 played a minor third high, as when a clef is misread
    a = run(score_path, score, tmp_path, Take(detune={i: 300 for i in (14, 15, 16, 17)}))
    r = {x.index: x for x in a.results}
    assert [r[i].status for i in (14, 15, 16, 17)] == [SCORE_SUSPECT] * 4
    assert "Check the score" in summary_markdown(a)


def test_overall_sharpness_suggests_a_tuning_pitch(score_path, score, tmp_path):
    take = Take(overall_cents=20)
    a = run(score_path, score, tmp_path, take)
    assert a.tuning_offset_cents == pytest.approx(20, abs=3)
    assert any("--a4 445" in w for w in a.warnings)
    b = run(score_path, score, tmp_path, take, AnalysisSettings(a4=445.1))
    assert all(x.status == IN_TUNE for x in b.results if x.status != DOUBLE_STOP)


def test_cli_writes_report_and_colored_score(score_path, score, tmp_path, capsys):
    wav = write_take(tmp_path / "take.wav", score, Take(detune={2: 30}, skip={23}))
    out = tmp_path / "report"
    assert main(["analyze", str(score_path), str(wav), "--out", str(out)]) == 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "Spots to practise" in summary and "F#3 30 cents sharp" in summary
    assert (out / "notes.csv").read_text(encoding="utf-8").count("\n") == len(score.notes) + 1
    colored = ET.parse(out / "etude.feedback.musicxml").getroot()
    cello = colored.find("./part[@id='P2']")
    colors = [n.get("color") for n in cello.iter("note") if n.find("rest") is None]
    assert colors.count("#D0342C") == 1 and colors.count("#8E44AD") == 1
    assert colored.find("./part[@id='P1']/measure/note").get("color") is None
    labels = [lyr.findtext("text") for lyr in cello.iter("lyric")]
    assert "+30" in labels and "miss" in labels
    assert "Report written" in capsys.readouterr().out


def test_cli_reports_bad_input(score_path, tmp_path, capsys):
    missing = tmp_path / "nothing.wav"
    assert main(["analyze", str(score_path), str(missing)]) == 2
    assert "error" in capsys.readouterr().err
