"""Synthetic cello score and recordings for the practice analyzer tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SR = 22050

# (measure, [(step, alter, octave, quarters, extra)]) where extra is "", "tie-start", "tie-stop", "chord" or "rest"
MEASURES = [
    [("D", 0, 3, 1, ""), ("E", 0, 3, 1, ""), ("F", 1, 3, 1, ""), ("G", 0, 3, 1, "")],
    [("A", 0, 3, 1, ""), ("A", 0, 3, 0.5, ""), ("A", 0, 3, 0.5, ""), ("B", 0, 3, 1, ""), ("C", 1, 4, 1, "")],
    [("D", 0, 4, 2, ""), ("", 0, 0, 1, "rest"), ("D", 0, 4, 1, "")],
    [("D", 0, 3, 2, ""), ("A", 0, 3, 2, "chord"), ("G", 0, 2, 2, "")],
    [("C", 0, 2, 1, ""), ("G", 0, 2, 1, ""), ("D", 0, 3, 1, ""), ("A", 0, 3, 1, "")],
    [("E", 0, 4, 1, ""), ("E", 0, 4, 1, ""), ("F", 1, 4, 2, "tie-start")],
    [("F", 1, 4, 2, "tie-stop"), ("", 0, 0, 2, "rest")],
    [("B", 0, 3, 1, ""), ("C", 1, 4, 1, ""), ("D", 0, 4, 1, ""), ("E", 0, 4, 1, "")],
    [("F", 1, 4, 1, ""), ("E", 0, 4, 1, ""), ("D", 0, 4, 2, "")],
]
TYPES = {4: "whole", 2: "half", 1: "quarter", 0.5: "eighth"}


def write_score(path: Path, tempo: float = 80.0) -> Path:
    div = 2
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<score-partwise version="4.0">',
        "<work><work-title>Test Etude</work-title></work>",
        '<part-list><score-part id="P1"><part-name>Piano</part-name></score-part>'
        '<score-part id="P2"><part-name>Violoncello</part-name></score-part></part-list>',
        '<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>'
        '<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure></part>',
        '<part id="P2">',
    ]
    for i, notes in enumerate(MEASURES, 1):
        out.append(f'<measure number="{i}">')
        if i == 1:
            out.append(
                f"<attributes><divisions>{div}</divisions><key><fifths>2</fifths></key>"
                "<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>"
                f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                f"<per-minute>{tempo:g}</per-minute></metronome></direction-type><sound tempo=\"{tempo:g}\"/></direction>"
            )
        for step, alter, octave, q, extra in notes:
            dur = int(q * div)
            if extra == "rest":
                out.append(f"<note><rest/><duration>{dur}</duration><type>{TYPES[q]}</type></note>")
                continue
            chord = "<chord/>" if extra == "chord" else ""
            alt = f"<alter>{alter}</alter>" if alter else ""
            tie = ""
            if extra == "tie-start":
                tie = '<tie type="start"/>'
            elif extra == "tie-stop":
                tie = '<tie type="stop"/>'
            out.append(
                f"<note>{chord}<pitch><step>{step}</step>{alt}<octave>{octave}</octave></pitch>"
                f"<duration>{dur}</duration>{tie}<voice>1</voice><type>{TYPES[q]}</type></note>"
            )
        out.append("</measure>")
    out += ["</part>", "</score-partwise>"]
    path.write_text("\n".join(out), encoding="utf-8")
    return path


@dataclass
class Take:
    """How to play the score: tempo, and mistakes keyed by score note index."""

    tempo: float = 68.0  # slower than written, as in practice
    detune: dict[int, float] = field(default_factory=dict)  # cents
    skip: set[int] = field(default_factory=set)
    shift_ms: dict[int, float] = field(default_factory=dict)  # + late
    overall_cents: float = 0.0
    first_measure: int = 0  # 0-based, inclusive
    last_measure: int = 99
    slow_down: float = 0.0  # tempo falls linearly by this fraction over the take
    reverb_sec: float = 0.0  # room echo decay time
    seed: int = 1


def _tone(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib_amt = np.clip((t - 0.15) / 0.2, 0, 1) * 15.0  # cents, starts after the attack
    cents = vib_amt * np.sin(2 * np.pi * 5.5 * t + rng.uniform(0, 6.28))
    inst = freq * 2 ** (cents / 1200)
    phase = 2 * np.pi * np.cumsum(inst) / SR
    sig = np.zeros(n)
    for k in range(1, 12):
        if freq * k > SR / 2 - 500:
            break
        sig += (1.0 / k) * np.sin(k * phase + rng.uniform(0, 6.28))
    env = np.ones(n)
    a, r = int(0.04 * SR), int(0.03 * SR)
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)
    sig *= env
    sig[: int(0.03 * SR)] += rng.normal(0, 0.15, int(0.03 * SR))  # bow noise at the attack
    return sig


def render(score, take: Take) -> np.ndarray:
    """Play the part as written at take.tempo, with the take's mistakes."""
    rng = np.random.default_rng(take.seed)
    notes = [n for n in score.notes if take.first_measure <= n.measure_index <= take.last_measure]
    start_beat = min(n.beat for n in notes)
    end_beat = max(n.beat + n.duration for n in notes)
    span = end_beat - start_beat
    grid = np.linspace(0, span, 2001)
    spb_grid = 60.0 / (take.tempo * (1 - take.slow_down * grid / span))
    t_grid = np.concatenate([[0], np.cumsum((spb_grid[1:] + spb_grid[:-1]) / 2 * np.diff(grid))])

    def at(beat: float) -> float:
        return float(np.interp(beat - start_beat, grid, t_grid))

    lead = 0.5
    y = np.zeros(int((lead + at(end_beat) + 1.0 + take.reverb_sec) * SR))
    for n in notes:
        if n.index in take.skip:
            continue
        t0 = lead + at(n.beat) + take.shift_ms.get(n.index, 0) / 1000.0
        # short bow change; a late note still ends on time, as when a player comes in late
        dur = at(n.beat + n.duration) - at(n.beat) - 0.03 - max(0.0, take.shift_ms.get(n.index, 0) / 1000.0)
        cents = take.overall_cents + take.detune.get(n.index, 0.0)
        freq = 440.0 * 2 ** ((n.midi - 69) / 12 + cents / 1200)
        tone = _tone(freq, dur, rng) * (0.6 if n.in_chord else 1.0)
        i = int(t0 * SR)
        y[i : i + len(tone)] += tone[: len(y) - i]
    if take.reverb_sec:
        from scipy.signal import fftconvolve

        n = int(take.reverb_sec * SR)
        ir = rng.normal(0, 1, n) * np.exp(-6.9 * np.arange(n) / n)
        ir[0] = 0
        wet = fftconvolve(y, ir)[: len(y)]
        y = y + 0.3 * wet / (np.max(np.abs(wet)) + 1e-9) * np.max(np.abs(y))
    y += rng.normal(0, 0.003, len(y))
    return y / np.max(np.abs(y)) * 0.8


def write_take(path: Path, score, take: Take) -> Path:
    import soundfile as sf

    sf.write(str(path), render(score, take), SR)
    return path
