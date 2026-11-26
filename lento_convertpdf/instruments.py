"""Work out which instrument each staff of a score belongs to, from the labels printed beside the staves.

Standard library only: homr_bridge.py loads this file inside homr's environment.

A full score hides instruments that rest, so the staves of a system are a subset of the instruments, always in the
same order. Labels are matched with that order in mind: first a roster of all instruments is built from the whole
score, then each system is aligned with it. A staff whose place is not certain is left unplaced (None), never guessed.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

MIN_MATCH = 0.5  # labels less alike than this are different instruments

# Families in usual score order: names and abbreviations in English, Italian, German and French.
_FAMILIES: list[tuple[str, str]] = [
    ("piccolo", "piccolo piccoli picc ottavino ott|flauto piccolo|kleine flote|kl fl|petite flute|fl picc"),
    ("flute", "flute flutes flauto flauti fl flote floten"),
    ("oboe", "oboe oboes oboi oboen ob hautbois hb htb"),
    ("english horn", "englischhorn eh|english horn|cor anglais|corno inglese|c ing|cor ing|e h|e hn|c a"),
    ("bass clarinet", "bassklarinette bcl|bass clarinet|clarinetto basso|clarinette basse|b cl|bs cl|cl b|cl basso"),
    ("clarinet", "clarinet clarinets clarinetto clarinetti klarinette klarinetten clarinette clarinettes cl kl klar clar"),
    ("contrabassoon", "contrabassoon contrafagotto kontrafagott contrebasson cbsn cfg kfg cfag|c fag|double bassoon"),
    ("bassoon", "bassoon bassoons fagotto fagotti fagott fagotte basson bassons fag fg bsn bn"),
    ("soprano sax", "|soprano saxophone|soprano sax|s sax|sop sax"),
    ("alto sax", "|alto saxophone|alto sax|a sax"),
    ("tenor sax", "|tenor saxophone|tenor sax|t sax|ten sax"),
    ("baritone sax", "|baritone saxophone|baritone sax|b sax|bari sax"),
    ("horn", "horn horns corno corni horner cor cors hn hns hr|french horn|french horns"),
    ("cornet", "cornet cornets cornetta cornette kornett|cornet a pistons"),
    ("trumpet", "trumpet trumpets tromba trombe trompete trompeten trompette trompettes tpt tpts trp tr"),
    ("bass trombone", "bassposaune|bass trombone|trombone basso|b tbn|bs tbn"),
    ("trombone", "trombone trombones tromboni trombono posaune posaunen tbn tbns tbni tbne trb trbn trbni pos"),
    ("tuba", "tuba tubas tb tba basstuba"),
    ("timpani", "timpani timp pauken pk timbales timb"),
    ("triangle", "triangle triangolo triangel trgl trg"),
    ("cymbals", "cymbal cymbals piatti becken cymbales cym ptti"),
    ("bass drum", "|bass drum|gran cassa|grosse trommel|grosse caisse|gr c|gr tr"),
    ("snare drum", "|snare drum|side drum|kleine trommel|caisse claire|s d"),
    ("percussion", "percussion perc drums drumset schlagzeug batteria"),
    ("glockenspiel", "glockenspiel glsp campanelli"),
    ("xylophone", "xylophone xylophon silofono xyl"),
    ("harp", "harp harps arpa arpe harfe harfen harpe harpes hp hfe hrp"),
    ("celesta", "celesta celeste cel"),
    ("harpsichord", "harpsichord cembalo clavecin hpschd cemb"),
    ("organ", "organ organo orgel orgue org"),
    ("piano", "piano pianoforte pno pf pfte klavier klav pn"),
    ("guitar", "guitar guitars chitarra gitarre guitare gtr git"),
    ("soprano", "soprano soprani sopran sopranos sop"),
    ("alto", "alto alti altos contralto"),
    ("tenor", "tenor tenore tenori tenors ten"),
    ("baritone", "baritone baritono bariton bar"),
    ("voice", "voice voices canto singstimme gesang voix"),
    ("violin", "violin violins violino violini violine violinen violon violons vl vln vlns vn vni viol vno"),
    ("viola", "viola violas viole violen bratsche bratschen vla vle br"),
    ("cello", "violoncello violoncelli violoncellos cello celli cellos violoncell violoncelle violoncelles vc vlc vcl vlcl"),
    (
        "double bass",
        "basso bassi bass basses b contrabass contrabasso contrabbasso contrabbassi kontrabass contrebasse "
        "contrebasses cb kb db|double bass|double basses|string bass|d b|c b",
    ),
]
# Clefs homr may well have misread: it takes tenor clefs for alto clefs, which puts every note a third too high
_CLEFS: dict[str, set[str]] = {
    **dict.fromkeys(("piccolo", "flute", "oboe", "english horn", "clarinet", "cornet", "trumpet", "violin"), {"G2"}),
    **dict.fromkeys(("cello", "double bass"), {"F4", "C4", "G2"}),
    **dict.fromkeys(("contrabassoon", "bass trombone", "tuba", "timpani"), {"F4"}),
    "bassoon": {"F4", "C4"},
    "trombone": {"F4", "C4"},
    "horn": {"G2", "F4"},
    "viola": {"C3", "G2"},
}
TWO_STAFF_FAMILIES = {"piano", "harp", "celesta", "harpsichord", "organ"}
# Written range as MIDI note numbers, a little wider than the usual range so that only misreadings fall outside:
# a note below a cello's open C is almost always a wrong clef, a missed octave line or a misread ledger line.
_RANGES: dict[str, tuple[int, int]] = {
    "violin": (55, 105),  # G3 to A7
    "viola": (48, 93),  # C3 to A6
    "cello": (36, 88),  # C2 to E6
    "double bass": (28, 79),  # E1 to G5, written
    "piano": (21, 108),
    "harp": (23, 104),
    "guitar": (40, 88),  # written
    "flute": (59, 98),
    "oboe": (58, 93),
    "clarinet": (50, 96),  # written
    "bassoon": (34, 79),
    "horn": (34, 82),  # written
    "trumpet": (52, 86),  # written
    "trombone": (34, 77),
    "tuba": (26, 67),
}

_NAMES: dict[str, str] = {}
for _family, _spec in _FAMILIES:
    _single, *_phrases = _spec.split("|")
    for _name in [*_single.split(), *_phrases]:
        _NAMES.setdefault(_name, _family)
_ORDER = {family: i for i, (family, _) in enumerate(_FAMILIES)}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}
_ORDINALS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "first": 1, "second": 2, "third": 3, "fourth": 4}
_PERFORMANCE = {"div", "divisi", "unis", "solo", "soli", "tutti"}


@dataclass(frozen=True)
class Name:
    """A label taken apart: 'Corni in F I II' is words ('corni',), numbers {1, 2}, family 'horn'."""

    text: str
    words: tuple[str, ...]
    numbers: frozenset[int]
    family: str | None
    unsure: bool = False  # the numbers are 'III' from OCR, which may as well be 'I II'

    @property
    def readings(self) -> list[frozenset[int]]:
        return [self.numbers, frozenset({1, 2})] if self.unsure else [self.numbers]


def parse_name(text: str, ocr: bool = False) -> Name | None:
    """Take a printed label apart. None if it cannot be an instrument, e.g. a measure number."""
    shown = " ".join(text.split())
    plain = unicodedata.normalize("NFKD", shown.replace("ß", "ss").replace("♭", " "))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    tokens = re.findall(r"[^\W_]+|\|+", plain)
    if not any(c.isalpha() for c in plain):
        return None
    words: list[str] = []
    numbers: set[int] = set()
    tuning = False  # after "in": the pitches an instrument is tuned to, up to a number
    for token in tokens:
        if token in _ORDINALS:
            numbers.add(_ORDINALS[token])
        elif token.isdigit():
            if int(token) <= 8:
                numbers.add(int(token))
        elif token in _ROMAN and (words or tuning or token in ("i", "ii", "iii", "iv")):  # also "II. Violine"
            numbers.add(_ROMAN[token])
            tuning = False
        elif re.fullmatch(r"[il1|]{1,3}", token) and (words or tuning):  # I, II and III as OCR may read them
            numbers.add(len(token))
            tuning = False
        elif token in ("in", "en") and words:
            tuning = True
        elif not tuning and token not in _PERFORMANCE:
            words.append(token)
    if words == ["vi"] or (not words and tokens[:1] == ["vi"]):
        words = ["vl"]  # OCR reads "Vl." as "VI."
    if len(words) > 1:  # the pitch of a transposing instrument: "Bb Clarinet", "F Horn"
        kept = [w for w in words if w not in ("bb", "eb", "ab", "flat", "sharp")]
        phrase = " ".join(kept)
        if phrase not in _NAMES and len(kept) > 1 and len(kept[0]) == 1 and " ".join(kept[1:]) in _NAMES:
            kept = kept[1:]
        words = kept or words
    if not words:
        return None
    return Name(shown, tuple(words), frozenset(numbers), _family(words), ocr and numbers == {3})


def _family(words: list[str]) -> str | None:
    phrase = " ".join(words)
    for candidate in (phrase, " ".join(words[:2]), words[0]):
        if candidate in _NAMES:
            return _NAMES[candidate]
    return None


def _abbreviates(short: str, long: str) -> bool:
    """Whether the letters of short occur in long in order, with the same first letter."""
    if not short or short[0] != long[0]:
        return False
    letters = iter(long)
    return all(c in letters for c in short)


def _numbers_agree(a: frozenset[int], b: frozenset[int]) -> float:
    if a == b:
        return 1.0
    if a and b:
        return 0.55 if a & b else 0.1
    given = a or b
    # "Cl. I" can be the clarinets of "Clarinetti"; "Cl. II" alone is somebody else
    return 0.85 if 1 in given and len(given) == 1 else 0.8 if 1 in given else 0.3


def similarity(a: Name, b: Name) -> float:
    """How sure it is that two labels mean the same instrument, 0 to 1."""
    if a.family and b.family:
        if a.family != b.family:
            return 0.0
        base = 1.0
    else:
        x, y = "".join(a.words), "".join(b.words)
        short, long = sorted((x, y), key=len)
        if x == y:
            base = 1.0
        elif a.family or b.family:  # one is known, so the other should look very much like it
            base = SequenceMatcher(None, x, y).ratio() if len(short) > 2 else 0.0
            base = base if base >= 0.75 else 0.0
        elif _abbreviates(short, long):
            base = 0.8
        else:
            base = SequenceMatcher(None, x, y).ratio()
    agree = _numbers_agree(a.numbers, b.numbers)
    if a.unsure or b.unsure:
        agree = max(agree, 0.7 * max(_numbers_agree(x, y) for x in a.readings for y in b.readings))
    return base * agree


# ---- labels beside staves ----------------------------------------------------------------------


@dataclass
class Text:
    """A piece of text on the page, in the coordinates of the staves."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def text_lines(chars: list[Text]) -> list[Text]:
    """Join single characters into lines. A clear gap becomes a space, so 'I II' is not read as 'III'."""
    lines: list[list[Text]] = []
    for char in sorted(chars, key=lambda c: c.y1):
        for line in lines:
            height = max(c.y1 - c.y0 for c in line)
            if abs(line[0].y1 - char.y1) < 0.4 * max(height, char.y1 - char.y0):
                line.append(char)
                break
        else:
            lines.append([char])
    joined = []
    for line in lines:
        line.sort(key=lambda c: c.x0)
        height = max(c.y1 - c.y0 for c in line)
        pieces: list[list[Text]] = [[line[0]]]
        for char in line[1:]:
            if char.x0 - pieces[-1][-1].x1 > 2.5 * height:
                pieces.append([char])
            else:
                pieces[-1].append(char)
        for piece in pieces:
            text = piece[0].text
            for left, right in zip(piece, piece[1:]):
                text += (" " if right.x0 - left.x1 > 0.22 * height else "") + right.text
            joined.append(
                Text(piece[0].x0, min(c.y0 for c in piece), piece[-1].x1, max(c.y1 for c in piece), text)
            )
    return joined


