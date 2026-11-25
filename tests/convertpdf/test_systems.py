"""Tests for reading full scores system by system: matching staves with instruments, and joining the systems."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from lento_convertpdf import instruments as ins
from lento_convertpdf import system_merge as sm
from lento_convertpdf.quality import assess

ORCHESTRA = [
    "Flauti", "Oboi", "Clarinetti in B", "Fagotti", "Corni in F I II", "Corni in F III IV", "Trombe in B", "Tromboni I II",
    "Trombono III", "Tuba", "Timpani in G.As.C", "Piano", "Violino I", "Violino II", "Viola", "Violoncello", "Basso",
]  # fmt: skip


def system(*labels: str) -> list[ins.Unit]:
    """A system with these labels from top to bottom. 'Piano' gets two staves, '' has no label."""
    units, row = [], 0
    for label in labels:
        name = ins.parse_name(label)
        size = 2 if (name and name.family == "piano") or label == "=" else 1
        units.append(ins.Unit(tuple(range(row, row + size)), None if label in ("", "=") else name))
        row += size
    return units


def placed(roster: list[ins.Instrument], *labels: str) -> list[str | None]:
    (placement,) = ins.place([system(*labels)], roster)
    return [None if k is None else roster[k].title for k in placement.parts]


# ---- names -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "family", "numbers"),
    [
        ("Corni in F III IV", "horn", {3, 4}),
        ("Timpani in G.As.C", "timpani", set()),
        ("B.", "double bass", set()),
        ("Vl. II", "violin", {2}),
        ("2nd Violins", "violin", {2}),
        ("B♭ Clarinet 1", "clarinet", {1}),
        ("F Horn 3", "horn", {3}),
        ("Flöten", "flute", set()),
        ("Vc. div.", "cello", set()),
        ("VI. l", "violin", {1}),  # "Vl. I" as OCR reads it
        ("Bass Clarinet", "bass clarinet", set()),
        ("English Horn", "english horn", set()),
        ("Glass Harmonica", None, set()),
    ],
)
def test_labels_are_understood(text, family, numbers):
    name = ins.parse_name(text)
    assert name is not None and name.family == family and name.numbers == numbers


@pytest.mark.parametrize("text", ["12", "I", "", "♩ = 60"])
def test_text_that_names_nothing(text):
    assert ins.parse_name(text) is None


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Flauti", "Fl.", True),
        ("Tromboni I II", "Tbni. I II", True),
        ("Violoncello", "Vc. I", True),
        ("Violoncello", "Vc. II", False),
        ("Vl. I", "Vl. II", False),
        ("Vl. I", "Vla.", False),
        ("Tr.", "Tbni. I II", False),
        ("Cor. I II", "Cor. III IV", False),
        ("Glass Harmonica", "Gl. Harm.", True),  # not in the list of families
    ],
)
def test_similarity(a, b, same):
    x, y = ins.parse_name(a), ins.parse_name(b)
    assert x and y and (ins.similarity(x, y) >= ins.MIN_MATCH) is same


# ---- labels beside staves ----------------------------------------------------------------------


def block(y: float, text: str) -> ins.Text:
    return ins.Text(0, y - 5, 40, y + 5, text)


def test_characters_become_lines_and_blocks():
    def chars(text: str, x: float, y: float) -> list[ins.Text]:
        found = []
        for c in text:
            if c != " ":
                found.append(ins.Text(x, y, x + 5, y + 10, c))
            x += 5.5
        return found

    page = chars("17", 40, 0) + chars("Cor.", 10, 30) + chars("I II", 12, 46) + chars("Pno.", 10, 120)
    blocks = ins.text_blocks(ins.text_lines(page))
    assert [b.text for b in blocks] == ["Cor. I II", "Pno."]  # not "III", and no measure number


def test_label_beside_each_staff_undoes_a_pair_of_two_instruments():
    units = ins.label_units([100, 200, 300, 400], {0, 2}, [block(100, "Cor. I II"), block(200, "Cor. III IV"), block(350, "Pno.")])
    assert [u.rows for u in units] == [(0,), (1,), (2, 3)]
    assert [u.label.text for u in units if u.label] == ["Cor. I II", "Cor. III IV", "Pno."]


def test_missed_brace_is_found_by_the_label_between_the_staves():
    units = ins.label_units([100, 200, 300], set(), [block(100, "Vl."), block(250, "Pno.")])
    assert [u.rows for u in units] == [(0,), (1, 2)]


def test_shared_label_names_both_staves():
    units = ins.label_units([100, 200], set(), [block(150, "Violins"), block(100, "I"), block(200, "II")])
    assert [(u.label.family, u.label.numbers) for u in units if u.label] == [("violin", {1}), ("violin", {2})]


def test_staff_without_a_label_stays_without():
    units = ins.label_units([100, 200, 300], set(), [block(100, "Fl."), block(300, "B.")])
    assert [u.label is None for u in units] == [False, True, False]


def test_text_between_systems_is_not_a_label():
    assert ins.label_units([100, 200], set(), [block(30, "Allegro")])[0].label is None


# ---- roster and placement ----------------------------------------------------------------------


def test_hidden_instruments_are_placed_by_label():
    roster = ins.build_roster([system(*ORCHESTRA), system("Cl.", "Pno.", "Vl. I", "Vl. II", "Vla.", "Vc.", "B.")])
    assert [i.title for i in roster] == ORCHESTRA
    assert placed(roster, "Cl.", "Cor. III IV", "Pno.", "B.") == ["Clarinetti in B", "Corni in F III IV", "Piano", "Basso"]


def test_instruments_that_join_later_get_their_place():
    roster = ins.build_roster([system(*ORCHESTRA), system("Ob.", "Cl. I", "Cl. II", "Fag.", "Vc. I", "Vc. II", "B.")])
    titles = [i.title for i in roster]
    assert titles[titles.index("Clarinetti in B") + 1] == "Cl. II"
    assert titles[titles.index("Violoncello") + 1] == "Vc. II"
    assert len(roster) == len(ORCHESTRA) + 2
    assert placed(roster, "Vc.", "B.") == ["Violoncello", "Basso"]


def test_usual_score_order_decides_where_neighbours_do_not():
    roster = ins.build_roster([system("Fl.", "Cl.", "Vl. I", "Vc."), system("Ob.", "Vc.")])
    assert [i.title for i in roster] == ["Fl.", "Ob.", "Cl.", "Vl. I", "Vc."]


def test_stray_word_is_not_an_instrument():
    roster = ins.build_roster([system("Fl.", "Vl. I", "Vc."), system("Fl.", "con sord", "Vc.")])
    assert len(roster) == 3


def test_unlabelled_staff_is_placed_only_if_one_place_is_left():
    roster = ins.build_roster([system("Fl.", "Ob.", "Pno.", "Vl. I", "Vl. II", "Vc.")])
    assert placed(roster, "Fl.", "", "Pno.", "Vl. I", "Vc.") == ["Fl.", "Ob.", "Pno.", "Vl. I", "Vc."]
    assert placed(roster, "Fl.", "Pno.", "", "Vc.") == ["Fl.", "Pno.", None, "Vc."]  # which violin?
    assert placed(roster, "Fl.", "=", "Vl. I", "Vl. II", "Vc.") == ["Fl.", None, "Vl. I", "Vl. II", "Vc."]  # 1 staff or 2?


def test_ocr_may_read_one_and_two_as_three():
    horns = ["Corni in F I II", "Corni in F III IV"]
    roster = ins.build_roster([system(*horns)])
    read = [ins.Unit((k,), ins.parse_name(text, ocr=True)) for k, text in enumerate(["Cor. III", "Cor. III IV"])]
    assert len(ins.build_roster([system(*horns), read])) == 2
    assert ins.place([read], roster)[0].parts == [0, 1]
    printed = [ins.Unit((0,), ins.parse_name("Cor. III"))]  # from the PDF's own text it is what it says
    assert ins.place([printed], roster)[0].parts == [1]


def test_unknown_label_is_not_forced_into_a_gap():
    roster = ins.build_roster([system("Fl.", "Ob.", "Vc.")])
    assert placed(roster, "Fl.", "Xyz.", "Vc.") == ["Fl.", None, "Vc."]


def test_system_without_labels_continues_the_one_before():
    roster = ins.build_roster([system("Fl.", "Ob.", "Vc."), system("Fl.", "Vc.")])
    _, second, third, fourth = ins.place([system("Fl.", "Ob.", "Vc."), system("Fl.", "Vc."), system("", ""), system("")], roster)
    assert third.parts == second.parts == [0, 2] and third.by_position == [0, 1]
    assert fourth.parts == [None]  # another layout: no way to know


# ---- joining -----------------------------------------------------------------------------------


def bar(*pitches: str, duration: int = 1, staff: int = 1) -> str:
    return "".join(
        f"<note><pitch><step>{p}</step><octave>4</octave></pitch><duration>{duration}</duration>"
        f"<voice>1</voice><staff>{staff}</staff></note>"
        for p in pitches
    )


def reading(*bars: str, divisions: int = 1, meter: str = "4/4", key: int = 0, ends: list[float] | None = None) -> sm.Read:
    beats, kind = meter.split("/")
    first = (
        f"<attributes><divisions>{divisions}</divisions><key><fifths>{key}</fifths></key><time><beats>{beats}</beats>"
        f"<beat-type>{kind}</beat-type></time><clef number='1'><sign>G</sign><line>2</line></clef></attributes>"
    )
    bars = (first + bars[0], *bars[1:])
    return sm.Read([ET.fromstring(f"<measure>{b}</measure>") for b in bars], ends)


def parts(count: int, two_staves: tuple[int, ...] = ()) -> list[dict]:
    return [{"name": f"I{k}", "staves": 2 if k in two_staves else 1, "labels": [f"I{k}"]} for k in range(count)]


def pitches(root: ET.Element, part: int) -> list[str]:
    measures = root.findall("part")[part].findall("measure")
    return ["".join(s.text or "" for s in m.iter("step")) for m in measures]


FULL = bar("C", "D", "E", "F")


def test_hidden_instrument_rests_and_stays_in_step():
    systems = [
        sm.System(1, 1, {0: reading(FULL, FULL), 1: reading(bar("G", duration=8), FULL.replace("<duration>1", "<duration>2"), divisions=2)}),
        sm.System(1, 2, {0: reading(FULL)}),
        sm.System(1, 3, {1: reading(bar("A", duration=4))}),
    ]
    root, report = sm.merge(systems, parts(2))
    assert pitches(root, 0) == ["CDEF", "CDEF", "CDEF", ""]
    assert pitches(root, 1) == ["G", "CDEF", "", "A"]
    rest = root.findall("part")[1].findall("measure")[2]
    assert rest.find("note/rest") is not None and rest.findtext("note/duration") == "8"  # 4 quarters at 2 divisions
    assert not report["unplaced"] and not report["uneven"]


def test_signatures_in_force_are_not_repeated():
    root, _ = sm.merge([sm.System(1, n, {0: reading(FULL, key=k)}) for n, k in ((1, -3), (2, -3), (3, 2))], parts(1))
    part = root.findall("part")[0]
    assert [k.text for k in part.iter("fifths")] == ["-3", "2"]
    assert len(list(part.iter("time"))) == len(list(part.iter("clef"))) == len(list(part.iter("divisions"))) == 1


def test_misread_meter_is_outvoted_everywhere():
    systems = [sm.System(1, 1, {0: reading(FULL), 1: reading(FULL), 2: reading(FULL, meter="2/4")})]
    root, _ = sm.merge(systems, parts(3))
    assert [t.findtext("beats") for t in root.iter("time")] == ["4", "4", "4"]


def test_meter_change_reaches_hidden_instruments():
    systems = [sm.System(1, 1, {0: reading(FULL), 1: reading(FULL)}), sm.System(1, 2, {0: reading(bar("C", "D", "E"), meter="3/4")})]
    root, _ = sm.merge(systems, parts(2))
    hidden = root.findall("part")[1].findall("measure")[1]
    assert hidden.findtext("attributes/time/beats") == "3" and hidden.findtext("note/duration") == "3"


def test_lost_barline_costs_only_its_own_measures():
    good = [reading(FULL, FULL, FULL, FULL, ends=[100, 200, 300, 400]) for _ in range(2)]
    lost = reading(FULL, bar("G", "G", "A", "A"), bar("B", "B", "B", "B"), ends=[101, 299, 401])
    root, report = sm.merge([sm.System(1, 1, {0: good[0], 1: good[1], 2: lost})], parts(3))
    assert pitches(root, 2) == ["CDEF", "", "GGAA", "BBBB"]
    assert report["uneven"][0]["measures"] == [2, 3]


def test_false_barline_is_joined_again():
    good = [reading(FULL, FULL, ends=[100, 200]) for _ in range(2)]
    split = reading(bar("C", "D"), bar("E", "F"), FULL, ends=[52, 99, 200])
    root, report = sm.merge([sm.System(1, 1, {0: good[0], 1: good[1], 2: split})], parts(3))
    assert pitches(root, 2) == ["CDEF", "CDEF"] and report["uneven"][0]["measures"] == [1]


def test_unplaced_staff_is_kept_apart_and_reported():
    systems = [
        sm.System(1, 1, {0: reading(FULL)}),
        sm.System(2, 1, {0: reading(FULL)}, unplaced=[(2, reading(bar("A", duration=4)))]),
    ]
    root, report = sm.merge(systems, parts(1))
    assert [p.findtext("part-name") for p in root.iter("score-part")] == ["I0", "Unplaced staff 1"]
    assert pitches(root, 0) == ["CDEF", "CDEF"] and pitches(root, 1) == ["", "A"]
    assert report["unplaced"] == [{"page": 2, "system": 1, "staff": 2, "part": "Unplaced staff 1", "measures": [2]}]


def test_two_staff_instrument_shown_on_one_staff():
    both = bar("C", duration=4) + "<backup><duration>4</duration></backup>" + bar("E", duration=4, staff=2)
    root, _ = sm.merge([sm.System(1, 1, {0: reading(both)}), sm.System(1, 2, {0: reading(FULL)})], parts(1, two_staves=(0,)))
    first, second = root.findall("part")[0].findall("measure")
    assert first.findtext("attributes/staves") == "2"
    assert [n.findtext("staff") for n in second.findall("note")] == ["1", "1", "1", "1", "2"]
    assert second.findtext("backup/duration") == "4"


def test_pickup_is_as_short_for_everyone():
    systems = [sm.System(1, 1, {0: reading(bar("C"), FULL), 1: reading("<note><rest/><duration>1</duration></note>", FULL)})]
    root, _ = sm.merge(systems, parts(3))
    assert [p.find("measure").findtext("note/duration") for p in root.findall("part")] == ["1", "1", "1"]


def test_rests_fit_a_meter_that_needs_finer_divisions():
    systems = [sm.System(1, 1, {0: reading(bar("C", "D", "E"), divisions=2, meter="3/8")}), sm.System(1, 2, {0: reading(bar("C", "D", "E"), divisions=2, meter="3/8")})]
    del systems[1].reads[0]
    systems[1].unplaced = [(1, reading(bar("C", "D", "E"), divisions=2, meter="3/8"))]
    root, _ = sm.merge(systems, parts(1))
    for part in root.findall("part"):
        divisions = 0
        for measure in part.findall("measure"):
            divisions = int(measure.findtext("attributes/divisions") or divisions)
            assert Fraction(sum(int(n.findtext("duration")) for n in measure.findall("note")), divisions) == Fraction(3, 2)


def test_system_where_nothing_could_be_read_is_reported():
    _, report = sm.merge([sm.System(1, 1, {0: reading(FULL)}), sm.System(1, 2, unread=[0])], parts(1))
    assert report["unread"][0]["system"] == 2


# ---- flags -------------------------------------------------------------------------------------


def write(root: ET.Element, path: Path) -> Path:
    ET.ElementTree(root).write(path)
    return path


def test_unplaced_staff_is_flagged_in_the_export(tmp_path):
    systems = [sm.System(1, n, {0: reading(*[FULL] * 10), 1: reading(*[FULL] * 10)}) for n in range(1, 21)]
    systems[4].unplaced = [(3, reading(*[FULL] * 10))]
    root, report = sm.merge(systems, parts(2))
    quality = assess(write(root, tmp_path / "a.xml"), {"pages": [], "by_system": json.loads(json.dumps(report))})
    assert quality.level == "review" and quality.by_system
    assert "1 staff could not be matched with an instrument" in quality.summary
    assert quality.suspicious[41] == ["Unplaced staff 1: staff could not be matched with an instrument"]
    assert quality.instruments["I0"] == 1.0


def test_many_unplaced_staves_are_unreliable(tmp_path):
    systems = [sm.System(1, n, {0: reading(FULL)}, unplaced=[(2, reading(FULL))]) for n in range(1, 4)]
    root, report = sm.merge(systems, parts(1))
    assert assess(write(root, tmp_path / "a.xml"), {"pages": [], "by_system": report}).level == "unreliable"


def test_clean_full_score_is_good(tmp_path):
    systems = [sm.System(1, n, {0: reading(FULL), 1: reading(FULL)}) for n in range(1, 4)]
    root, report = sm.merge(systems, parts(2))
    quality = assess(write(root, tmp_path / "a.xml"), {"pages": [], "by_system": report})
    assert quality.level == "good" and "read system by system, 2 instruments" in quality.summary


def test_too_few_labels_is_said(tmp_path):
    root, _ = sm.merge([sm.System(1, 1, {0: reading(FULL)})], parts(1))
    quality = assess(write(root, tmp_path / "a.xml"), {"pages": [{"page": 1, "flattened": True}], "layout_changed": "page 1"})
    assert quality.level == "unreliable" and "too few labels" in quality.summary
