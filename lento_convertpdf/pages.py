"""Pages of a PDF that hold music.

OMR engines give up on a whole PDF when one page has no staff: homr with "No staffs found", Audiveris with
"No system found". Title pages, blank pages and library stamps are common in scanned parts, so the converters
retry with only the pages that show staves.
"""

from __future__ import annotations

from pathlib import Path


def pages_with_staves(pdf: Path) -> tuple[int, list[int]]:
    """(number of pages, the 1-based pages where at least one 5-line staff can be seen)."""
    from .staff_detection import detect_staves_in_image

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
            image = doc[i].render(scale=100 / 72).to_pil().convert("L")
            if detect_staves_in_image(image):
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
