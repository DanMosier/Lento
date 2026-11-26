"""Tests for reading the number above a whole-bar rest (multirests.py runs inside homr's environment)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

path = Path(__file__).resolve().parents[2] / "lento_convertpdf" / "multirests.py"
spec = importlib.util.spec_from_file_location("multirests_under_test", path)
mr = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mr)


def sym(rhythm: str, at: tuple[float, float] | None = None):
    return SimpleNamespace(rhythm=rhythm, image_coordinates=at)


def test_only_rests_alone_in_their_bar_count():
    symbols = [
        sym("clef_F4"), sym("measureRest"), sym("barline"),
        sym("note_4"), sym("rest_4"), sym("barline"),
        sym("rest_1"), sym("barline"),
        sym("measureRest"), sym("measureRest"), sym("newline"),
        sym("rest_4m"),
    ]
    assert mr.lone_rests(symbols) == [1, 6, 11]


def test_number_must_be_large_and_over_the_rest():
    unit = 10.0
    texts = [
        (0, 0, 8, 8, "3"),  # a fingering: too small
        (35, 0, 55, 20, "12"),  # the bar count, centred over x=45
        (120, 0, 140, 20, "4"),  # big, but over another bar
        (40, 5, 70, 20, "3"),  # a fermata read as "3": wider than tall
        (40, 0, 50, 20, "pizz."),
    ]
    assert mr.pick_number(texts, 45.0, unit) == 12
    assert mr.pick_number(texts[:1], 45.0, unit) is None
    assert mr.pick_number([(35, 0, 55, 20, "1")], 45.0, unit) is None  # one bar is not a multi-bar rest
    assert mr.pick_number([(72, 0, 84, 20, "13")], 45.0, unit) == 13  # printed 3.3 spaces right of the rest


class Staff:
    min_x, max_x, min_y, max_y, average_unit_size = 0.0, 400.0, 100.0, 140.0, 10.0

    def get_at(self, x):
        return SimpleNamespace(y=[100.0, 110.0, 120.0, 130.0, 140.0])


class Reader:
    """Stands in for RapidOCR: '8' printed above the staff, centred on the given page x."""

    def __init__(self):
        self.crops = []

    def __call__(self, crop):
        self.crops.append(crop.shape)
        h, w = crop.shape[:2]
        # crop is x 140..270 of the page, scaled 2x, padded 20: page x=200 is at 20 + 2 * 60 = 140
        box = [[130, 30], [150, 30], [150, 75], [130, 75]]
        return SimpleNamespace(boxes=[box], txts=["8"])


def test_expand_turns_the_rest_into_a_multirest():
    pytest.importorskip("cv2")
    debug = SimpleNamespace(original_image=np.full((300, 400), 255, np.uint8))
    rest = sym("measureRest", at=(400.0, 240.0))  # input image is twice the page size
    voices = [[sym("note_4", (100, 240)), sym("barline"), rest, sym("barline")]]
    rows = [SimpleNamespace(staffs=[Staff()])]
    found = mr.expand(debug, voices, rows, lambda p: (p[0] * 2, p[1] * 2), Reader())
    assert found == [8] and rest.rhythm == "rest_8m"
    assert voices[0][0].rhythm == "note_4"


def test_no_reader_changes_nothing():
    rest = sym("measureRest", at=(10.0, 10.0))
    assert mr.expand(SimpleNamespace(original_image=None), [[rest]], [], None, None) == []
    assert rest.rhythm == "measureRest"
