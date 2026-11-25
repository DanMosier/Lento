"""Score a MusicXML transcription against a reference, note by note.

Uses music21 rather than the app's own parser so that a parser bug cannot hide a transcription bug.

    python tests/compare_musicxml.py reference.musicxml candidate.musicxml

Method
- Notes of all parts/staves/voices are pooled per measure; hand and voice assignment is not scored.
- Measures are aligned in order, so a dropped or inserted measure costs only itself instead of shifting the rest.
- "pitch" matches written pitch within an aligned measure. "strict" also needs the same onset and duration.
- With several instruments, each is also scored on its own against the part of the same printed name. The
  measures are paired once for the whole score, so a line in the wrong instrument counts as wrong in both.
- Grace notes are left out (they have no duration). Repeats are not expanded. Ties are not merged.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from music21 import chord, converter, harmony, key, meter, note, stream

GRID = 48  # onsets and durations are compared on a 1/48-quarter grid


def _grid(value: float | Fraction) -> int:
    return round(Fraction(value) * GRID)


@dataclass
class Score:
    measures: list[Counter]  # one Counter of (onset, midi, duration) per measure
    parts: int
    staves: int
    times: list[str]
    keys: list[int]
    by_part: dict[str, list[Counter]] = field(default_factory=dict)  # the same per instrument name
    short_names: dict[str, str] = field(default_factory=dict)  # instrument name -> abbreviation

    @property
    def notes(self) -> int:
        return sum(m.total() for m in self.measures)


@dataclass
class PRF:
    matched: int
    candidate: int
    reference: int

    @property
    def precision(self) -> float:
        return self.matched / self.candidate if self.candidate else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.reference if self.reference else 0.0

    @property
    def f1(self) -> float:
        total = self.candidate + self.reference
        return 2 * self.matched / total if total else 0.0

    def __str__(self) -> str:
        return (
            f"P {self.precision:6.1%}  R {self.recall:6.1%}  F1 {self.f1:6.1%}  "
            f"({self.matched} matched, {self.candidate} found, {self.reference} expected)"
        )


@dataclass
class Comparison:
    reference: Score
    candidate: Score
    pitch: PRF
    strict: PRF
    wrong_measures: list[str] = field(default_factory=list)
    perfect_measures: int = 0
    instruments: dict[str, tuple[PRF, PRF]] = field(default_factory=dict)  # name -> pitch, strict
    unmatched_parts: list[str] = field(default_factory=list)  # in the output, but not in the reference

    @property
    def placed_pitch(self) -> PRF:
        """Pitches that are right and in the right instrument."""
        return self._placed(0)

    @property
    def placed_strict(self) -> PRF:
        return self._placed(1)

    def _placed(self, kind: int) -> PRF:
        return PRF(sum(v[kind].matched for v in self.instruments.values()), self.candidate.notes, self.reference.notes)


def load(path: Path) -> Score:
    parsed = converter.parse(str(path), forceSource=True)
    parts = list(parsed.parts) if isinstance(parsed, stream.Score) else [parsed]
    measures: list[Counter] = []
    by_part: dict[str, list[Counter]] = {}
    short_names: dict[str, str] = {}
    names: dict[str, str] = {}
    for part in parts:
        part_id = str(part.id).split("-Staff")[0]
        if part_id not in names:
            name = _plain(part.partName) or part_id
            while name in by_part:  # two parts of the same name stay two
                name += "+"
            names[part_id] = name
            by_part[name] = []
            short_names[name] = _plain(part.partAbbreviation)
        own = by_part[names[part_id]]
        for index, measure in enumerate(part.getElementsByClass(stream.Measure)):
            while len(measures) <= index:
                measures.append(Counter())
            while len(own) <= index:
                own.append(Counter())
            for element in measure.recurse().notes:
                if element.duration.isGrace or isinstance(element, harmony.ChordSymbol):
                    continue
                onset = _grid(element.getOffsetInHierarchy(measure))
                length = _grid(element.duration.quarterLength)
                members = element.notes if isinstance(element, chord.Chord) else [element]
                for member in members:
                    if isinstance(member, note.Note):
                        measures[index][(onset, member.pitch.midi, length)] += 1
                        own[index][(onset, member.pitch.midi, length)] += 1

    first = parts[0]
    times = [t.ratioString for t in first.recurse().getElementsByClass(meter.TimeSignature)]
    keys = [k.sharps for k in first.recurse().getElementsByClass(key.KeySignature)]
    part_ids = {str(p.id).split("-Staff")[0] for p in parts}
    return Score(measures, len(part_ids), len(parts), _collapse(times), _collapse(keys), by_part, short_names)


def _plain(name: str | None) -> str:
    return " ".join((name or "").split())


def _collapse(values: list) -> list:
    """Drop repeats, so a key restated on every system counts once."""
    return [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]


def _pitches(measure: Counter) -> Counter:
    out: Counter = Counter()
    for (_, midi, _), count in measure.items():
        out[midi] += count
    return out


def _similarity(a: Counter, b: Counter) -> float:
    total = a.total() + b.total()
    if total == 0:
        return 0.1  # two empty measures: weak evidence that they correspond
    strict = 2 * (a & b).total() / total
    pitch = 2 * (_pitches(a) & _pitches(b)).total() / total
    return (strict + pitch) / 2


def align(ref: list[Counter], cand: list[Counter]) -> list[tuple[int | None, int | None]]:
    n, m = len(ref), len(cand)
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(
                best[i + 1][j + 1] + _similarity(ref[i], cand[j]), best[i + 1][j], best[i][j + 1]
            )
    pairs: list[tuple[int | None, int | None]] = []
    i = j = 0
    while i < n and j < m:
        if best[i][j] == best[i + 1][j + 1] + _similarity(ref[i], cand[j]):
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            pairs.append((i, None))
            i += 1
        else:
            pairs.append((None, j))
            j += 1
    pairs += [(k, None) for k in range(i, n)] + [(None, k) for k in range(j, m)]
    return pairs


def compare(reference: Path, candidate: Path) -> Comparison:
    ref, cand = load(reference), load(candidate)
    pitch_hits = strict_hits = perfect = 0
    wrong: list[str] = []
    pairs = align(ref.measures, cand.measures)
    for i, j in pairs:
        if i is None:
            wrong.append(f"extra measure in output at #{j + 1}")
            continue
        if j is None:
            wrong.append(f"m{i + 1}: missing")
            continue
        a, b = ref.measures[i], cand.measures[j]
        strict_hits += (a & b).total()
        pitch_hits += (_pitches(a) & _pitches(b)).total()
        if a == b:
            perfect += 1
        else:
            wrong.append(f"m{i + 1}: {(a & b).total()}/{a.total()} right, {b.total()} found")
    return Comparison(
        ref, cand,
        PRF(pitch_hits, cand.notes, ref.notes),
        PRF(strict_hits, cand.notes, ref.notes),
        wrong, perfect, *_compare_parts(ref, cand, pairs),
    )


def _compare_parts(
    ref: Score, cand: Score, pairs: list[tuple[int | None, int | None]]
) -> tuple[dict[str, tuple[PRF, PRF]], list[str]]:
    left = dict(cand.by_part)
    result: dict[str, tuple[PRF, PRF]] = {}
    chosen: dict[str, list[Counter]] = {}
    for label in (lambda n: n, lambda n: ref.short_names[n]):  # by full name first, then by abbreviation
        for name in ref.by_part:
            if name not in chosen and label(name) in left:
                chosen[name] = left.pop(label(name))
    for name, want in ref.by_part.items():
        got = chosen.get(name, [])
        pitch = strict = 0
        for i, j in pairs:
            if i is not None and j is not None and i < len(want) and j < len(got):
                strict += (want[i] & got[j]).total()
                pitch += (_pitches(want[i]) & _pitches(got[j])).total()
        found, expected = sum(m.total() for m in got), sum(m.total() for m in want)
        result[name] = PRF(pitch, found, expected), PRF(strict, found, expected)
    return result, list(left)


def report(result: Comparison) -> str:
    r, c = result.reference, result.candidate
    lines = []
    if r.parts > 1:
        lines = [f"{'instrument':24}{'expected':>9}{'found':>8}{'pitch F1':>10}{'strict F1':>11}"]
        for name, (pitch, strict) in result.instruments.items():
            lines.append(f"{name[:23]:24}{pitch.reference:>9}{pitch.candidate:>8}{pitch.f1:>10.1%}{strict.f1:>11.1%}")
        lines += [
            f"in the right instrument: pitch {result.placed_pitch.f1:.1%}, strict {result.placed_strict.f1:.1%}",
            f"parts without a match in the reference: {result.unmatched_parts or 'none'}",
        ]
    return "\n".join([
        f"{'':12}{'reference':>12}{'output':>12}",
        f"{'measures':12}{len(r.measures):>12}{len(c.measures):>12}",
        f"{'notes':12}{r.notes:>12}{c.notes:>12}",
        f"{'parts':12}{r.parts:>12}{c.parts:>12}",
        f"{'staves':12}{r.staves:>12}{c.staves:>12}",
        f"time sigs   {r.times} -> {c.times}",
        f"key sigs    {r.keys} -> {c.keys}",
        f"pitch       {result.pitch}",
        f"strict      {result.strict}",
        f"measures exactly right: {result.perfect_measures}/{len(r.measures)}",
        "wrong measures: " + ("; ".join(result.wrong_measures) or "none"),
        *lines,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a MusicXML transcription with a reference.")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(report(compare(args.reference, args.candidate)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
