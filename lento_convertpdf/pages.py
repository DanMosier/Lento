"""Pages of a PDF that hold music.

OMR engines give up on a whole PDF when one page has no staff: homr with "No staffs found", Audiveris with
"No system found". Title pages, blank pages and library stamps are common in scanned parts, so the converters
retry with only the pages that show staves.
"""

from __future__ import annotations

from pathlib import Path


STRIPS = 12
DPI = 100


def _line_rows(strip) -> list[int]:
    """Centres of the dark horizontal lines across a narrow vertical strip of the page."""
    from PIL import ImageFilter

    # ink thickened by a pixel each way, so that a slightly sloping line still covers its rows
    ink = strip.point(lambda v: 255 if v < 160 else 0).filter(ImageFilter.MaxFilter(3))
    dark = ink.resize((1, strip.height), resample=_box())
    rows = [dark.getpixel((0, y)) >= 128 for y in range(strip.height)]  # half the strip's width is ink
    centres, y = [], 0
    while y < len(rows):
        if rows[y]:
            start = y
            while y < len(rows) and rows[y]:
                y += 1
            if y - start <= 6:  # a staff line, not a block of ink
                centres.append((start + y - 1) // 2)
        y += 1
    return centres


def _box():
    from PIL import Image

    return Image.Resampling.BOX


def _five_even(lines: list[int]) -> bool:
    """Five lines in a row, evenly spaced as a staff's are (3 to 25 pixels apart at 100 dpi)."""
    for i in range(len(lines) - 4):
        gaps = [b - a for a, b in zip(lines[i : i + 5], lines[i + 1 : i + 5])]
        if 3 <= min(gaps) and max(gaps) <= 25 and max(gaps) - min(gaps) <= max(2, 0.3 * min(gaps)):
            return True
    return False


def has_staff(image) -> bool:
    """Whether a grayscale page image shows a 5-line staff. The page is looked at in narrow strips, so that a
    skewed scan, whose lines do not run along one row across the page, still counts."""
    left, width = int(image.width * 0.1), int(image.width * 0.8)
    step = max(1, width // STRIPS)
    found = 0
    for k in range(STRIPS):
        strip = image.crop((left + k * step, 0, left + (k + 1) * step, image.height))
        if _five_even(_line_rows(strip)):
            found += 1
            if found >= 2:
                return True
    return False


def pages_with_staves(pdf: Path) -> tuple[int, list[int]]:
    """(number of pages, the 1-based pages where at least one 5-line staff can be seen)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover
        return 0, []
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except Exception:
        return 0, []
    music: list[int] = []
    try:
        for i in range(len(doc)):
            image = doc[i].render(scale=DPI / 72).to_pil().convert("L")
            if has_staff(image):
                music.append(i + 1)
        return len(doc), music
    finally:
        doc.close()


def keep_pages(source: Path, pages: list[int], dest: Path) -> Path:
    """Write the 1-based pages of source, in order, to dest (a new PDF)."""
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(str(source))
    out = pdfium.PdfDocument.new()
    try:
        out.import_pages(src, [p - 1 for p in pages])
        out.save(str(dest))
    finally:
        out.close()
        src.close()
    return dest
