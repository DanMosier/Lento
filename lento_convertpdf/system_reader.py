"""Read a full score one system at a time. Runs inside homr's environment, started by homr_bridge.py.

homr reads a page across its systems, which needs the same instruments in each. Where instruments come and go it
loses track of them. Here homr still finds the staves, groups them into systems and reads every staff with its own
models; only the bookkeeping is different: labels say which instrument a staff is (instruments.py), and the systems
are joined instrument by instrument (system_merge.py).
"""

from __future__ import annotations

import ctypes
import dataclasses
import xml.etree.ElementTree as ET
from typing import Any

import cv2
import homr.main as homr_main
import homr.staff_parsing as parsing
import instruments as ins
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import system_merge as sm
from homr import title_detection
from homr.debug import Debug
from homr.model import MultiStaff, Staff, StaffPoint
from homr.music_xml_generator import generate_xml
from homr.simple_logging import eprint
from homr.staff_regions import StaffRegions
from homr.system_repair import repair_systems
from homr.transformer.configs import Config

MIN_LABELLED = 0.5  # share of systems that need a label, or there is too little to go by
Crop = tuple[int, int, int, int]  # where homr's image starts on the rendered page, and the size of that page


@dataclasses.dataclass
class FoundSystem:
    page: int
    number: int
    units: list[ins.Unit]
    staffs: list[Staff]  # one per unit
    right: float  # where the system ends in the page image


@dataclasses.dataclass
class FoundPage:
    image: Any
    mapping: Any
    systems: list[FoundSystem]


def read(images: list[str], pdf: str, crops: list[Crop], config: Any, args: Any, trace: dict, out: str) -> bool:
    """Write the score to out. Returns False, with nothing written, if there are too few labels to go by."""
    pages: list[FoundPage] = []
    title_future = None
    labels = PageLabels(pdf, crops)
    for number, path in enumerate(images, start=1):
        eprint("Finding the systems of page", number)
        # homr only keeps the title of the first page
        page_config = dataclasses.replace(config, title_detection=config.title_detection and number == 1)
        multi, image, debug, future, _, mapping = homr_main.detect_staffs_in_image(path, page_config)
        title_future = title_future or future
        multi = repair_systems(debug, multi)
        pages.append(FoundPage(image, mapping, find_systems(number, path, multi, mapping, labels)))

    found = [system for page in pages for system in page.systems]
    units = [system.units for system in found]
    labelled = sum(any(u.label for u in system) for system in units)
    roster = ins.build_roster(units)
    trace["labels"] = {
        "systems": len(found),
        "labelled": labelled,
        "source": sorted(labels.used),
        "found": [[s.page, s.number, [u.label.text if u.label else None for u in s.units]] for s in found],
    }
    if len(roster) < 2 or labelled < MIN_LABELLED * len(found):
        return False
    placements = iter(ins.place(units, roster))
    eprint("Reading", len(found), "systems of", [i.title for i in roster])

    transformer = Config()
    transformer.use_gpu_inference = config.transformer_use_gpu
    transformer.use_coreml_encoder = config.coreml_encoder
    systems: list[sm.System] = []
    meter: sm.Meter | None = None
    for number, page in enumerate(pages, start=1):
        sizes = [len(s.staffs) for s in page.systems]
        trace["pages"].append({"page": number, "reads": [], "systems": sizes, "flattened": False})
        regions = StaffRegions([MultiStaff(s.staffs, []) for s in page.systems])
        debug = Debug(page.image, images[number - 1], False)
        for system in page.systems:
            result = read_system(system, next(placements), page, regions, debug, transformer, args, meter)
            systems.append(result)
            meters = sm.vote_meters(result, sm.measure_count(result), meter)
            meter = meters[-1] if meters else meter

    title = title_future.result(60) if title_future else ""
    root, trace["by_system"] = sm.merge(systems, ins.to_dict(roster), title)
    ET.ElementTree(root).write(out, encoding="UTF-8", xml_declaration=True)
    return True