def text_blocks(lines: list[Text]) -> list[Text]:
    """Join the lines of a label, such as 'Cor.' above 'I II'. Measure numbers are left out."""
    lines = [line for line in lines if any(c.isalpha() for c in line.text)]
    blocks: list[Text] = []
    for line in sorted(lines, key=lambda t: t.y0):
        above = blocks[-1] if blocks else None
        if above and line.y0 - above.y1 < 0.9 * (line.y1 - line.y0) and line.x0 < above.x1 and above.x0 < line.x1:
            blocks[-1] = Text(
                min(above.x0, line.x0), above.y0, max(above.x1, line.x1), line.y1, f"{above.text} {line.text}"
            )
        else:
            blocks.append(Text(line.x0, line.y0, line.x1, line.y1, line.text))
    return blocks


@dataclass
class Unit:
    """One instrument's staff (or pair of staves) in a system. rows are indexes of five-line staves from the top."""

    rows: tuple[int, ...]
    label: Name | None = None


def label_units(centers: list[float], pairs: set[int], blocks: list[Text], ocr: bool = False) -> list[Unit]:
    """Group five-line staves into instruments, by where the labels stand.

    centers: the middle of each five-line staff from top to bottom. pairs: rows detected as the upper staff of a pair.
    A label beside one staff belongs to that staff, which also undoes a pair that joined two instruments. A label
    between two staves names the pair, or both staves if they have labels of their own.
    """
    own: dict[int, list[str]] = {}
    shared: dict[int, list[str]] = {}
    for block in sorted(blocks, key=lambda b: b.y0):
        y = (block.y0 + block.y1) / 2
        spots = [(abs(y - c), 0, i) for i, c in enumerate(centers)]
        spots += [(abs(y - (a + b) / 2), 1, i) for i, (a, b) in enumerate(zip(centers, centers[1:]))]
        if not spots:
            continue
        distance, kind, i = min(spots)
        near = [abs(centers[i] - c) for c in centers[max(0, i - 1) : i + 2] if c != centers[i]]
        if near and distance > 0.35 * min(near):
            continue  # beside nothing in particular
        (shared if kind else own).setdefault(i, []).append(block.text)

    units: list[Unit] = []
    row = 0
    while row < len(centers):
        texts = own.get(row, [])
        between = shared.get(row, [])
        below = own.get(row + 1, [])
        if between and not texts and not below:
            label = parse_name(" ".join(between), ocr)
            if label and (row in pairs or label.family in TWO_STAFF_FAMILIES):
                units.append(Unit((row, row + 1), label))
                row += 2
                continue
            if label:  # one name for two separate staves
                units += [Unit((row,), label), Unit((row + 1,), label)]
                row += 2
                continue
        if row in pairs and not texts and not below and row + 1 < len(centers):
            units.append(Unit((row, row + 1)))
            row += 2
            continue
        prefix = [*shared.get(row - 1, []), *between] if texts else []
        label = parse_name(" ".join(texts), ocr) if texts else None
        if prefix and (label is None or label.family is None):
            label = parse_name(" ".join([*prefix, *texts]), ocr) or label
        units.append(Unit((row,), label))
        row += 1
    return units


