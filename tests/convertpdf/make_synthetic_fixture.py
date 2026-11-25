"""Regenerate tests/fixtures/synthetic: engraved scores whose exact notes are known.

The waltz is for piano. The ensemble hides instruments that rest, so its systems have different staves.

Verovio engraves the MusicXML to SVG and headless Edge prints it to PDF. Run by hand, not by pytest:

    .venv\\Scripts\\python.exe tests\\make_synthetic_fixture.py
"""

from __future__ import annotations

import random
import subprocess
import sys
import tempfile
from pathlib import Path

import verovio
from music21 import chord, clef, key, layout, metadata, meter, note, stream

OUT = Path(__file__).parent.parent / "fixtures" / "synthetic"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
MEASURES = 60

RIGHT = ["D4", "E4", "F#4", "G4", "A4", "B4", "C#5", "D5", "E5", "F#5", "G5"]
LEFT_ROOTS = [("D3", "F#3", "A3"), ("G2", "B2", "D3"), ("A2", "C#3", "E3"), ("B2", "D3", "F#3")]
RHYTHMS = [(1, 1, 1), (1, 0.5, 0.5, 1), (2, 1), (0.5,) * 6, (1.5, 0.5, 1), (3,)]


def build_score() -> stream.Score:
    rng = random.Random(7)
    right, left = stream.PartStaff(id="R"), stream.PartStaff(id="L")
    pos = 4
    for number in range(1, MEASURES + 1):
        m_right, m_left = stream.Measure(number=number), stream.Measure(number=number)
        if number == 1:
            m_right.append([clef.TrebleClef(), key.KeySignature(2), meter.TimeSignature("3/4")])
            m_left.append([clef.BassClef(), key.KeySignature(2), meter.TimeSignature("3/4")])
        for length in rng.choice(RHYTHMS):
            if rng.random() < 0.08:
                m_right.append(note.Rest(quarterLength=length))
                continue
            pos = max(0, min(len(RIGHT) - 1, pos + rng.choice([-2, -1, -1, 1, 1, 2])))
            m_right.append(note.Note(RIGHT[pos], quarterLength=length))
        triad = rng.choice(LEFT_ROOTS)
        if rng.random() < 0.5:
            m_left.append(note.Note(triad[0], quarterLength=1))
            m_left.append(chord.Chord(list(triad[1:]), quarterLength=1))
            m_left.append(chord.Chord(list(triad[1:]), quarterLength=1))
        else:
            m_left.append(chord.Chord(list(triad), quarterLength=3))
        right.append(m_right)
        left.append(m_left)
    score = stream.Score([right, left, layout.StaffGroup([right, left], symbol="brace")])
    score.metadata = metadata.Metadata(title="Synthetic Waltz", composer="Test Fixture")
    return score


# name, abbreviation, clef, lowest and highest pitch
ENSEMBLE = [
    ("Flute", "Fl.", clef.TrebleClef, "D5", "G6"),
    ("Oboe", "Ob.", clef.TrebleClef, "C4", "A5"),
    ("Bassoon", "Bsn.", clef.BassClef, "C2", "D4"),
    ("Horn 1", "Hn. 1", clef.TrebleClef, "C4", "E5"),
    ("Horn 2", "Hn. 2", clef.TrebleClef, "G3", "C5"),
    ("Piano", "Pno.", None, "", ""),
    ("Violin 1", "Vln. 1", clef.TrebleClef, "A4", "E6"),
    ("Violin 2", "Vln. 2", clef.TrebleClef, "A3", "A5"),
    ("Viola", "Vla.", clef.AltoClef, "C3", "D5"),
    ("Cello", "Vc.", clef.BassClef, "C2", "D4"),
    ("Double Bass", "Db.", clef.BassClef, "E2", "C4"),
]
ENSEMBLE_MEASURES = 72
ENSEMBLE_RHYTHMS = [(1, 1, 1, 1), (2, 1, 1), (2, 2), (1, 0.5, 0.5, 2), (4,), (1.5, 0.5, 1, 1)]


def build_ensemble() -> stream.Score:
    rng = random.Random(11)
    score = stream.Score()
    parts: dict[str, list] = {}
    for name, short, own_clef, low, high in ENSEMBLE:
        staves = [(own_clef, low, high)] if own_clef else [(clef.TrebleClef, "C4", "A5"), (clef.BassClef, "E2", "B3")]
        # Everyone plays at first, then in blocks of six measures only some do
        plays = [block < 1 or name == "Piano" or rng.random() < 0.5 for block in range(ENSEMBLE_MEASURES // 6)]
        for k, (staff_clef, bottom, top) in enumerate(staves):
            part = (stream.PartStaff if len(staves) == 2 else stream.Part)(id=f"{name}-{k}")
            part.partName, part.partAbbreviation = name, short
            scale = [p for p in key.Key("G").getPitches(bottom, top)]
            at = len(scale) // 2
            for number in range(1, ENSEMBLE_MEASURES + 1):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.append([staff_clef(), key.KeySignature(1), meter.TimeSignature("4/4")])
                if plays[(number - 1) // 6]:
                    for length in rng.choice(ENSEMBLE_RHYTHMS):
                        at = max(0, min(len(scale) - 1, at + rng.choice([-2, -1, -1, 1, 1, 2])))
                        measure.append(note.Note(scale[at], quarterLength=length))
                else:
                    rest = note.Rest(quarterLength=4)
                    rest.fullMeasure = True
                    measure.append(rest)
                part.append(measure)
            parts.setdefault(name, []).append(part)
            score.insert(0, part)
    score.insert(0, layout.StaffGroup(parts["Piano"], name="Piano", abbreviation="Pno.", symbol="brace"))
    strings = [p for name in ("Violin 1", "Violin 2", "Viola", "Cello", "Double Bass") for p in parts[name]]
    score.insert(0, layout.StaffGroup(strings, symbol="bracket"))
    score.metadata = metadata.Metadata(title="Synthetic Ensemble", composer="Test Fixture")
    return score


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("synthetic_waltz", build_score), ("synthetic_ensemble", build_ensemble)):
        if name in sys.argv[1:] or len(sys.argv) == 1:
            engrave(build(), name)


def engrave(score: stream.Score, name: str) -> None:
    xml = OUT / f"{name}.musicxml"
    score.write("musicxml", fp=str(xml))

    toolkit = verovio.toolkit()
    toolkit.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": 100, "breaks": "auto",
                        "footer": "none", "svgViewBox": True, "condense": "auto"})
    toolkit.loadData(xml.read_text(encoding="utf-8"))
    pages = [toolkit.renderToSVG(i) for i in range(1, toolkit.getPageCount() + 1)]
    html = (
        "<style>@page{size:210mm 297mm;margin:0}body{margin:0}"
        "div{width:210mm;height:296mm;overflow:hidden;page-break-after:always}"
        "div:last-child{page-break-after:auto}svg{width:210mm;height:296mm}</style>"
        + "".join(f"<div>{svg}</div>" for svg in pages)
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        page = Path(tmp) / "score.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}\\profile",
             f"--print-to-pdf={OUT / f'{name}.pdf'}", page.as_uri()],
            check=True, timeout=120, capture_output=True,
        )
    print(f"{len(pages)} page(s) -> {OUT}")


if __name__ == "__main__":
    main()
