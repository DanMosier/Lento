"""Line a pitch track up with the score's notes.

A left-to-right dynamic programme over two states per note group ("event"):
the gap before it (silence, bow change, rest) and the event itself. Every
audio frame is assigned to one state, in score order, minimising how far the
heard pitch is from the written one. Tempo changes, pauses and rubato cost
nothing, so the alignment follows whatever tempo was played.

By default the recording may start and stop anywhere in the score, so a take of
a few measures lines up with those measures on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lento_core.score import ScoreNote

from .audio import PitchTrack

PITCH_CAP = 6.0  # semitones; a wrong note costs no more than this per frame
UNVOICED_IN_NOTE = 1.0  # a frame with no pitch inside a note (bow change, noise)
VOICED_IN_GAP = 6.5  # a pitched frame where no note is written; above PITCH_CAP so wrong notes stay notes
SKIP = 8.0  # passing over a note without playing it
ENTER = 0.5  # starting a note after a gap, reduced by an onset
LEGATO = 0.3  # moving straight to a note of another pitch, reduced by an onset
REPEAT = 4.0  # moving straight to a note of the same pitch: needs a clear onset
POSITION = 1.0  # per frame and per beat beyond half a beat, away from where the rhythm expects a note
INF = 1e18


@dataclass
class Event:
    """Notes that start together: one note, or a double stop."""

    index: int
    notes: list[ScoreNote]
    beat: float
    duration: float
    pitches: np.ndarray = field(repr=False)
    start_frame: int = -1
    end_frame: int = -1  # exclusive

    @property
    def played(self) -> bool:
        return self.start_frame >= 0


def group_events(notes: list[ScoreNote]) -> list[Event]:
    events: list[Event] = []
    for n in notes:
        if events and abs(events[-1].beat - n.beat) < 1e-6:
            ev = events[-1]
            ev.notes.append(n)
            ev.duration = max(ev.duration, n.duration)
            ev.pitches = np.array([x.midi for x in ev.notes], dtype=float)
        else:
            events.append(Event(len(events), [n], n.beat, n.duration, np.array([n.midi], dtype=float)))
    return events


def _note_costs(track: PitchTrack, events: list[Event]) -> np.ndarray:
    """Frame x event cost of hearing this frame inside that event."""
    m = track.midi[:, None]
    best = np.full((len(track.midi), len(events)), np.inf)
    width = max(len(e.pitches) for e in events)
    for k in range(width):
        p = np.array([e.pitches[min(k, len(e.pitches) - 1)] for e in events])[None, :]
        d = np.abs(m - p)
        d = np.minimum(d, np.minimum(np.abs(m - p - 12), np.abs(m - p + 12)) + 2.0)
        best = np.minimum(best, d)
    cost = np.minimum(best, PITCH_CAP)
    unvoiced = ~np.isfinite(track.midi)
    cost[unvoiced, :] = UNVOICED_IN_NOTE
    return cost


def align(
    track: PitchTrack,
    events: list[Event],
    free_ends: bool = True,
    expected_sec: np.ndarray | None = None,
    sec_per_beat: float | None = None,
) -> list[Event]:
    """Fill start_frame/end_frame on each event that was heard. Returns the events.

    With `expected_sec` (where each event is expected to sound, from a first pass)
    a note heard more than half a beat away from where the rhythm puts it costs extra,
    so a passage that matches no written pitch still lines up by its rhythm.
    """
    n_ev = len(events)
    n_fr = len(track.midi)
    if n_ev == 0 or n_fr == 0:
        return events
    if n_ev * n_fr > 120_000_000:
        raise ValueError("recording and score are too long to compare at once; choose a range of measures")

    note_cost = _note_costs(track, events)
    if expected_sec is not None and sec_per_beat:
        off_beats = np.abs(track.times[:, None] - expected_sec[None, :]) / sec_per_beat
        note_cost += np.minimum(POSITION * np.maximum(off_beats - 0.5, 0.0), PITCH_CAP)
    voiced = np.isfinite(track.midi)
    gap_cost = np.where(voiced, VOICED_IN_GAP, 0.0)
    same_as_prev = np.zeros(n_ev, dtype=bool)
    for j in range(1, n_ev):
        same_as_prev[j] = bool(set(events[j].pitches.tolist()) & set(events[j - 1].pitches.tolist()))
    no_onset = 1.0 - track.onset

    inf1 = np.array([INF])
    # E[j]: inside event j. G[j]: gap before event j (G[n_ev] = after the last one)
    E = note_cost[0].copy()
    G = np.full(n_ev + 1, gap_cost[0])
    if not free_ends:
        E[1:] = INF
        G[1:] = INF
    back_e = np.zeros((n_fr, n_ev), dtype=np.int8)
    back_g = np.zeros((n_fr, n_ev + 1), dtype=np.int8)

    for t in range(1, n_fr):
        step = np.where(same_as_prev, REPEAT, LEGATO) * no_onset[t]
        cands_e = np.stack(
            [
                E,  # 0 stay
                G[:n_ev] + ENTER * no_onset[t],  # 1 from the gap before
                np.concatenate([inf1, E[:-1] + step[1:]]),  # 2 straight from the previous note
                np.concatenate([inf1, inf1, E[:-2]])[:n_ev] + SKIP,  # 3 skipping one note
                np.concatenate([inf1, G[: n_ev - 1]]) + SKIP,  # 4 from the gap before the skipped note
            ]
        )
        cands_g = np.stack(
            [
                G,  # 0 stay
                np.concatenate([inf1, E]),  # 1 note ended
                np.concatenate([inf1, G[:-1]]) + SKIP,  # 2 skipping a note
            ]
        )
        be = np.argmin(cands_e, axis=0)
        bg = np.argmin(cands_g, axis=0)
        E = cands_e[be, np.arange(n_ev)] + note_cost[t]
        G = cands_g[bg, np.arange(n_ev + 1)] + gap_cost[t]
        back_e[t] = be
        back_g[t] = bg

    if free_ends:
        end_e, end_g = E, G
    else:
        end_e = E + SKIP * (n_ev - 1 - np.arange(n_ev))
        end_g = G + SKIP * (n_ev - np.arange(n_ev + 1))
    if end_e.min() <= end_g.min():
        is_note, j = True, int(np.argmin(end_e))
    else:
        is_note, j = False, int(np.argmin(end_g))

    path = np.full(n_fr, -1)  # event index per frame, -1 for gaps
    for t in range(n_fr - 1, -1, -1):
        if is_note:
            path[t] = j
            code = back_e[t, j] if t > 0 else 0
            if code == 1:
                is_note = False
            elif code == 2:
                j -= 1
            elif code == 3:
                j -= 2
            elif code == 4:
                is_note, j = False, j - 1
        else:
            code = back_g[t, j] if t > 0 else 0
            if code == 1:
                is_note, j = True, j - 1
            elif code == 2:
                j -= 1

    for ev in events:
        ev.start_frame = ev.end_frame = -1
    _split_repeated(track, events, path)
    return events


def _split_repeated(track: PitchTrack, events: list[Event], path: np.ndarray) -> None:
    """Fill frames per event, splitting runs of same-pitch notes by rhythm and onsets.

    Pitch alone cannot tell where one A ends and the next begins, so inside such a
    run each boundary goes to the strongest onset or silence near where the
    written rhythm puts it.
    """
    change = np.flatnonzero(np.diff(np.concatenate([[-2], path, [-2]])))
    for a, b in zip(change[:-1], change[1:]):
        j = int(path[a])
        if j >= 0:
            if events[j].start_frame < 0:
                events[j].start_frame = int(a)
            events[j].end_frame = int(b)

    j = 0
    while j < len(events):
        k = j
        while (
            k + 1 < len(events)
            and events[k + 1].played
            and events[k].played
            and set(events[k + 1].pitches.tolist()) & set(events[k].pitches.tolist())
        ):
            k += 1
        if k > j and events[j].played:
            run = events[j : k + 1]
            a, b = run[0].start_frame, run[-1].end_frame
            total = run[-1].beat + run[-1].duration - run[0].beat
            silent = ~np.isfinite(track.midi)
            prev = a
            for ev in run[1:]:
                expect = a + (b - a) * (ev.beat - run[0].beat) / total
                reach = 0.35 * (b - a) * min(ev.duration, ev.beat - run[ev.index - j - 1].beat) / total
                lo, hi = max(prev + 1, int(expect - reach)), min(b - 1, int(expect + reach) + 1)
                if hi <= lo:
                    cut = int(round(expect))
                else:
                    frames = np.arange(lo, hi)
                    # an onset, or the end of a silence (bow change), close to the expected place
                    after_silence = np.concatenate([[0.0], silent[lo - 1 : hi - 1].astype(float)])[: len(frames)] if lo > 0 else np.zeros(len(frames))
                    evidence = np.maximum(track.onset[lo:hi], after_silence * (~silent[lo:hi]))
                    closeness = 1.0 - np.abs(frames - expect) / max(reach, 1.0)
                    cut = int(frames[np.argmax(evidence + 0.5 * closeness)])
                cut = max(prev + 1, min(cut, b - 1))
                events[ev.index - 1].end_frame = cut
                ev.start_frame = cut
                prev = cut
            # skip the silence at the start of each note
            for ev in run[1:]:
                while ev.start_frame < ev.end_frame - 1 and silent[ev.start_frame]:
                    ev.start_frame += 1
        j = k + 1