# ---- roster ------------------------------------------------------------------------------------


@dataclass
class Instrument:
    name: Name  # the fullest label seen
    staves: int = 1
    names: list[Name] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.name.text

    def likeness(self, label: Name) -> float:
        return max(similarity(label, name) for name in self.names)

    def add(self, unit: Unit) -> None:
        assert unit.label is not None
        self.staves = max(self.staves, len(unit.rows))
        if unit.label not in self.names:
            self.names.append(unit.label)
            if len("".join(unit.label.words)) > len("".join(self.name.words)):
                self.name = unit.label


def _align(labels: list[Name | None], roster: list[Instrument]) -> list[int | None]:
    """The best order-preserving match of labels with the roster, only of labels that are alike."""
    n, m = len(labels), len(roster)
    score = [[0.0] * m for _ in range(n)]
    for i, label in enumerate(labels):
        for j in range(m) if label else ():
            likeness = roster[j].likeness(label)
            # An exactly equal label beats a similar one, e.g. "Vc. II" the plain "Vc."
            score[i][j] = likeness if likeness >= MIN_MATCH else 0.0
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            take = best[i + 1][j + 1] + score[i][j] if score[i][j] else 0.0
            best[i][j] = max(take, best[i + 1][j], best[i][j + 1])
    result: list[int | None] = [None] * n
    i = j = 0
    while i < n and j < m:
        if score[i][j] and abs(best[i][j] - (best[i + 1][j + 1] + score[i][j])) < 1e-9:
            result[i] = j
            i, j = i + 1, j + 1
        elif abs(best[i][j] - best[i][j + 1]) < 1e-9:
            j += 1
        else:
            i += 1
    return result


