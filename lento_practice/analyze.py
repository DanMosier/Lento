"""Turn an aligned recording into per-note feedback."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from lento_core.score import Score, ScoreNote, load_score, midi_name

from .align import Event, align, group_events
from .audio import PitchTrack, load_audio, track_pitch

# Status of each note, worst last
IN_TUNE = "in_tune"
SLIGHTLY_OFF = "slightly_off"
OUT_OF_TUNE = "out_of_tune"
WRONG_NOTE = "wrong_note"
MISSED = "missed"
SCORE_SUSPECT = "score_suspect"  # consistently off by one interval: the score may be wrong
DOUBLE_STOP = "double_stop"  # second note of a double stop; not measured yet
NOT_PLAYED = "not_played"  # outside the part of the score the recording covers


# Named strictness levels, chosen separately for pitch and timing
PITCH_WINDOWS = {"strict": (5.0, 15.0), "standard": (10.0, 25.0), "relaxed": (20.0, 40.0)}  # in tune, slightly off (cents)
TIMING_WINDOWS = {"strict": 60.0, "standard": 100.0, "relaxed": 160.0}  # ms early or late


@dataclass
class AnalysisSettings:
    a4: float = 440.0
    good_cents: float = 10.0  # within this: in tune
    ok_cents: float = 25.0  # within this: slightly off; beyond: out of tune
    wrong_note_cents: float = 70.0  # beyond this the nearest semitone is another note
    timing_ms: float = 100.0  # early or late beyond this, against your own local tempo
    part: str | None = None
    measures: tuple[str, str] | None = None  # printed numbers, inclusive
    suspect_run: int = 4  # this many notes in a row off by the same interval → suspect the score


@dataclass
class NoteResult:
    index: int
    measure: str
    beat_in_measure: float  # quarter notes from the start of the measure, from 0
    written: str
    written_midi: int
    status: str
    heard: str | None = None
    heard_midi: int | None = None  # nearest semitone heard
    cents: float | None = None  # how far from the written pitch (or the heard note, for wrong notes)
    onset_sec: float | None = None
    timing_ms: float | None = None  # + late, - early, against your local tempo
    timing: str | None = None  # "early" | "late" | None
    in_chord: bool = False
    octave_folded: bool = False
    note: ScoreNote | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("note")
        return d


@dataclass
class Analysis:
    score: Score
    track: PitchTrack
    settings: AnalysisSettings
    results: list[NoteResult]
    first_measure: str | None
    last_measure: str | None
    tempo_bpm: float | None  # quarter notes per minute you played
    tempo_start_bpm: float | None
    tempo_end_bpm: float | None
    tuning_offset_cents: float | None  # median of all measured notes: your overall sharpness
    warnings: list[str]

    @property
    def played(self) -> list[NoteResult]:
        return [r for r in self.results if r.status != NOT_PLAYED]


def _measure_pitch(track: PitchTrack, ev: Event) -> tuple[float | None, int]:
    """Median pitch over the steady middle of a note, and how many pitched frames it had."""
    a, b = ev.start_frame, ev.end_frame
    midi = track.midi[a:b]
    voiced = np.isfinite(midi)
    n_voiced = int(voiced.sum())
    if n_voiced == 0:
        return None, 0
    length = b - a
    skip_head = max(5, int(0.2 * length))  # bow attack
    skip_tail = int(0.15 * length)  # release, shift to the next note
    mid = midi[skip_head : length - skip_tail] if length - skip_tail > skip_head else midi[:0]
    mid = mid[np.isfinite(mid)]
    if mid.size < 3:
        mid = midi[voiced]
    return float(np.median(mid)), n_voiced


def _refine_onset(track: PitchTrack, frame: int) -> int:
    """Move a note start to the nearest strong onset just around it."""
    lo, hi = max(0, frame - 4), min(len(track.onset), frame + 3)
    if hi <= lo:
        return frame
    k = lo + int(np.argmax(track.onset[lo:hi]))
    return k if track.onset[k] >= 0.3 else frame


def _expected_times(track: PitchTrack, events: list[Event]) -> tuple[np.ndarray, float] | None:
    """Where each event should sound, from the notes the first pass matched cleanly.

    Notes whose pitch matched and that sit within a beat of the overall tempo line
    become anchors; between anchors the expected time is interpolated, so rubato is
    followed. Returns (seconds per event, seconds per beat) or None if too few anchors.
    """
    beats, secs = [], []
    for ev in events:
        if not ev.played or ev.end_frame - ev.start_frame < 3:
            continue
        midi = track.midi[ev.start_frame : ev.end_frame]
        midi = midi[np.isfinite(midi)]
        if midi.size < 3 or np.min(np.abs(np.median(midi) - ev.pitches)) > 0.5:
            continue
        beats.append(ev.beat)
        secs.append(track.times[ev.start_frame])
    if len(beats) < 4:
        return None
    b, t = np.array(beats), np.array(secs)
    fit = _fit_line(b, t)
    if fit is None or fit[0] <= 0:
        return None
    spb = fit[0]
    resid = t - (spb * b + fit[1])
    keep = np.abs(resid) <= spb
    if keep.sum() < 4:
        return None
    all_beats = np.array([ev.beat for ev in events])
    expected = spb * all_beats + fit[1] + np.interp(all_beats, b[keep], resid[keep])
    return expected, spb


def _theil_sen(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    """Line through the median of pairwise slopes: a few early or late neighbours barely move it."""
    i, j = np.triu_indices(len(x), 1)
    ok = x[j] != x[i]
    if not ok.any():
        return None
    slope = float(np.median((y[j][ok] - y[i][ok]) / (x[j][ok] - x[i][ok])))
    return slope, float(np.median(y - slope * x))


def _fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    if len(x) < 2 or np.ptp(x) == 0:
        return None
    keep = np.ones(len(x), dtype=bool)
    for _ in range(3):
        slope, icept = np.polyfit(x[keep], y[keep], 1)
        resid = np.abs(y - (slope * x + icept))
        mad = np.median(resid[keep]) + 1e-3
        new = resid <= 3.0 * mad + 0.05
        if new.sum() < 2 or (new == keep).all():
            break
        keep = new
    return float(slope), float(icept)


def analyze(
    score_path: str | Path,
    audio_path: str | Path,
    settings: AnalysisSettings | None = None,
    *,
    track: PitchTrack | None = None,
) -> Analysis:
    settings = settings or AnalysisSettings()
    score = load_score(score_path, settings.part)
    warnings = list(score.warnings)
    notes = score.notes
    free_ends = True
    if settings.measures:
        lo, hi = score.measure_range(*settings.measures)
        notes = [n for n in notes if lo <= n.measure_index <= hi]
        free_ends = False
    if not notes:
        raise ValueError("no notes to compare in that part of the score")

    if track is None:
        track = track_pitch(load_audio(audio_path), a4=settings.a4)
    events = group_events(notes)
    align(track, events, free_ends=free_ends)
    expected = _expected_times(track, events)
    if expected is not None:
        align(track, events, free_ends=free_ends, expected_sec=expected[0], sec_per_beat=expected[1])

    played = [e for e in events if e.played]
    if not played:
        raise ValueError("could not find the score's notes in the recording")
    first_ev, last_ev = played[0].index, played[-1].index

    results: dict[int, NoteResult] = {}
    onsets: list[tuple[float, float]] = []  # (beat, seconds)
    for ev in events:
        inside = first_ev <= ev.index <= last_ev
        for n in ev.notes:
            results[n.index] = NoteResult(
                index=n.index,
                measure=n.measure,
                beat_in_measure=round(n.beat_in_measure, 3),
                written=n.name,
                written_midi=n.midi,
                status=NOT_PLAYED if not inside else MISSED,
                in_chord=n.in_chord,
                note=n,
            )
        if not inside or not ev.played:
            continue
        heard, n_voiced = _measure_pitch(track, ev)
        if heard is None or n_voiced < 3:
            continue
        # the written note this pitch belongs to (a double stop has two)
        target = min(ev.notes, key=lambda n: abs(heard - n.midi))
        diff = heard - target.midi
        folded = False
        if abs(diff) > 6 and abs(abs(diff) - 12) < 1.0:  # pitch tracker an octave out
            diff -= 12 * np.sign(diff)
            folded = True
        r = results[target.index]
        r.octave_folded = folded
        r.heard = midi_name(target.midi + diff)
        r.heard_midi = int(round(target.midi + diff))
        if abs(diff) * 100 > settings.wrong_note_cents:
            r.status = WRONG_NOTE
            r.cents = round(float((diff - round(diff)) * 100), 1)
        else:
            r.cents = round(float(diff * 100), 1)
            c = abs(r.cents)
            r.status = IN_TUNE if c <= settings.good_cents else SLIGHTLY_OFF if c <= settings.ok_cents else OUT_OF_TUNE
        start = _refine_onset(track, ev.start_frame)
        r.onset_sec = round(float(track.times[start]), 3)
        onsets.append((ev.beat, r.onset_sec))
        for other in ev.notes:
            if other is not target:
                results[other.index].status = DOUBLE_STOP
                results[other.index].onset_sec = r.onset_sec

    ordered = [results[i] for i in sorted(results)]
    _flag_suspect_score(ordered, settings)
    tempo, t_start, t_end = _timing(ordered, onsets, settings, score)

    measured = [r.cents for r in ordered if r.cents is not None and r.status not in (WRONG_NOTE, SCORE_SUSPECT)]
    offset = round(float(np.median(measured)), 1) if len(measured) >= 5 else None
    if offset is not None and abs(offset) >= 6:
        side = "sharp" if offset > 0 else "flat"
        a4_guess = settings.a4 * 2 ** (offset / 1200)
        warnings.append(
            f"On average you are {abs(offset):.0f} cents {side}. If you tuned to A={a4_guess:.0f}, "
            f"rerun with --a4 {a4_guess:.0f} to judge notes against your own tuning."
        )
    in_score = [r for r in ordered if r.status != NOT_PLAYED]
    return Analysis(
        score=score,
        track=track,
        settings=settings,
        results=ordered,
        first_measure=in_score[0].measure if in_score else None,
        last_measure=in_score[-1].measure if in_score else None,
        tempo_bpm=tempo,
        tempo_start_bpm=t_start,
        tempo_end_bpm=t_end,
        tuning_offset_cents=offset,
        warnings=warnings,
    )


def _flag_suspect_score(results: list[NoteResult], settings: AnalysisSettings) -> None:
    """Runs of notes all off by the same interval point at a misread score, not at the player."""
    measured = [r for r in results if r.heard is not None and not r.in_chord]
    run: list[NoteResult] = []

    def close(run: list[NoteResult]) -> None:
        if len(run) >= settings.suspect_run:
            for r in run:
                r.status = SCORE_SUSPECT

    last = None
    for r in measured:
        off = (r.heard_midi - r.written_midi) if r.status == WRONG_NOTE and r.heard_midi is not None else 0
        if off != 0 and off == last:
            run.append(r)
        else:
            close(run)
            run = [r] if off != 0 else []
        last = off if off != 0 else None
    close(run)


def _timing(results, onsets, settings, score):
    if len(onsets) < 4:
        return None, None, None
    beats = np.array([b for b, _ in onsets])
    secs = np.array([s for _, s in onsets])
    fit = _fit_line(beats, secs)
    if fit is None or fit[0] <= 0:
        return None, None, None
    tempo = round(60.0 / fit[0], 1)

    # each note against a line through its neighbours (about two measures), so gradual
    # tempo changes are not counted against every note
    for r in results:
        if r.onset_sec is None or r.status == DOUBLE_STOP:
            continue
        b = r.note.beat
        # neighbours only: a late note must not pull the line it is measured against
        dist = np.abs(beats - b)
        window = (dist <= 6.0) & (dist > 1e-6)
        if window.sum() < 4:
            window = [i for i in np.argsort(dist) if dist[i] > 1e-6][:4]
        local = _theil_sen(beats[window], secs[window]) or fit
        dev = (r.onset_sec - (local[0] * b + local[1])) * 1000.0
        r.timing_ms = round(float(dev), 0)
        if dev > settings.timing_ms:
            r.timing = "late"
        elif dev < -settings.timing_ms:
            r.timing = "early"

    quarter = max(1, len(beats) // 4)
    order = np.argsort(beats)
    head, tail = order[: max(quarter, 3)], order[-max(quarter, 3):]
    fs, fe = _fit_line(beats[head], secs[head]), _fit_line(beats[tail], secs[tail])
    t_start = round(60.0 / fs[0], 1) if fs and fs[0] > 0 else None
    t_end = round(60.0 / fe[0], 1) if fe and fe[0] > 0 else None
    return tempo, t_start, t_end
