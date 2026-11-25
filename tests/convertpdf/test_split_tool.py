from __future__ import annotations

from pathlib import Path

import pypdf

from lento_convertpdf import split_tool
from lento_convertpdf.pdf_splitter import PdfPieceSegment, execute_pdf_split


def blank_pdf(path: Path, pages: int) -> None:
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=300)
    with path.open("wb") as f:
        w.write(f)


def test_split_never_overwrites(tmp_path: Path) -> None:
    src = tmp_path / "book.pdf"
    blank_pdf(src, 4)
    out = tmp_path / "out"
    out.mkdir()
    segs = [PdfPieceSegment(index=1, start_page=1, end_page=2, title="Piece"),
            PdfPieceSegment(index=2, start_page=3, end_page=4, title="Piece")]
    (out / "Piece.pdf").write_bytes(b"keep me")
    created = execute_pdf_split(src, segs, output_dir=out)
    assert (out / "Piece.pdf").read_bytes() == b"keep me"
    assert len(created) == 2 and all(p.exists() and p.name != "Piece.pdf" for p in created)


def test_install_sendto(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Microsoft" / "Windows" / "SendTo").mkdir(parents=True)
    f = split_tool.install_sendto()
    assert f.name == "Lento Split PDF.cmd"
    assert "-m lento_convertpdf.split_tool %1" in f.read_text(encoding="utf-8")
    assert split_tool.main(["--uninstall-sendto"]) == 0 and not f.exists()


def test_missing_pdf_is_an_error(tmp_path: Path) -> None:
    assert split_tool.main([str(tmp_path / "nope.pdf")]) == 2
