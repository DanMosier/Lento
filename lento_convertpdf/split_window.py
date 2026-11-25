"""The Multi-Piece PDF Splitter window: proposed pieces beside a page preview, nothing written until "Split".

Opened from Lento_ConvertPDF, or by itself with `python -m lento_convertpdf.split_tool`.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

from .pdf_splitter import (
    PdfPieceSegment,
    SplitAnalysisReport,
    analyze_multi_piece_pdf,
    default_output_dir,
    execute_pdf_split,
    find_midpage_cutoff_y_ratio,
    resolve_overlapping_page_cutoffs,
)

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None  # type: ignore[assignment]


def render_pdf_page_image(
    pdf_path: Path,
    page_index: int = 0,
    zoom: float = 1.0,
    fit_width: int | None = None,
    highlight_y_ratio: float | None = None,
    cutoff_y_ratio: float | None = None,
    active_region: tuple[float, float] | None = None,
) -> tuple[Image.Image, int, int]:
    """Render a single page of a PDF file to a PIL Image for the side-by-side PDF Reader.

    Supports drawing a playback highlight band (`highlight_y_ratio`) as well as a mid-page
    split cutoff line (`cutoff_y_ratio`) and active piece region (`active_region = (top_r, bot_r)`).
    Returns `(pil_image, clamped_page_index, total_pages)`.
    """
    if pdfium is None:
        raise RuntimeError("pypdfium2 is required to render PDF pages.")

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        total_pages = max(1, len(doc))
        clamped_idx = max(0, min(total_pages - 1, page_index))
        page = doc[clamped_idx]
        page_w, _page_h = page.get_size()

        if fit_width is not None and fit_width > 80 and page_w > 0:
            base_scale = (fit_width / page_w) * zoom
        else:
            base_scale = 1.35 * zoom
        scale = max(0.35, min(4.0, base_scale))

        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil().convert("RGBA")
        img_w, img_h = pil_img.size

        if highlight_y_ratio is not None and 0.0 <= highlight_y_ratio <= 1.0:
            overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            band_h = max(36, int(img_h * 0.16))
            center_y = int(img_h * (0.14 + highlight_y_ratio * 0.72))
            y0 = max(4, center_y - band_h // 2)
            y1 = min(img_h - 4, center_y + band_h // 2)
            draw.rectangle((8, y0, img_w - 8, y1), fill=(37, 99, 235, 36), outline=(37, 99, 235, 165), width=2)
            pil_img = Image.alpha_composite(pil_img, overlay)

        if active_region is not None or cutoff_y_ratio is not None:
            overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            if active_region is not None:
                top_r, bot_r = active_region
                ay0 = max(0, min(img_h, int(img_h * top_r)))
                ay1 = max(ay0, min(img_h, int(img_h * bot_r)))
                # Shade excluded areas outside [top_r .. bot_r] in gray and highlight kept area in green tint
                if ay0 > 2:
                    draw.rectangle((0, 0, img_w, ay0), fill=(100, 116, 139, 75))
                if ay1 < img_h - 2:
                    draw.rectangle((0, ay1, img_w, img_h), fill=(100, 116, 139, 75))
                draw.rectangle((4, ay0, img_w - 4, ay1), fill=(22, 163, 74, 22), outline=(22, 163, 74, 160), width=2)

            if cutoff_y_ratio is not None and 0.02 < cutoff_y_ratio < 0.98:
                cy = int(img_h * cutoff_y_ratio)
                draw.line((0, cy, img_w, cy), fill=(220, 38, 38, 240), width=3)
                badge_top = max(4, cy - 18)
                draw.rectangle((10, badge_top, min(img_w - 10, 235), badge_top + 18), fill=(220, 38, 38, 230))
                draw.text((16, badge_top + 2), f"CUTOFF LINE @ {cutoff_y_ratio:.0%}", fill=(255, 255, 255, 255))

            pil_img = Image.alpha_composite(pil_img, overlay)

        return pil_img.convert("RGB"), clamped_idx, total_pages
    finally:
        doc.close()


def build_split_window(
    dlg: tk.Toplevel,
    initial_pdf: Path | None = None,
    browse_dir: Callable[[], str] = lambda: "",
    on_split: Callable[[Path, list[Path], Path, bool], None] | None = None,
) -> None:
    """Fills `dlg` with the splitter. `on_split(pdf, created, out_folder, queue_them)` runs after a split; without it
    the "import into the converter queue" option is hidden."""
    dlg.title("Split Multi-Piece Sheet Music PDF")
    dlg.geometry("1180x740")
    dlg.minsize(960, 600)

    pdf_var = tk.StringVar(value=str(initial_pdf) if initial_pdf else "")
    out_dir_var = tk.StringVar(value=str(default_output_dir(initial_pdf)) if initial_pdf else "")
    mode_var = tk.StringVar(value="auto")
    ocr_var = tk.BooleanVar(value=True)
    llm_var = tk.BooleanVar(value=False)
    import_after_var = tk.BooleanVar(value=True)

    recognition_badge_var = tk.StringVar(
        value="Click 'Analyze PDF' to check whether the PDF can be split easily with pypdf or requires the Vision System."
    )
    preview_page_var = tk.StringVar(value="Page 0 / 0")

    current_report: list[SplitAnalysisReport | None] = [None]
    row_to_seg: dict[str, PdfPieceSegment] = {}
    preview_page_idx: list[int] = [0]
    preview_photo_ref: list[ImageTk.PhotoImage | None] = [None]

    outer = ttk.Frame(dlg, padding=12)
    outer.pack(fill=tk.BOTH, expand=True)

    # 1. Top Controls: Source PDF + Mode Selection
    top_box = ttk.LabelFrame(
        outer,
        text="1. Multi-Piece PDF Source & Split Recognition Mode (pypdf vs. Vision System)",
        padding=8,
    )
    top_box.pack(fill=tk.X, pady=(0, 8))

    r1 = ttk.Frame(top_box)
    r1.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(r1, text="Multi-Piece PDF:").pack(side=tk.LEFT)
    ttk.Entry(r1, textvariable=pdf_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

    def _browse_src_pdf() -> None:
        p = filedialog.askopenfilename(
            parent=dlg,
            title="Select PDF Containing Multiple Pieces of Sheet Music",
            initialdir=browse_dir() or str(Path.home()),
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
        )
        if p:
            pdf_var.set(p)
            out_dir_var.set(str(default_output_dir(Path(p))))
            _run_analysis()

    ttk.Button(r1, text="Browse PDF...", command=_browse_src_pdf).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(r1, text="Output Folder:").pack(side=tk.LEFT)
    ttk.Entry(r1, textvariable=out_dir_var, width=28).pack(side=tk.LEFT, padx=(6, 6))

    def _browse_out_folder() -> None:
        d = filedialog.askdirectory(
            parent=dlg,
            title="Select Folder to Save Split Piece PDFs",
            initialdir=out_dir_var.get() or browse_dir() or str(Path.home()),
        )
        if d:
            out_dir_var.set(d)

    ttk.Button(r1, text="Output...", command=_browse_out_folder).pack(side=tk.LEFT)

    r2 = ttk.Frame(top_box)
    r2.pack(fill=tk.X)
    ttk.Label(r2, text="Detection Engine:", style="SubHeader.TLabel").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Radiobutton(
        r2,
        text="Auto-Detect (Recognize pypdf vs. Vision)",
        value="auto",
        variable=mode_var,
    ).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Radiobutton(
        r2,
        text="pypdf Only (Fast Outline / Embedded Text)",
        value="pypdf",
        variable=mode_var,
    ).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Radiobutton(
        r2,
        text="Robust Vision System (Staff Layout + WinRT OCR)",
        value="vision",
        variable=mode_var,
    ).pack(side=tk.LEFT, padx=(0, 12))

    ttk.Checkbutton(r2, text="WinRT OCR", variable=ocr_var).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Checkbutton(r2, text="Vision LLM (if API key set)", variable=llm_var).pack(side=tk.LEFT, padx=(0, 8))

    # 2. Recognition Status Banner
    rec_frame = ttk.LabelFrame(outer, text="2. Reader Recognition Assessment (pypdf vs. Vision System)", padding=8)
    rec_frame.pack(fill=tk.X, pady=(0, 8))
    rec_label = ttk.Label(
        rec_frame,
        textvariable=recognition_badge_var,
        font=("Segoe UI", 9, "bold"),
        wraplength=1120,
    )
    rec_label.pack(anchor=tk.W)

    # 3. Split PanedWindow: Left = Detected Pieces Table & Boundary Editor, Right = Page Visual Preview
    mid_pane = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
    mid_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

    left_box = ttk.LabelFrame(
        mid_pane,
        text="3. Detected Sheet Music Pieces (Click '☑' to toggle; Select a row to edit page range or title)",
        padding=6,
    )
    mid_pane.add(left_box, weight=3)

    cols = ("selected", "idx", "pages", "count", "title", "composer", "source", "conf", "notes")
    seg_tree = ttk.Treeview(left_box, columns=cols, show="headings", selectmode="browse", height=10)
    for col, (lbl, w) in {
        "selected": ("Split?", 52),
        "idx": ("#", 34),
        "pages": ("Page Range", 85),
        "count": ("Pages", 50),
        "title": ("Detected Piece Title", 190),
        "composer": ("Composer", 120),
        "source": ("Method Used", 110),
        "conf": ("Conf.", 50),
        "notes": ("Boundary Detection Reason", 210),
    }.items():
        seg_tree.heading(col, text=lbl)
        seg_tree.column(col, width=w, anchor=tk.CENTER if col in ("selected", "idx", "count") else tk.W)

    seg_vsb = ttk.Scrollbar(left_box, orient=tk.VERTICAL, command=seg_tree.yview)
    seg_tree.configure(yscrollcommand=seg_vsb.set)
    seg_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

    # Inline segment editor row
    edit_row = ttk.Frame(left_box)
    edit_row.pack(fill=tk.X, pady=(0, 4))
    edit_title_var = tk.StringVar(value="")
    edit_comp_var = tk.StringVar(value="")
    edit_start_var = tk.IntVar(value=1)
    edit_end_var = tk.IntVar(value=1)
    edit_start_y_pct_var = tk.IntVar(value=0)
    edit_end_y_pct_var = tk.IntVar(value=100)

    ttk.Label(edit_row, text="Title:").pack(side=tk.LEFT)
    ttk.Entry(edit_row, textvariable=edit_title_var, width=18).pack(side=tk.LEFT, padx=(3, 6))
    ttk.Label(edit_row, text="Composer:").pack(side=tk.LEFT)
    ttk.Entry(edit_row, textvariable=edit_comp_var, width=13).pack(side=tk.LEFT, padx=(3, 6))
    ttk.Label(edit_row, text="Pages:").pack(side=tk.LEFT)
    ttk.Spinbox(edit_row, from_=1, to=9999, textvariable=edit_start_var, width=4).pack(side=tk.LEFT, padx=(3, 2))
    ttk.Label(edit_row, text="–").pack(side=tk.LEFT)
    ttk.Spinbox(edit_row, from_=1, to=9999, textvariable=edit_end_var, width=4).pack(side=tk.LEFT, padx=(2, 6))
    ttk.Label(edit_row, text="Start Y%:").pack(side=tk.LEFT)
    ttk.Spinbox(edit_row, from_=0, to=95, increment=2, textvariable=edit_start_y_pct_var, width=4).pack(
        side=tk.LEFT, padx=(2, 6)
    )
    ttk.Label(edit_row, text="End Y%:").pack(side=tk.LEFT)
    ttk.Spinbox(edit_row, from_=5, to=100, increment=2, textvariable=edit_end_y_pct_var, width=4).pack(
        side=tk.LEFT, padx=(2, 6)
    )

    # Right: Live PDF Page Preview
    right_box = ttk.LabelFrame(
        mid_pane,
        text="Page Visual Preview (Click on a shared page to adjust mid-page cutoff line)",
        padding=6,
    )
    mid_pane.add(right_box, weight=2)

    p_nav = ttk.Frame(right_box)
    p_nav.pack(fill=tk.X, pady=(0, 4))

    preview_img_height: list[int] = [400]

    def _get_selected_segment() -> PdfPieceSegment | None:
        s = seg_tree.selection()
        if s and s[0] in row_to_seg:
            return row_to_seg[s[0]]
        return None

    def _render_preview_page(page_idx: int) -> None:
        raw_p = pdf_var.get().strip()
        if not raw_p or not Path(raw_p).is_file():
            return
        try:
            cw = max(260, preview_canvas.winfo_width() - 12)
            pnum = page_idx + 1
            active_reg: tuple[float, float] | None = None
            cutoff_r: float | None = None

            sel_seg = _get_selected_segment()
            if sel_seg and sel_seg.start_page <= pnum <= sel_seg.end_page:
                top_r = sel_seg.start_y_ratio if (pnum == sel_seg.start_page and sel_seg.has_midpage_start) else 0.0
                bot_r = sel_seg.end_y_ratio if (pnum == sel_seg.end_page and sel_seg.has_midpage_end) else 1.0
                if top_r > 0.02 or bot_r < 0.98:
                    active_reg = (top_r, bot_r)
                    cutoff_r = top_r if top_r > 0.02 else bot_r

            pil_img, clamped, total = render_pdf_page_image(
                Path(raw_p),
                page_index=page_idx,
                fit_width=cw,
                cutoff_y_ratio=cutoff_r,
                active_region=active_reg,
            )
            preview_page_idx[0] = clamped
            preview_img_height[0] = max(1, pil_img.height)
            photo = ImageTk.PhotoImage(pil_img)
            preview_photo_ref[0] = photo
            preview_canvas.delete("all")
            preview_canvas.create_image(6, 6, anchor=tk.NW, image=photo)
            preview_canvas.configure(scrollregion=(0, 0, pil_img.width + 12, pil_img.height + 12))
            preview_page_var.set(f"Page {clamped + 1} / {total}")
        except Exception:
            pass

    ttk.Button(
        p_nav,
        text="◀ Prev",
        width=7,
        command=lambda: _render_preview_page(max(0, preview_page_idx[0] - 1)),
    ).pack(side=tk.LEFT, padx=(0, 3))
    ttk.Label(p_nav, textvariable=preview_page_var, width=11, anchor=tk.CENTER).pack(side=tk.LEFT, padx=(0, 3))
    ttk.Button(
        p_nav,
        text="Next ▶",
        width=7,
        command=lambda: _render_preview_page(preview_page_idx[0] + 1),
    ).pack(side=tk.LEFT, padx=(0, 6))

    def _split_midpage_on_current_page() -> None:
        """Split the segment containing the current page into TWO pieces sharing this overlapping page."""
        rep = current_report[0]
        if not rep:
            return
        cur_p = preview_page_idx[0] + 1
        for idx_s, seg in enumerate(rep.segments):
            if seg.start_page <= cur_p <= seg.end_page:
                cutoff_y, _, reason = find_midpage_cutoff_y_ratio(rep.pdf_path, cur_p)
                old_end = seg.end_page
                old_end_yr = seg.end_y_ratio
                seg.end_page = cur_p
                seg.end_y_ratio = cutoff_y
                seg.notes = f"{seg.notes}; ends mid-page on p.{cur_p} @ {cutoff_y:.0%}".strip("; ")

                new_seg = PdfPieceSegment(
                    index=idx_s + 2,
                    title=f"{rep.pdf_path.stem} - Piece {idx_s + 2}",
                    composer=seg.composer,
                    start_page=cur_p,
                    end_page=old_end,
                    start_y_ratio=cutoff_y,
                    end_y_ratio=old_end_yr,
                    confidence=0.92,
                    detection_source="midpage-cutoff",
                    notes=f"starts mid-page on p.{cur_p} @ {cutoff_y:.0%} ({reason})",
                )
                rep.segments.insert(idx_s + 1, new_seg)
                for r_i, s_item in enumerate(rep.segments, start=1):
                    s_item.index = r_i
                _populate_segments_tree()
                return

    ttk.Button(
        p_nav,
        text="✂ Split Mid-Page Here (Overlapping Page)",
        command=_split_midpage_on_current_page,
    ).pack(side=tk.RIGHT)

    preview_canvas = tk.Canvas(right_box, bg="#e5e7eb", width=340, height=360)
    preview_vsb = ttk.Scrollbar(right_box, orient=tk.VERTICAL, command=preview_canvas.yview)
    preview_canvas.configure(yscrollcommand=preview_vsb.set)
    preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    preview_vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_preview_canvas_click(event: tk.Event) -> None:  # type: ignore[type-arg]
        """Allow clicking vertically on a shared/overlapping page in the preview to set the mid-page cutoff line."""
        rep = current_report[0]
        sel_seg = _get_selected_segment()
        if not rep or not sel_seg:
            return
        pnum = preview_page_idx[0] + 1
        canvas_y = preview_canvas.canvasy(event.y) - 6
        clicked_ratio = round(max(0.08, min(0.92, canvas_y / max(1, preview_img_height[0]))), 3)

        updated = False
        if pnum == sel_seg.end_page and (
            sel_seg.has_midpage_end
            or any(other is not sel_seg and other.start_page == pnum for other in rep.segments)
        ):
            sel_seg.end_y_ratio = clicked_ratio
            for other in rep.segments:
                if other is not sel_seg and other.start_page == pnum:
                    other.start_y_ratio = clicked_ratio
            updated = True
        elif pnum == sel_seg.start_page and (
            sel_seg.has_midpage_start
            or any(other is not sel_seg and other.end_page == pnum for other in rep.segments)
        ):
            sel_seg.start_y_ratio = clicked_ratio
            for other in rep.segments:
                if other is not sel_seg and other.end_page == pnum:
                    other.end_y_ratio = clicked_ratio
            updated = True

        if updated:
            _populate_segments_tree()
            _render_preview_page(pnum - 1)

    preview_canvas.bind("<Button-1>", _on_preview_canvas_click)

    def _populate_segments_tree() -> None:
        prev_sel_idx: int | None = None
        cur_sel = _get_selected_segment()
        if cur_sel:
            prev_sel_idx = cur_sel.index

        for rid in seg_tree.get_children():
            seg_tree.delete(rid)
        row_to_seg.clear()
        rep = current_report[0]
        if not rep:
            return
        target_rid: str | None = None
        for seg in rep.segments:
            chk = "☑" if seg.selected else "☐"
            rid = seg_tree.insert(
                "",
                tk.END,
                values=(
                    chk,
                    str(seg.index),
                    seg.page_range_label,
                    str(seg.page_count),
                    seg.title,
                    seg.composer or "-",
                    seg.detection_source,
                    f"{seg.confidence:.2f}",
                    seg.notes,
                ),
            )
            row_to_seg[rid] = seg
            if prev_sel_idx == seg.index:
                target_rid = rid

        children = seg_tree.get_children()
        if children:
            seg_tree.selection_set(target_rid or children[0])
            _on_seg_select()

    def _on_seg_select(_e: object = None) -> None:
        seg = _get_selected_segment()
        if not seg:
            return
        edit_title_var.set(seg.title)
        edit_comp_var.set(seg.composer)
        edit_start_var.set(seg.start_page)
        edit_end_var.set(seg.end_page)
        edit_start_y_pct_var.set(int(round(seg.start_y_ratio * 100)))
        edit_end_y_pct_var.set(int(round(seg.end_y_ratio * 100)))
        _render_preview_page(seg.start_page - 1)

    def _on_seg_click(event: tk.Event) -> None:  # type: ignore[type-arg]
        if seg_tree.identify("region", event.x, event.y) != "cell":
            return
        if seg_tree.identify_column(event.x) == "#1":
            rid = seg_tree.identify_row(event.y)
            if rid and rid in row_to_seg:
                seg = row_to_seg[rid]
                seg.selected = not seg.selected
                vals = list(seg_tree.item(rid, "values"))
                vals[0] = "☑" if seg.selected else "☐"
                seg_tree.item(rid, values=vals)

    def _apply_inline_edit() -> None:
        rep = current_report[0]
        seg = _get_selected_segment()
        if not rep or not seg:
            return
        seg.title = edit_title_var.get().strip() or seg.title
        seg.composer = edit_comp_var.get().strip()
        try:
            seg.start_page = max(1, int(edit_start_var.get()))
            seg.end_page = max(seg.start_page, int(edit_end_var.get()))
            seg.start_y_ratio = max(0.0, min(0.95, float(edit_start_y_pct_var.get()) / 100.0))
            seg.end_y_ratio = max(seg.start_y_ratio + 0.05 if seg.start_page == seg.end_page else 0.05, min(1.0, float(edit_end_y_pct_var.get()) / 100.0))
        except (ValueError, tk.TclError):
            pass
        # Automatically compute mid-page cutoffs for any overlapping boundary pages (e.g. 20-26 and 26-30)
        resolve_overlapping_page_cutoffs(rep.pdf_path, rep.segments)
        _populate_segments_tree()

    ttk.Button(edit_row, text="Update / Auto-Cut", command=_apply_inline_edit).pack(side=tk.LEFT)
    seg_tree.bind("<<TreeviewSelect>>", _on_seg_select)
    seg_tree.bind("<Button-1>", _on_seg_click)

    def _run_analysis() -> None:
        raw_p = pdf_var.get().strip()
        if not raw_p or not Path(raw_p).is_file():
            messagebox.showwarning("Select a PDF", "Please choose a valid PDF file to analyze.", parent=dlg)
            return
        recognition_badge_var.set(
            "Analyzing PDF structure (checking pypdf embedded text & outlines vs. Vision layout)..."
        )
        dlg.update_idletasks()
        try:
            rep = analyze_multi_piece_pdf(
                Path(raw_p),
                mode=mode_var.get(),
                use_winrt_ocr=ocr_var.get(),
                use_vision_llm=llm_var.get(),
            )
            current_report[0] = rep
            badge_prefix = (
                "✔ EASY SPLIT VIA PYPDF"
                if rep.recommended_method == "pypdf"
                else "🔍 ROBUST VISION SYSTEM REQUIRED"
            )
            recognition_badge_var.set(
                f"[{badge_prefix}]  (Active Engine: {rep.method_used.upper()}  |  "
                f"Total Pages: {rep.total_pages}  |  Detected Pieces: {len(rep.segments)})\n"
                f"Assessment: {rep.method_reason}"
            )
            _populate_segments_tree()
        except Exception as exc:
            messagebox.showerror("Analysis Error", str(exc), parent=dlg)

    ttk.Button(r2, text="🔍 Analyze PDF", style="Accent.TButton", command=_run_analysis).pack(side=tk.RIGHT)

    # 4. Bottom Action Bar
    bot_bar = ttk.Frame(outer)
    bot_bar.pack(fill=tk.X)

    if on_split:  # only the converter has a queue
        ttk.Checkbutton(
            bot_bar,
            text="Import split PDFs into batch MusicXML converter queue after splitting",
            variable=import_after_var,
        ).pack(side=tk.LEFT)

    def _execute_split() -> None:
        rep = current_report[0]
        if not rep or not rep.segments:
            messagebox.showinfo("Analyze First", "Click 'Analyze PDF' first to detect piece boundaries.", parent=dlg)
            return
        selected_segs = [s for s in rep.segments if s.selected]
        if not selected_segs:
            messagebox.showinfo("No Pieces Selected", "Select at least one piece (☑) to export.", parent=dlg)
            return

        out_folder = Path(out_dir_var.get().strip()) if out_dir_var.get().strip() else default_output_dir(rep.pdf_path)
        try:
            created = execute_pdf_split(rep.pdf_path, rep.segments, output_dir=out_folder, prefix_index=True)
            if on_split:
                on_split(rep.pdf_path, created, out_folder, import_after_var.get())
            messagebox.showinfo(
                "PDF Split Complete",
                f"Created {len(created)} separate PDF file(s) in:\n{out_folder}\n\n"
                + "\n".join(f"• {p.name}" for p in created[:12]),
                parent=dlg,
            )
        except Exception as exc:
            messagebox.showerror("Split Failed", str(exc), parent=dlg)

    ttk.Button(bot_bar, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)
    ttk.Button(
        bot_bar,
        text="✂ Split Selected Pieces into Separate PDFs",
        style="Accent.TButton",
        command=_execute_split,
    ).pack(side=tk.RIGHT, padx=(0, 8))

    if initial_pdf and initial_pdf.is_file():
        dlg.after(120, _run_analysis)
