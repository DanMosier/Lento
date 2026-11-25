"""The PDF splitter as a tool of its own: encrypted PDFs, where the pieces go, and the window."""

from pathlib import Path

import pypdf
import pytest

from lento_convertpdf.pdf_splitter import analyze_multi_piece_pdf, default_output_dir, execute_pdf_split, open_pdf


def anthology(path: Path, password: str | None = None) -> Path:
    w = pypdf.PdfWriter()
    for _ in range(4):
        w.add_blank_page(width=612, height=792)
    w.add_outline_item(title="Prelude", page_number=0)
    w.add_outline_item(title="Fugue", page_number=2)
    if password is not None:
        w.encrypt(user_password=password, owner_password="owner", algorithm="RC4-128")
    with path.open("wb") as f:
        w.write(f)
    return path


def test_encrypted_without_a_password(tmp_path: Path) -> None:
    pdf = anthology(tmp_path / "a.pdf", password="")
    assert pypdf.PdfReader(str(pdf)).is_encrypted
    assert not open_pdf(pdf).is_encrypted
    rep = analyze_multi_piece_pdf(pdf)
    assert [(s.title, s.start_page, s.end_page) for s in rep.segments] == [("Prelude", 1, 2), ("Fugue", 3, 4)]
    before = pdf.read_bytes()
    made = execute_pdf_split(pdf, rep.segments, output_dir=tmp_path / "out")
    assert [len(pypdf.PdfReader(str(p)).pages) for p in made] == [2, 2]
    assert pdf.read_bytes() == before


def test_a_real_password_says_so(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs a password"):
        open_pdf(anthology(tmp_path / "a.pdf", password="secret"))


def test_never_overwrites(tmp_path: Path) -> None:
    pdf = anthology(tmp_path / "a.pdf")
    out = tmp_path / "out"
    segs = analyze_multi_piece_pdf(pdf).segments
    first = execute_pdf_split(pdf, segs, output_dir=out)
    first[0].write_bytes(b"mine")
    again = execute_pdf_split(pdf, segs, output_dir=out)
    assert first[0].read_bytes() == b"mine"
    assert not set(first) & set(again)


def test_default_output_dir(tmp_path: Path) -> None:
    assert default_output_dir(tmp_path / "x.pdf") == tmp_path.resolve() / "x (split)"
    score = tmp_path / "lib" / "pieces" / "bach_x" / "bach_x__score.pdf"
    score.parent.mkdir(parents=True)
    assert default_output_dir(score) == score.parent.resolve() / "bach_x__score (split)"  # not a library
    (tmp_path / "lib" / "library.json").write_text("{}")
    assert default_output_dir(score) == (tmp_path / "lib" / "inbox").resolve() / "bach_x__score (split)"


def test_window_by_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tk = pytest.importorskip("tkinter")
    from tkinter import messagebox, ttk

    from lento_convertpdf.split_window import build_split_window

    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(messagebox, name, lambda *a, **k: None)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    dlg = tk.Toplevel(root)
    dlg.withdraw()
    build_split_window(dlg, anthology(tmp_path / "a.pdf", password=""))

    def all_of(w):
        for c in w.winfo_children():
            yield c
            yield from all_of(c)

    buttons = {b.cget("text"): b for b in all_of(dlg) if isinstance(b, (ttk.Button, ttk.Checkbutton))}
    assert not any("converter queue" in t for t in buttons)
    buttons["\U0001f50d Analyze PDF"].invoke()
    tree = next(w for w in all_of(dlg) if isinstance(w, ttk.Treeview))
    assert [tree.item(r, "values")[4] for r in tree.get_children()] == ["Prelude", "Fugue"]
    assert not (tmp_path / "a (split)").exists()  # nothing written before Split
    buttons["\u2702 Split Selected Pieces into Separate PDFs"].invoke()
    assert sorted(p.name for p in (tmp_path / "a (split)").iterdir()) == ["01 - Prelude.pdf", "02 - Fugue.pdf"]
    root.destroy()


def test_tool_closes_with_its_last_window(tmp_path: Path) -> None:
    tk = pytest.importorskip("tkinter")
    from lento_convertpdf import split_tool

    made = []

    def fake(dlg, pdf, browse_dir):
        dlg.withdraw()
        made.append(pdf)
        dlg.after(20, dlg.destroy)

    real, split_tool.build_split_window = split_tool.build_split_window, fake
    try:
        a, b = anthology(tmp_path / "a.pdf"), anthology(tmp_path / "b.pdf")
        assert split_tool.main([str(a), str(b)]) == 0
    except tk.TclError:
        pytest.skip("no display")
    finally:
        split_tool.build_split_window = real
    assert made == [a, b]
