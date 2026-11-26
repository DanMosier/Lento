"""Tests for finding the pages of a PDF that hold music."""

from __future__ import annotations

from PIL import Image, ImageDraw

from lento_convertpdf.pages import has_staff, keep_pages, pages_with_staves

W, H = 850, 1100  # a letter page at 100 dpi


def page(staves: int = 0, skew: int = 0, text: bool = False) -> Image.Image:
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    for s in range(staves):
        top = 120 + s * 110
        for line in range(5):
            y = top + line * 8
            d.line([(60, y), (W - 60, y + skew)], fill=0, width=1)
    if text:
        for row in range(12):
            for word in range(10):
                d.rectangle([80 + word * 70, 200 + row * 30, 130 + word * 70, 212 + row * 30], fill=0)
        d.line([(60, 100), (W - 60, 100)], fill=0, width=2)  # a rule under the title
    return im


def test_staves_are_found_even_when_skewed():
    assert has_staff(page(staves=1))
    assert has_staff(page(staves=8, skew=25))


def test_title_and_blank_pages_have_no_staff():
    assert not has_staff(page())
    assert not has_staff(page(text=True))


def test_pdf_pages(tmp_path):
    pdf = tmp_path / "part.pdf"
    images = [page(text=True), page(staves=8, skew=12), page(staves=8), page()]
    images[0].convert("RGB").save(pdf, save_all=True, append_images=[i.convert("RGB") for i in images[1:]], resolution=100)
    assert pages_with_staves(pdf) == (4, [2, 3])
    kept = keep_pages(pdf, [2, 3], tmp_path / "kept.pdf")
    assert pages_with_staves(kept) == (2, [1, 2])
