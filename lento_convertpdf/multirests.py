"""Runs inside homr's environment (loaded by homr_bridge.py): reads the number printed above a whole-bar rest.

A part often shows "12" above one bar of rest instead of twelve bars. homr's reader usually takes this for a single
bar of rest (it only knows multi-bar rests of 2 to 10 bars, and often misses those too), so the part comes out
short and drifts away from the other parts. Here the strip above each lone bar of rest is read with homr's own
text reader (RapidOCR). Where it finds a number, the rest becomes rest_<N>m, which homr's MusicXML writer lays out
as N bars.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

MEASURE_ENDS = ("barline", "doublebarline", "bolddoublebarline", "newline")
MAX_BARS = 999
# homr places a rest a little left of where the number is printed: how far off centre a number may be, in staff spaces
MAX_OFFSET = 4.0


def _is_end(rhythm: str) -> bool:
    return rhythm in MEASURE_ENDS or "repeat" in rhythm


def _is_sounding(rhythm: str) -> bool:
    return rhythm.startswith(("note", "rest")) or rhythm == "measureRest"


def lone_rests(symbols: Sequence[Any]) -> list[int]:
    """Positions of rests that fill a bar on their own: the only note or rest between two bar lines."""
    found: list[int] = []
    bar: list[int] = []

    def close() -> None:
        if len(bar) == 1:
            rhythm = symbols[bar[0]].rhythm
            if rhythm == "measureRest" or rhythm.startswith("rest_"):
                found.append(bar[0])
        bar.clear()

    for i, symbol in enumerate(symbols):
        if _is_end(symbol.rhythm):
            close()
        elif _is_sounding(symbol.rhythm):
            bar.append(i)
    close()
    return found


def pick_number(texts: Sequence[tuple[float, float, float, float, str]], center_x: float, unit: float) -> int | None:
    """The bar count among text boxes (x0, y0, x1, y1, text) read above a rest, centred on center_x.

    Multi-bar rest numbers are printed in the large time-signature digits, so a box must be well over one staff
    space tall; that keeps out fingerings and the small bar numbers at the start of a line. The closest one to
    center_x wins, within MAX_OFFSET staff spaces."""
    best: tuple[float, int] | None = None
    for x0, y0, x1, y1, text in texts:
        digits = text.strip().replace(" ", "")
        if not re.fullmatch(r"\d{1,3}", digits):
            continue
        n, height = int(digits), y1 - y0
        if not 2 <= n <= MAX_BARS or height < 1.2 * unit:
            continue
        if x1 - x0 > 0.95 * height * len(digits):
            continue  # wider than digits are: a fermata, which the text reader takes for a "3"
        off = abs((x0 + x1) / 2 - center_x)
        if off <= MAX_OFFSET * unit and (best is None or off < best[0]):
            best = (off, n)
    return best[1] if best else None


def _staff_at(staffs: Sequence[Any], x: float, y: float) -> Any | None:
    """The staff (page coordinates) that a symbol at (x, y) sits on."""
    best = None
    for staff in staffs:
        unit = staff.average_unit_size
        if not staff.min_x - unit <= x <= staff.max_x + unit:
            continue
        if not staff.min_y - 4 * unit <= y <= staff.max_y + 4 * unit:
            continue
        gap = abs((staff.min_y + staff.max_y) / 2 - y)
        if best is None or gap < best[0]:
            best = (gap, staff)
    return best[1] if best else None


def _inverse(mapping: Callable[[tuple[float, float]], tuple[float, float]]) -> Callable[[float, float], tuple[float, float]]:
    """homr maps page points to the input image by scaling and shifting; undo that."""
    (ax, ay), (bx, by) = mapping((0.0, 0.0)), mapping((1000.0, 1000.0))
    sx, sy = (bx - ax) / 1000.0 or 1.0, (by - ay) / 1000.0 or 1.0
    return lambda x, y: ((x - ax) / sx, (y - ay) / sy)


def _read(reader: Any, image: Any, staff: Any, x: float) -> int | None:
    import cv2
    import numpy as np

    unit = float(staff.average_unit_size)
    point = staff.get_at(x)
    top = float(min(point.y)) if point is not None else float(staff.min_y)
    y0, y1 = max(0, int(top - 6 * unit)), max(0, int(top - 0.2 * unit))
    x0, x1 = max(0, int(x - (MAX_OFFSET + 2) * unit)), min(image.shape[1], int(x + (MAX_OFFSET + 3) * unit))
    if y1 - y0 < unit or x1 - x0 < unit:
        return None
    crop = image[y0:y1, x0:x1]
    scale = max(1.0, 20.0 / unit)  # the text detector misses digits that are only a few pixels tall
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    pad = 20
    crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    result = reader(crop)
    if getattr(result, "boxes", None) is None or result.txts is None:
        return None
    texts = []
    for box, text in zip(result.boxes, result.txts):
        xs, ys = (np.asarray(box)[:, 0] - pad) / scale, (np.asarray(box)[:, 1] - pad) / scale
        texts.append((float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()), str(text)))
    return pick_number(texts, x - x0, unit)


def expand(debug: Any, voices: list[list[Any]], rows: Sequence[Any], to_input: Any, reader: Any) -> list[int]:
    """Turn lone bar rests with a number above them into multi-bar rests. Returns the numbers found."""
    if reader is None or debug is None or getattr(debug, "original_image", None) is None:
        return []
    image = debug.original_image
    staffs = [staff for row in rows for staff in row.staffs]
    to_page = _inverse(to_input) if to_input is not None else (lambda x, y: (x, y))
    found: list[int] = []
    for symbols in voices:
        for i in lone_rests(symbols):
            symbol = symbols[i]
            if symbol.image_coordinates is None:
                continue
            x, y = to_page(*symbol.image_coordinates)
            staff = _staff_at(staffs, x, y)
            if staff is None:
                continue
            n = _read(reader, image, staff, x)
            if n:
                symbol.rhythm = f"rest_{n}m"
                found.append(n)
    return found