def find_systems(page: int, path: str, multi: list[MultiStaff], mapping: Any, labels: PageLabels) -> list[FoundSystem]:
    found: list[FoundSystem] = []
    for system in multi:
        rows: list[Staff] = []
        pairs: dict[int, Staff] = {}  # upper row -> the pair homr found
        for staff in join_pieces(system.staffs):
            halves = staff.split() if staff.is_grandstaff else None
            if halves:
                pairs[len(rows)] = staff
                rows += halves
            else:
                rows.append(staff)
        complete = [complete_staff(row, rows) for row in rows]
        for k in list(pairs):
            if complete[k] is not rows[k] or complete[k + 1] is not rows[k + 1]:
                pairs[k] = complete[k].merge(complete[k + 1])
        rows = complete
        corners = [(*mapping((s.min_x, s.min_y)), *mapping((s.max_x, s.max_y))) for s in rows]
        left, top, right, bottom = (f(c[k] for c in corners) for k, f in enumerate((min, min, max, max)))
        height = float(np.median([c[3] - c[1] for c in corners]))
        # At the left end, where the labels are: a scanned page may be skewed
        centers = [mapping((s.grid[0].x, float(np.mean(s.grid[0].y))))[1] for s in rows]
        blocks, ocr = labels.beside(page, path, left, top - height, bottom + height)
        units = ins.label_units(centers, set(pairs), blocks, ocr)
        staffs = []
        for unit in units:
            first = rows[unit.rows[0]]
            if len(unit.rows) == 2:
                first = pairs.get(unit.rows[0]) or first.merge(rows[unit.rows[1]])
            staffs.append(first)
        found.append(FoundSystem(page, len(found) + 1, units, staffs, right))
    return found


def complete_staff(staff: Staff, rows: list[Staff]) -> Staff:
    """Extend a staff that was only found in part: all staves of a system are equally wide.

    The missing end follows the bends of the widest staff.
    """
    left = float(np.median([r.min_x for r in rows]))
    right = float(np.median([r.max_x for r in rows]))
    model = max(rows, key=lambda r: r.max_x - r.min_x)
    tolerance = 3 * staff.average_unit_size
    grid = list(staff.grid)
    for missing, edge, at in (
        ([p for p in model.grid if p.x < staff.min_x], grid[0], 0),
        ([p for p in model.grid if p.x > staff.max_x], grid[-1], len(grid)),
    ):
        short = staff.min_x - left if at == 0 else right - staff.max_x
        if short <= tolerance or not missing:
            continue
        nearest = min(model.grid, key=lambda p: abs(p.x - edge.x))
        ends = [p for p in missing if left - tolerance <= p.x <= right + tolerance]
        shift = [float(np.mean(p.y) - np.mean(nearest.y)) for p in ends]
        added = [StaffPoint(p.x, [y + d for y in edge.y], p.angle) for p, d in zip(ends, shift, strict=True)]
        grid = [*added, *grid] if at == 0 else [*grid, *added]
    if len(grid) == len(staff.grid):
        return staff
    eprint("Extending a staff from", staff.min_x, staff.max_x, "to", grid[0].x, grid[-1].x)
    result = Staff(grid)
    result.symbols = staff.symbols
    return result


def join_pieces(staffs: list[Staff]) -> list[Staff]:
    """Join the pieces of a staff that was found in two parts beside each other."""
    result: list[Staff] = []
    for staff in sorted(staffs, key=lambda s: s.min_y):
        for k, other in enumerate(result):
            beside = staff.min_x > other.max_x or other.min_x > staff.max_x
            overlap = min(staff.max_y, other.max_y) - max(staff.min_y, other.min_y)
            if beside and overlap > 0.6 * (staff.max_y - staff.min_y) and staff.is_grandstaff == other.is_grandstaff:
                joined = Staff(sorted([*other.grid, *staff.grid], key=lambda p: p.x))
                joined.symbols = [*other.symbols, *staff.symbols]
                joined.is_grandstaff = staff.is_grandstaff
                result[k] = joined
                break
        else:
            result.append(staff)
    return sorted(result, key=lambda s: s.min_y)


def read_system(
    system: FoundSystem,
    placement: ins.Placement,
    page: FoundPage,
    regions: StaffRegions,
    debug: Debug,
    config: Config,
    args: Any,
    meter: sm.Meter | None,
) -> sm.System:
    result = sm.System(system.page, system.number)
    voices, owners, ends = [], [], []
    for k, staff in enumerate(system.staffs):
        symbols = parsing.parse_staff_image(debug, k, staff, page.image, regions, config, page.mapping)
        voice = parsing._clean_up_voice([*symbols, parsing.EncodedSymbol("newline")]) if symbols else []
        if any(_is_music(s) for s in voice):
            voices.append(voice)
            owners.append(k)
            ends.append(measure_ends(symbols, system.right))
        elif (index := placement.parts[k]) is not None:
            result.unread.append(index)
    if not voices:
        return result
    xml = generate_xml(args, voices, "", [meter] * len(voices))
    for part, k, end in zip(xml.findall("part"), owners, ends, strict=True):
        measures = part.findall("measure")
        reading = sm.Read(measures, end if end and len(end) == len(measures) else None)
        index = placement.parts[k]
        if index is None:
            result.unplaced.append((k + 1, reading))
            continue
        result.reads[index] = reading
        if k in placement.by_position:
            result.by_position.append(index)
    return result