def build_roster(systems: list[list[Unit]]) -> list[Instrument]:
    """All instruments of the score in order. Starts from the fullest system and adds those that join elsewhere."""
    seen = Counter((u.label.words, u.label.numbers) for system in systems for u in system if u.label)
    labelled = [s for s in systems if any(u.label for u in s)]
    if not labelled:
        return []
    start = max(labelled, key=lambda s: sum(u.label is not None for u in s))
    roster: list[Instrument] = []
    for system in [start, *(s for s in labelled if s is not start)]:
        matched = _align([u.label for u in system], roster)
        for unit, at in zip(system, matched):
            if unit.label and at is not None:
                roster[at].add(unit)
        # New instruments go between the neighbours they are printed with
        position = 0
        shift = 0
        for k, (unit, at) in enumerate(zip(system, matched)):
            if at is not None:
                position = at + shift + 1
                continue
            label = unit.label
            if label is None or (label.family is None and seen[label.words, label.numbers] < 2 and system is not start):
                continue  # more likely a stray word than an instrument
            following = next((a + shift for a in matched[k + 1 :] if a is not None), len(roster))
            while position < following and _comes_before(roster[position].name, label):
                position += 1
            roster.insert(position, Instrument(label, len(unit.rows), [label]))
            position += 1
            shift += 1
    return roster


def _comes_before(a: Name, b: Name) -> bool:
    """Usual score order, for an instrument whose printed neighbours leave its place open."""
    if a.family is None or b.family is None:
        return True
    if a.family == b.family:
        return min(a.numbers, default=0) <= min(b.numbers, default=0)
    return _ORDER[a.family] < _ORDER[b.family]


@dataclass
class Placement:
    """Where the units of a system go: an index into the roster, or None."""

    parts: list[int | None]
    by_position: list[int]  # units without a label of their own, placed because only one place was left


def place(systems: list[list[Unit]], roster: list[Instrument]) -> list[Placement]:
    result: list[Placement] = []
    previous: tuple[tuple[int, ...], list[int | None]] | None = None
    for system in systems:
        parts = _align([u.label for u in system], roster)
        by_position: list[int] = []
        shape = tuple(len(u.rows) for u in system)
        if not any(u.label for u in system):
            if previous and previous[0] == shape:  # printed without labels because nothing changed
                parts = list(previous[1])
                by_position = [k for k, p in enumerate(parts) if p is not None]
            elif shape == tuple(i.staves for i in roster):
                parts = list(range(len(roster)))
                by_position = list(parts)
        else:
            by_position = _fill_gaps(system, parts, roster)
        result.append(Placement(parts, by_position))
        previous = (shape, parts)
    return result


def _fill_gaps(system: list[Unit], parts: list[int | None], roster: list[Instrument]) -> list[int]:
    """Place staves without labels where the placed staves around them leave exactly as many instruments."""
    filled: list[int] = []
    k = 0
    while k < len(system):
        if parts[k] is not None:
            k += 1
            continue
        end = k
        while end < len(system) and parts[end] is None:
            end += 1
        low = parts[k - 1] + 1 if k else 0  # type: ignore[operator]
        high = parts[end] if end < len(system) else len(roster)
        assert high is not None
        run = system[k:end]
        free = list(range(low, high))
        if not any(u.label for u in run) and [len(u.rows) for u in run] == [roster[j].staves for j in free]:
            parts[k:end] = free
            filled += range(k, end)
        k = end
    return filled


def to_dict(roster: list[Instrument]) -> list[dict[str, Any]]:
    return [{"name": i.title, "staves": i.staves, "labels": [n.text for n in i.names]} for i in roster]


def unusual_clef(title: str, clef: str) -> bool:
    """Whether an instrument rarely has this clef, such as "C3". Always False for instruments not known here."""
    name = parse_name(title)
    usual = _CLEFS.get(name.family or "") if name else None
    return bool(usual) and clef not in usual


def written_range(title: str) -> tuple[int, int] | None:
    """The lowest and highest written note (MIDI numbers) an instrument plausibly has, or None if not known here."""
    name = parse_name(title)
    return _RANGES.get(name.family or "") if name else None