def _is_music(symbol: Any) -> bool:
    return symbol.rhythm.startswith(("note", "rest", "measureRest"))


def measure_ends(symbols: list[Any], right: float) -> list[float] | None:
    """Where the barlines stand that end a measure. None if homr could not say."""
    ends: list[float] = []
    music = False
    for symbol in symbols:
        if _is_music(symbol):
            music = True
        elif music and ("barline" in symbol.rhythm or "repeat" in symbol.rhythm):
            if symbol.image_coordinates is None:
                return None
            ends.append(symbol.image_coordinates[0])
            music = False
    return [*ends, right] if music else ends


class PageLabels:
    """The text to the left of the staves: from the PDF itself, or by OCR if it is a scan.

    All coordinates are those of homr's image of the page.
    """

    def __init__(self, pdf: str, crops: list[Crop]) -> None:
        self.document = pdfium.PdfDocument(pdf)
        self.crops = crops
        self.used: set[str] = set()
        self._page = 0
        self._chars: list[ins.Text] = []
        self._image: Any = None

    def beside(self, page: int, path: str, left: float, top: float, bottom: float) -> tuple[list[ins.Text], bool]:
        """The labels left of a system, and whether they come from OCR."""
        if page != self._page:
            self._page, self._chars, self._image = page, self._from_pdf(page), None
        chars = [c for c in self._chars if c.x1 <= left + 2 and c.y1 > top and c.y0 < bottom]
        if any(c.text.isalpha() for c in chars):
            self.used.add("text")
            return ins.text_blocks(ins.text_lines(chars)), False
        if self._image is None:
            self._image = cv2.imread(path)
        texts = self._from_image(left, top, bottom)
        if texts:
            self.used.add("ocr")
        return ins.text_blocks(texts), True

    def _from_pdf(self, number: int) -> list[ins.Text]:
        if number > len(self.document) or number > len(self.crops):
            return []
        page = self.document[number - 1]
        text_page = page.get_textpage()
        x0, y0, width, height = self.crops[number - 1]

        def to_image(x: float, y: float) -> tuple[float, float]:
            px, py = ctypes.c_int(), ctypes.c_int()
            # At ten times the size, because pdfium answers in whole pixels
            pdfium_raw.FPDF_PageToDevice(page, 0, 0, width * 10, height * 10, 0, x, y, px, py)
            return px.value / 10 - x0, py.value / 10 - y0

        found = []
        for k in range(text_page.count_chars()):
            char = text_page.get_text_range(k, 1)
            if not char.strip() or not char.isprintable() or 0xE000 <= ord(char[0]) <= 0xF8FF:  # music symbols
                continue
            left, bottom, right, top = text_page.get_charbox(k)
            (ax, ay), (bx, by) = to_image(left, top), to_image(right, bottom)
            found.append(ins.Text(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), char))
        return found

    def _from_image(self, left: float, top: float, bottom: float, tile: int = 700, overlap: int = 200) -> list[ins.Text]:
        reader = title_detection._reader
        if reader is None or self._image is None or left < 20:
            return []
        found: list[ins.Text] = []
        pad = 20  # OCR expects text with some paper around it
        start, end = max(0, int(top)), min(self._image.shape[0], int(bottom))
        for y in range(start, end, tile - overlap):
            margin = self._image[y : min(end, y + tile), : int(left)]
            padded = cv2.copyMakeBorder(margin, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            result = reader(padded)
            if getattr(result, "boxes", None) is None or result.txts is None:
                continue
            for box, text in zip(result.boxes, result.txts, strict=True):
                xs, ys = np.asarray(box)[:, 0] - pad, np.asarray(box)[:, 1] - pad
                cut = (y > start and ys.min() < 3) or (y + tile < end and ys.max() > tile - 3)
                new = ins.Text(float(xs.min()), float(ys.min()) + y, float(xs.max()), float(ys.max()) + y, text)
                if not cut and not any(_same_spot(new, old) for old in found):
                    found.append(new)
        return found


def _same_spot(a: ins.Text, b: ins.Text) -> bool:
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * (a.y1 - a.y0) and a.x0 < b.x1 and b.x0 < a.x1
