"""Full desktop GUI (Tkinter) for batch PDF -> MusicXML OMR conversion, Side-by-Side PDF Reader, and Open-Source VST MusicXML Player."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .audio_player import MusicXMLAudioPlayer, synthesize_score_to_wav
from .homr_runner import GPU_MODES, EngineAvailability, OMRConfig
from .models import InstrumentPart, ParsedScore, PdfConversionItem
from .musicxml_parser import parse_musicxml
from .omr_engines import batch_convert_pdfs, check_engine, scan_folder_for_pdfs
from .quality import REVIEW_BELOW
from .split_window import build_split_window, render_pdf_page_image
from .vst_catalog import (
    OPEN_SOURCE_VST_CATALOG,
    VST_BY_ID,
    VSTDeepSearchItem,
    VSTDeepSearchReport,
    assign_recommended_vsts_to_parts,
    deep_search_and_download_vsts,
    get_managed_vst_directory,
    source_all_recommended_vsts,
    source_open_source_vst_bundle,
)

PART_COLORS = (
    "#2563eb",  # Royal Blue
    "#16a34a",  # Emerald Green
    "#d97706",  # Amber
    "#9333ea",  # Purple
    "#dc2626",  # Crimson
    "#0891b2",  # Cyan
    "#4f46e5",  # Indigo
    "#be185d",  # Pink
)


class LentoConvertPDFApp:
    """Main desktop GUI window for batch PDF-to-MusicXML conversion, Side-by-Side PDF comparison, and VST playback."""

    def __init__(self, root: tk.Tk, initial_directory: Path | None = None) -> None:
        self.root = root
        self.root.title("Lento_ConvertPDF — PDF to MusicXML, Side-by-Side PDF Reader & VST Player")
        self.root.geometry("1440x900")
        self.root.minsize(1120, 720)

        self._event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event: threading.Event | None = None
        self._worker_thread: threading.Thread | None = None

        self._items: list[PdfConversionItem] = []
        self._row_to_item: dict[str, PdfConversionItem] = {}
        self._item_to_row: dict[int, str] = {}

        self._current_score: ParsedScore | None = None
        self._part_row_map: dict[str, InstrumentPart] = {}
        self._audio_player = MusicXMLAudioPlayer()
        self._audio_dirty: bool = True
        self._seeking_slider: bool = False
        self._canvas_score_width: int = 800

        # PDF Reader state
        self._current_pdf_path: Path | None = None
        self._pdf_page_index: int = 0
        self._pdf_total_pages: int = 0
        self._pdf_zoom: float = 1.0
        self._pdf_fit_width_mode: bool = True
        self._pdf_photo_image: ImageTk.PhotoImage | None = None
        self._pdf_base_pil_image: Image.Image | None = None
        self._pdf_highlight_ratio: float | None = None

        # Top-level UI variables
        self.dir_var = tk.StringVar(value=str(initial_directory) if initial_directory else "")
        self.out_dir_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=True)
        self.engine_var = tk.StringVar(value="homr")
        self.gpu_var = tk.StringVar(value="force")
        self.homr_python_var = tk.StringVar(value="")
        self.audiveris_path_var = tk.StringVar(value="")
        self.legato_python_var = tk.StringVar(value="")
        self.review_below_var = tk.StringVar(value=f"{REVIEW_BELOW:.0%}".rstrip("%"))

        self.engine_status_var = tk.StringVar(value="")
        self.selection_summary_var = tk.StringVar(value="No folder loaded.")
        self.status_var = tk.StringVar(
            value="Select a folder of PDF sheet music files to import and click Convert."
        )

        # PDF Reader UI variables
        self.pdf_header_var = tk.StringVar(value="Original PDF Reader: No PDF selected")
        self.pdf_page_label_var = tk.StringVar(value="Page 0 / 0")
        self.pdf_zoom_label_var = tk.StringVar(value="Fit")
        self.pdf_sync_var = tk.BooleanVar(value=True)

        # MusicXML Player UI variables
        self.score_header_var = tk.StringVar(value="Generated MusicXML Player: Convert or select a file to compare.")
        self.view_mode_var = tk.StringVar(value="staff")  # "staff" | "pianoroll"
        self.tempo_var = tk.DoubleVar(value=112.0)
        self.time_label_var = tk.StringVar(value="00:00 / 00:00  |  Measure 0 / 0")
        self.seek_var = tk.DoubleVar(value=0.0)

        self._configure_style()
        self._build_ui()
        self._refresh_engine_status()
        self._poll_events()
        self._update_playhead_loop()

        if initial_directory and initial_directory.is_dir():
            self._load_folder()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        for theme in ("vista", "xpnative", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("SubHeader.TLabel", font=("Segoe UI", 9, "bold"))
        style.configure("Subtle.TLabel", foreground="#555555", font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(
            header,
            text="Lento_ConvertPDF — PDF to MusicXML, Side-by-Side PDF Reader & VST Player",
            style="Header.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="OMR Engine: homr   •   Visual PDF vs. MusicXML Comparison",
            style="Subtle.TLabel",
        ).pack(side=tk.LEFT, padx=(16, 0))

        # Section 1: Folder Import & OMR Engine Configuration
        top_frame = ttk.LabelFrame(outer, text="1. Folder Import & homr Settings", padding=8)
        top_frame.pack(fill=tk.X, pady=(0, 8))

        folder_row = ttk.Frame(top_frame)
        folder_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(folder_row, text="PDF Source Folder:").pack(side=tk.LEFT)
        ttk.Entry(folder_row, textvariable=self.dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(folder_row, text="Browse Folder...", command=self._browse_directory).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(folder_row, text="Import / Refresh PDFs", style="Accent.TButton", command=self._load_folder).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Checkbutton(
            folder_row, text="Include subfolders", variable=self.recursive_var, command=self._load_folder
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(folder_row, text="Overwrite existing MusicXML", variable=self.overwrite_var).pack(
            side=tk.LEFT
        )

        engine_row = ttk.Frame(top_frame)
        engine_row.pack(fill=tk.X)
        ttk.Label(engine_row, text="Engine:", style="SubHeader.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        for engine, label in (("homr", "homr"), ("audiveris", "Audiveris"), ("legato", "Legato")):
            ttk.Radiobutton(
                engine_row, text=label, value=engine, variable=self.engine_var, command=self._refresh_engine_status
            ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(engine_row, text="homr / Legato run on:", style="SubHeader.TLabel").pack(side=tk.LEFT, padx=(10, 10))
        for mode, label in zip(GPU_MODES, ("GPU (CUDA required)", "GPU if available", "CPU"), strict=True):
            ttk.Radiobutton(
                engine_row, text=label, value=mode, variable=self.gpu_var, command=self._refresh_engine_status
            ).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(engine_row, text="Flag below (%):").pack(side=tk.LEFT, padx=(14, 4))
        ttk.Spinbox(engine_row, from_=0, to=100, increment=1, width=5, textvariable=self.review_below_var).pack(
            side=tk.LEFT
        )
        ttk.Button(engine_row, text="Configure engines...", command=self._open_engine_settings_dialog).pack(
            side=tk.RIGHT
        )

        status_row = ttk.Frame(top_frame)
        status_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(status_row, textvariable=self.engine_status_var, style="Subtle.TLabel").pack(side=tk.LEFT)
        ttk.Label(status_row, text="Output Folder (blank = same as PDF):").pack(side=tk.RIGHT, padx=(10, 4))
        ttk.Entry(status_row, textvariable=self.out_dir_var, width=28).pack(side=tk.RIGHT, padx=(0, 4))
        ttk.Button(status_row, text="Output...", command=self._browse_output_directory, width=8).pack(side=tk.RIGHT)

        # Vertical PanedWindow splitting Batch Queue (top) and Side-by-Side PDF + MusicXML Player (bottom)
        self.paned = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        self.paned.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        # --- Pane 1: Batch PDF File Selection & Conversion Table ---
        queue_frame = ttk.LabelFrame(
            self.paned,
            text="2. Imported PDF Files (Click '☑' column or press Space to Select / Deselect; Click any row to compare PDF & MusicXML below)",
            padding=8,
        )
        self.paned.add(queue_frame, weight=2)

        toolbar = ttk.Frame(queue_frame)
        toolbar.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(toolbar, text="☑ Select All", command=self._select_all_files).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="☐ Deselect All", command=self._deselect_all_files).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="⇄ Invert Selection", command=self._invert_file_selection).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(toolbar, text="Select Unconverted Only", command=self._select_unconverted_files).pack(
            side=tk.LEFT, padx=(0, 14)
        )

        self.convert_btn = ttk.Button(
            toolbar,
            text="▶ Convert Selected PDFs to MusicXML",
            style="Accent.TButton",
            command=self._start_batch_conversion,
        )
        self.convert_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_conv_btn = ttk.Button(
            toolbar, text="⏹ Stop Conversion", command=self._cancel_batch_conversion, state=tk.DISABLED
        )
        self.stop_conv_btn.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(
            toolbar,
            text="🔍 Compare Highlighted PDF & MusicXML",
            command=self._preview_highlighted_row,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            toolbar,
            text="✂ Split Multi-Piece PDF...",
            style="Accent.TButton",
            command=self._open_multi_piece_splitter_dialog,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            toolbar,
            text="📂 Open Any MusicXML File...",
            command=self._open_external_musicxml,
        ).pack(side=tk.RIGHT)

        ttk.Label(toolbar, textvariable=self.selection_summary_var, style="Subtle.TLabel").pack(
            side=tk.RIGHT, padx=(0, 12)
        )

        # Treeview for PDF files
        tree_container = ttk.Frame(queue_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        cols = ("selected", "status", "filename", "folder", "pages", "size_kb", "engine", "output_xml", "notes")
        self.pdf_tree = ttk.Treeview(tree_container, columns=cols, show="headings", selectmode="extended", height=6)
        headings = {
            "selected": ("Convert?", 68),
            "status": ("Status", 95),
            "filename": ("PDF Filename", 260),
            "folder": ("Subfolder", 150),
            "pages": ("Pages", 55),
            "size_kb": ("Size (KB)", 75),
            "engine": ("OMR Engine", 95),
            "output_xml": ("Output MusicXML File", 250),
            "notes": ("Detected Instruments / Details", 240),
        }
        for col, (label, width) in headings.items():
            anchor = tk.CENTER if col in ("selected", "pages") else tk.W
            self.pdf_tree.heading(col, text=label)
            self.pdf_tree.column(col, width=width, anchor=anchor)

        self.pdf_tree.tag_configure("pending", background="#ffffff")
        self.pdf_tree.tag_configure("converting", background="#e0f2fe")
        self.pdf_tree.tag_configure("converted", background="#dcfce7")
        self.pdf_tree.tag_configure("failed", background="#fee2e2")
        self.pdf_tree.tag_configure("review", background="#fef9c3")
        self.pdf_tree.tag_configure("unreliable", background="#fed7aa")
        self.pdf_tree.tag_configure("unselected", foreground="#888888")

        pdf_vsb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.pdf_tree.yview)
        pdf_hsb = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.pdf_tree.xview)
        self.pdf_tree.configure(yscrollcommand=pdf_vsb.set, xscrollcommand=pdf_hsb.set)
        self.pdf_tree.grid(row=0, column=0, sticky="nsew")
        pdf_vsb.grid(row=0, column=1, sticky="ns")
        pdf_hsb.grid(row=1, column=0, sticky="ew")
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)

        self.pdf_tree.bind("<Button-1>", self._on_pdf_tree_click)
        self.pdf_tree.bind("<<TreeviewSelect>>", self._on_pdf_tree_select)
        self.pdf_tree.bind("<Double-1>", self._on_pdf_tree_double_click)
        self.pdf_tree.bind("<space>", self._on_pdf_tree_space)

        # --- Pane 2: Side-by-Side Original PDF Reader + MusicXML Preview Player + VST Rack ---
        player_frame = ttk.LabelFrame(
            self.paned,
            text="3. Side-by-Side Visual Comparison: Original PDF Reader (Left)  ↔  Generated MusicXML Player (Center)  ↔  Open-Source VST Rack (Right)",
            padding=8,
        )
        self.paned.add(player_frame, weight=3)

        # Shared Transport Bar at top of Section 3
        transport_bar = ttk.Frame(player_frame)
        transport_bar.pack(fill=tk.X, pady=(0, 6))

        self.play_btn = ttk.Button(
            transport_bar, text="▶ Play", style="Accent.TButton", command=self._play_score, width=8
        )
        self.play_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.pause_btn = ttk.Button(transport_bar, text="⏸ Pause", command=self._pause_score, width=8)
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.stop_play_btn = ttk.Button(transport_bar, text="⏹ Stop", command=self._stop_score, width=7)
        self.stop_play_btn.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(transport_bar, text="Seek:").pack(side=tk.LEFT)
        self.seek_slider = ttk.Scale(
            transport_bar,
            from_=0.0,
            to=100.0,
            orient=tk.HORIZONTAL,
            variable=self.seek_var,
            command=self._on_seek_drag,
            length=170,
        )
        self.seek_slider.pack(side=tk.LEFT, padx=(4, 10))
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)

        ttk.Label(transport_bar, textvariable=self.time_label_var, width=27).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(transport_bar, text="Tempo:").pack(side=tk.LEFT)
        self.tempo_spin = ttk.Spinbox(
            transport_bar,
            from_=40,
            to=240,
            increment=4,
            textvariable=self.tempo_var,
            width=5,
            command=self._mark_audio_dirty,
        )
        self.tempo_spin.pack(side=tk.LEFT, padx=(4, 10))

        ttk.Radiobutton(
            transport_bar,
            text="Staff Notation",
            value="staff",
            variable=self.view_mode_var,
            command=self._redraw_score_canvas,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(
            transport_bar,
            text="Piano Roll",
            value="pianoroll",
            variable=self.view_mode_var,
            command=self._redraw_score_canvas,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Checkbutton(
            transport_bar,
            text="Sync PDF Page with Playback",
            variable=self.pdf_sync_var,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(transport_bar, text="Export WAV...", command=self._export_wav).pack(side=tk.RIGHT)
        ttk.Button(
            transport_bar,
            text="🔎 Deep Search & Auto-Download VSTs...",
            style="Accent.TButton",
            command=self._open_deep_vst_search_dialog,
        ).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(
            transport_bar,
            text="VST Catalog...",
            command=self._open_vst_catalog_dialog,
        ).pack(side=tk.RIGHT, padx=(0, 6))

        # Horizontal PanedWindow: [Original PDF Reader] | [Generated MusicXML Player] | [Open-Source VST Rack]
        self.comparison_split = ttk.PanedWindow(player_frame, orient=tk.HORIZONTAL)
        self.comparison_split.pack(fill=tk.BOTH, expand=True)

        # =====================================================================
        # LEFT PANE: Original PDF Sheet Music Reader
        # =====================================================================
        pdf_reader_pane = ttk.LabelFrame(
            self.comparison_split,
            text="Original PDF Sheet Music Reader",
            padding=6,
        )
        self.comparison_split.add(pdf_reader_pane, weight=3)

        pdf_ctrl_bar = ttk.Frame(pdf_reader_pane)
        pdf_ctrl_bar.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(pdf_ctrl_bar, text="◀ Prev", width=7, command=self._pdf_prev_page).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(pdf_ctrl_bar, textvariable=self.pdf_page_label_var, width=11, anchor=tk.CENTER).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(pdf_ctrl_bar, text="Next ▶", width=7, command=self._pdf_next_page).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(pdf_ctrl_bar, text="−", width=3, command=self._pdf_zoom_out).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(pdf_ctrl_bar, textvariable=self.pdf_zoom_label_var, width=6, anchor=tk.CENTER).pack(
            side=tk.LEFT, padx=(0, 2)
        )
        ttk.Button(pdf_ctrl_bar, text="+", width=3, command=self._pdf_zoom_in).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(pdf_ctrl_bar, text="Fit Width", width=9, command=self._pdf_zoom_fit_width).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(pdf_ctrl_bar, text="Open PDF...", width=10, command=self._open_external_pdf).pack(side=tk.RIGHT)

        ttk.Label(pdf_reader_pane, textvariable=self.pdf_header_var, style="Subtle.TLabel").pack(
            anchor=tk.W, pady=(0, 4)
        )

        pdf_canvas_wrap = ttk.Frame(pdf_reader_pane)
        pdf_canvas_wrap.pack(fill=tk.BOTH, expand=True)

        self.pdf_canvas = tk.Canvas(
            pdf_canvas_wrap,
            bg="#e5e7eb",
            highlightthickness=1,
            highlightbackground="#9ca3af",
            width=420,
            height=260,
        )
        p_vsb = ttk.Scrollbar(pdf_canvas_wrap, orient=tk.VERTICAL, command=self.pdf_canvas.yview)
        p_hsb = ttk.Scrollbar(pdf_canvas_wrap, orient=tk.HORIZONTAL, command=self.pdf_canvas.xview)
        self.pdf_canvas.configure(yscrollcommand=p_vsb.set, xscrollcommand=p_hsb.set)
        self.pdf_canvas.grid(row=0, column=0, sticky="nsew")
        p_vsb.grid(row=0, column=1, sticky="ns")
        p_hsb.grid(row=1, column=0, sticky="ew")
        pdf_canvas_wrap.rowconfigure(0, weight=1)
        pdf_canvas_wrap.columnconfigure(0, weight=1)

        self.pdf_canvas.bind("<Configure>", self._on_pdf_canvas_configure)
        self.pdf_canvas.bind("<MouseWheel>", self._on_pdf_mousewheel)
        self.pdf_canvas.bind("<Control-MouseWheel>", self._on_pdf_ctrl_mousewheel)
        self.pdf_canvas.bind("<ButtonPress-1>", lambda e: self.pdf_canvas.scan_mark(e.x, e.y))
        self.pdf_canvas.bind("<B1-Motion>", lambda e: self.pdf_canvas.scan_dragto(e.x, e.y, gain=1))

        # =====================================================================
        # CENTER PANE: Generated MusicXML Notation & Piano-Roll Player
        # =====================================================================
        xml_player_pane = ttk.LabelFrame(
            self.comparison_split,
            text="Generated MusicXML Notation & Playback (Click canvas to seek)",
            padding=6,
        )
        self.comparison_split.add(xml_player_pane, weight=4)

        ttk.Label(xml_player_pane, textvariable=self.score_header_var, style="SubHeader.TLabel").pack(
            anchor=tk.W, pady=(0, 4)
        )

        canvas_frame = ttk.Frame(xml_player_pane)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.score_canvas = tk.Canvas(
            canvas_frame,
            bg="#fdfbf7",
            highlightthickness=1,
            highlightbackground="#cccccc",
            width=480,
            height=260,
        )
        canvas_hsb = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.score_canvas.xview)
        self.score_canvas.configure(xscrollcommand=canvas_hsb.set)
        self.score_canvas.pack(fill=tk.BOTH, expand=True)
        canvas_hsb.pack(fill=tk.X)
        self.score_canvas.bind("<Configure>", lambda _e: self._redraw_score_canvas())
        self.score_canvas.bind("<Button-1>", self._on_score_canvas_click)

        # =====================================================================
        # RIGHT PANE: Open-Source VST Instrument Rack
        # =====================================================================
        vst_rack_frame = ttk.LabelFrame(
            self.comparison_split,
            text="Open-Source VST Instrument Rack",
            padding=6,
        )
        self.comparison_split.add(vst_rack_frame, weight=2)

        vst_toolbar = ttk.Frame(vst_rack_frame)
        vst_toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(vst_toolbar, text="Part VST:").pack(side=tk.LEFT)

        self.part_vst_combo_var = tk.StringVar(value="")
        vst_choices = [f"{spec.id} — {spec.name}" for spec in OPEN_SOURCE_VST_CATALOG]
        self.part_vst_combo = ttk.Combobox(
            vst_toolbar,
            textvariable=self.part_vst_combo_var,
            values=vst_choices,
            state="readonly",
            width=26,
        )
        self.part_vst_combo.pack(side=tk.LEFT, padx=(4, 4), fill=tk.X, expand=True)
        self.part_vst_combo.bind("<<ComboboxSelected>>", self._on_part_vst_combo_changed)

        ttk.Button(vst_toolbar, text="Mute", command=self._toggle_selected_part_mute, width=7).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(vst_toolbar, text=".vst3...", command=self._browse_custom_vst_for_part, width=7).pack(
            side=tk.LEFT
        )

        vst_cols = ("part", "category", "notes_count", "vst_name", "status", "mute")
        self.vst_tree = ttk.Treeview(vst_rack_frame, columns=vst_cols, show="headings", selectmode="browse", height=6)
        vst_headings = {
            "part": ("Part", 95),
            "category": ("Family", 68),
            "notes_count": ("Notes", 48),
            "vst_name": ("Assigned Open-Source VST", 190),
            "status": ("Status", 110),
            "mute": ("Audio", 58),
        }
        for col, (label, width) in vst_headings.items():
            self.vst_tree.heading(col, text=label)
            self.vst_tree.column(col, width=width, anchor=tk.W)

        vst_vsb = ttk.Scrollbar(vst_rack_frame, orient=tk.VERTICAL, command=self.vst_tree.yview)
        self.vst_tree.configure(yscrollcommand=vst_vsb.set)
        self.vst_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vst_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.vst_tree.bind("<<TreeviewSelect>>", self._on_vst_part_selected)
        self.vst_tree.bind("<Double-1>", lambda _e: self._toggle_selected_part_mute())

        # Footer progress & status bar
        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X)
        self.progress = ttk.Progressbar(footer, mode="determinate", length=220)
        self.progress.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(footer, textvariable=self.status_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

    # -------------------------------------------------------------------------
    # Original PDF Reader Methods (Page Navigation, Zoom, & Playback Sync)
    # -------------------------------------------------------------------------
    def _load_pdf_into_reader(self, pdf_path: Path, page_index: int = 0) -> None:
        if not pdf_path or not pdf_path.is_file():
            return
        self._current_pdf_path = pdf_path.resolve()
        self._pdf_page_index = max(0, page_index)
        self._pdf_highlight_ratio = None
        self._render_current_pdf_page()

    def _open_external_pdf(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Open Original Sheet Music PDF in Side-by-Side PDF Reader",
            initialdir=self.dir_var.get() or str(Path.home()),
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
        )
        if chosen:
            self._load_pdf_into_reader(Path(chosen), page_index=0)

    def _pdf_prev_page(self) -> None:
        if not self._current_pdf_path:
            return
        if self._pdf_page_index > 0:
            self._pdf_page_index -= 1
            self._render_current_pdf_page()

    def _pdf_next_page(self) -> None:
        if not self._current_pdf_path:
            return
        if self._pdf_page_index + 1 < self._pdf_total_pages:
            self._pdf_page_index += 1
            self._render_current_pdf_page()

    def _pdf_zoom_in(self) -> None:
        if not self._current_pdf_path:
            return
        self._pdf_fit_width_mode = False
        self._pdf_zoom = min(2.75, round(self._pdf_zoom + 0.20, 2))
        self._render_current_pdf_page()

    def _pdf_zoom_out(self) -> None:
        if not self._current_pdf_path:
            return
        self._pdf_fit_width_mode = False
        self._pdf_zoom = max(0.45, round(self._pdf_zoom - 0.20, 2))
        self._render_current_pdf_page()

    def _pdf_zoom_fit_width(self) -> None:
        if not self._current_pdf_path:
            return
        self._pdf_fit_width_mode = True
        self._pdf_zoom = 1.0
        self._render_current_pdf_page()

    def _on_pdf_canvas_configure(self, _event: object = None) -> None:
        if self._current_pdf_path and self._pdf_fit_width_mode:
            self._render_current_pdf_page()
        elif not self._current_pdf_path:
            self._draw_pdf_placeholder()

    def _on_pdf_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        delta = getattr(event, "delta", 0)
        if delta:
            self.pdf_canvas.yview_scroll(int(-1 * (delta / 120)), "units")

    def _on_pdf_ctrl_mousewheel(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        delta = getattr(event, "delta", 0)
        if delta > 0:
            self._pdf_zoom_in()
        elif delta < 0:
            self._pdf_zoom_out()

    def _draw_pdf_placeholder(self) -> None:
        self.pdf_canvas.delete("all")
        w = max(320, self.pdf_canvas.winfo_width())
        h = max(180, self.pdf_canvas.winfo_height())
        self.pdf_canvas.create_text(
            w // 2,
            h // 2,
            text="Select any PDF row above (or click 'Open PDF...')\nto inspect the original sheet music side-by-side.",
            fill="#555555",
            font=("Segoe UI", 10),
            justify=tk.CENTER,
        )

    def _render_current_pdf_page(self) -> None:
        if not self._current_pdf_path or not self._current_pdf_path.is_file():
            self._draw_pdf_placeholder()
            return

        canvas_w = max(320, self.pdf_canvas.winfo_width() - 16)
        fit_w = canvas_w if self._pdf_fit_width_mode else None

        try:
            pil_img, clamped_idx, total_pages = render_pdf_page_image(
                self._current_pdf_path,
                page_index=self._pdf_page_index,
                zoom=self._pdf_zoom,
                fit_width=fit_w,
                highlight_y_ratio=self._pdf_highlight_ratio,
            )
            self._pdf_page_index = clamped_idx
            self._pdf_total_pages = total_pages
            self._pdf_base_pil_image = pil_img
            self._pdf_photo_image = ImageTk.PhotoImage(pil_img)

            self.pdf_canvas.delete("all")
            img_w, img_h = pil_img.size
            x_offset = max(8, (canvas_w - img_w) // 2)
            self.pdf_canvas.create_image(x_offset, 8, anchor=tk.NW, image=self._pdf_photo_image)
            self.pdf_canvas.configure(scrollregion=(0, 0, max(canvas_w, img_w + 16), img_h + 16))

            self.pdf_header_var.set(f"PDF: {self._current_pdf_path.name}")
            self.pdf_page_label_var.set(f"Page {clamped_idx + 1} / {total_pages}")
            self.pdf_zoom_label_var.set("Fit" if self._pdf_fit_width_mode else f"{int(self._pdf_zoom * 100)}%")
        except Exception as exc:
            self.pdf_header_var.set(f"PDF Error: {exc}")

    def _sync_pdf_reader_to_playback_ratio(self, ratio: float) -> None:
        """Synchronize the displayed PDF page and vertical system highlight band with the MusicXML playhead."""
        if not self.pdf_sync_var.get() or not self._current_pdf_path or self._pdf_total_pages <= 0:
            return
        ratio = max(0.0, min(0.9999, ratio))
        target_page = min(self._pdf_total_pages - 1, int(ratio * self._pdf_total_pages))
        page_span = 1.0 / max(1, self._pdf_total_pages)
        local_page_ratio = (ratio - target_page * page_span) / page_span

        # Quantize vertical highlight updates to 16 steps per page so playback stays silky-smooth
        quantized_y = round(local_page_ratio * 16.0) / 16.0
        if target_page != self._pdf_page_index or self._pdf_highlight_ratio != quantized_y:
            self._pdf_page_index = target_page
            self._pdf_highlight_ratio = quantized_y
            self._render_current_pdf_page()

    # -------------------------------------------------------------------------
    # Folder & Engine Configuration
    # -------------------------------------------------------------------------
    def _build_omr_config(self) -> OMRConfig:
        out_raw = self.out_dir_var.get().strip()
        out_dir = Path(out_raw) if out_raw else None
        return OMRConfig(
            engine=self.engine_var.get(),
            audiveris_path=self.audiveris_path_var.get().strip(),
            legato_python=self.legato_python_var.get().strip(),
            output_dir=out_dir,
            recursive=self.recursive_var.get(),
            overwrite_existing=self.overwrite_var.get(),
            homr_python=self.homr_python_var.get().strip(),
            gpu=self.gpu_var.get(),
            review_below=self._review_below(),
        )

    def _review_below(self) -> float:
        try:
            value = float(self.review_below_var.get()) / 100
        except ValueError:
            return REVIEW_BELOW
        return min(1.0, max(0.0, value))

    def _refresh_engine_status(self) -> None:
        """Check the engine in the background: homr opens a real GPU session and Audiveris starts Java, which take a few seconds."""
        cfg = self._build_omr_config()
        self._status_request = getattr(self, "_status_request", 0) + 1
        request = self._status_request
        self.engine_status_var.set(f"Checking {cfg.engine}...")

        def _worker() -> None:
            self._event_queue.put(("engine_status", (request, check_engine(cfg))))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_engine_status(self, request: int, info: EngineAvailability) -> None:
        if request != self._status_request:
            return  # settings changed since this check started
        needs_cuda = info.engine != "audiveris" and self.gpu_var.get() == "force"
        ok = info.installed and (info.cuda or not needs_cuda)
        name = {"homr": "homr", "audiveris": "Audiveris", "legato": "Legato"}.get(info.engine, info.engine)
        text = f"{'✔' if ok else '⚠'} {name}: {info.details}"
        if info.installed and not ok:
            text += " — conversions will fail while CUDA is required"
        self.engine_status_var.set(text)

    def _browse_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Folder Containing Sheet Music PDFs",
            initialdir=self.dir_var.get() or str(Path.home()),
        )
        if chosen:
            self.dir_var.set(chosen)
            self._load_folder()

    def _browse_output_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Output Folder for Converted MusicXML Files",
            initialdir=self.out_dir_var.get() or self.dir_var.get() or str(Path.home()),
        )
        if chosen:
            self.out_dir_var.set(chosen)

    def _load_folder(self) -> None:
        raw_dir = self.dir_var.get().strip()
        if not raw_dir:
            messagebox.showwarning("Choose a Folder", "Please select a folder containing PDF sheet music first.")
            return
        folder = Path(raw_dir)
        if not folder.is_dir():
            messagebox.showerror("Invalid Folder", f"Directory does not exist:\n{folder}")
            return

        out_raw = self.out_dir_var.get().strip()
        out_dir = Path(out_raw) if out_raw else None

        self._items = scan_folder_for_pdfs(folder, recursive=self.recursive_var.get(), output_dir=out_dir)
        self._populate_pdf_tree()
        self.status_var.set(
            f"Imported {len(self._items)} PDF file(s) from '{folder.name}'. "
            "Click any row to view its PDF on the left, or click 'Convert Selected PDFs to MusicXML'."
        )

        # Auto-load the first PDF and (if already converted) its MusicXML side-by-side
        if self._items:
            first_converted = next(
                (it for it in self._items if it.output_musicxml_path and it.output_musicxml_path.is_file()),
                None,
            )
            target_item = first_converted or self._items[0]
            self._load_pdf_into_reader(target_item.pdf_path, page_index=0)
            if target_item.output_musicxml_path and target_item.output_musicxml_path.is_file():
                self._load_musicxml_into_player(target_item.output_musicxml_path, pdf_path=target_item.pdf_path)

    def _populate_pdf_tree(self) -> None:
        for row_id in self.pdf_tree.get_children():
            self.pdf_tree.delete(row_id)
        self._row_to_item.clear()
        self._item_to_row.clear()

        for item in self._items:
            chk = "☑" if item.selected else "☐"
            rel_parent = str(Path(item.relative_path).parent)
            if rel_parent == ".":
                rel_parent = "(root)"
            out_name = item.output_musicxml_path.name if item.output_musicxml_path else ""
            notes = ", ".join(item.detected_instruments) if item.detected_instruments else item.error_message
            tag = item.status if item.selected else "unselected"

            row_id = self.pdf_tree.insert(
                "",
                tk.END,
                values=(
                    chk,
                    item.status.upper(),
                    item.pdf_path.name,
                    rel_parent,
                    str(item.page_count),
                    f"{item.file_size_kb:.1f}",
                    item.engine_used.upper() if item.engine_used else "-",
                    out_name,
                    notes,
                ),
                tags=(tag,),
            )
            self._row_to_item[row_id] = item
            self._item_to_row[id(item)] = row_id

        self._update_selection_summary()

    def _refresh_single_pdf_row(self, item: PdfConversionItem) -> None:
        row_id = self._item_to_row.get(id(item))
        if not row_id or not self.pdf_tree.exists(row_id):
            return
        chk = "☑" if item.selected else "☐"
        rel_parent = str(Path(item.relative_path).parent)
        if rel_parent == ".":
            rel_parent = "(root)"
        out_name = item.output_musicxml_path.name if item.output_musicxml_path else ""
        notes_parts: list[str] = []
        if item.detected_instruments:
            notes_parts.append("Instruments: " + ", ".join(item.detected_instruments))
        if item.duration_sec > 0:
            notes_parts.append(f"{item.duration_sec:.1f}s")
        if item.error_message:
            notes_parts.append(item.error_message)
        if item.quality:
            notes_parts.insert(0, item.quality.summary)
        notes_str = " | ".join(notes_parts)
        tag = item.status if item.selected else "unselected"
        if item.quality and item.quality.level != "good":
            tag = item.quality.level

        self.pdf_tree.item(
            row_id,
            values=(
                chk,
                item.status.upper(),
                item.pdf_path.name,
                rel_parent,
                str(item.page_count),
                f"{item.file_size_kb:.1f}",
                item.engine_used.upper() if item.engine_used else "-",
                out_name,
                notes_str,
            ),
            tags=(tag,),
        )
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        total = len(self._items)
        selected = sum(1 for it in self._items if it.selected)
        converted = sum(1 for it in self._items if it.status == "converted")
        self.selection_summary_var.set(f"Selected: {selected} / {total} PDFs  |  Converted: {converted}")

    # -------------------------------------------------------------------------
    # File Selection / Deselection Controls
    # -------------------------------------------------------------------------
    def _select_all_files(self) -> None:
        for item in self._items:
            item.selected = True
            self._refresh_single_pdf_row(item)

    def _deselect_all_files(self) -> None:
        for item in self._items:
            item.selected = False
            self._refresh_single_pdf_row(item)

    def _invert_file_selection(self) -> None:
        for item in self._items:
            item.selected = not item.selected
            self._refresh_single_pdf_row(item)

    def _select_unconverted_files(self) -> None:
        for item in self._items:
            item.selected = item.status != "converted"
            self._refresh_single_pdf_row(item)

    def _on_pdf_tree_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        region = self.pdf_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.pdf_tree.identify_column(event.x)
        row_id = self.pdf_tree.identify_row(event.y)
        if not row_id or row_id not in self._row_to_item:
            return
        # Column #1 is the "Convert?" checkbox
        if col == "#1":
            item = self._row_to_item[row_id]
            item.selected = not item.selected
            self._refresh_single_pdf_row(item)

    def _on_pdf_tree_select(self, _event: object = None) -> None:
        """When the user highlights a row in the table, display its PDF (and MusicXML if converted) side-by-side."""
        sel = self.pdf_tree.selection()
        if not sel or sel[0] not in self._row_to_item:
            return
        item = self._row_to_item[sel[0]]
        if item.pdf_path != self._current_pdf_path:
            self._load_pdf_into_reader(item.pdf_path, page_index=0)
        if item.output_musicxml_path and item.output_musicxml_path.is_file():
            if not self._current_score or self._current_score.musicxml_path != item.output_musicxml_path.resolve():
                self._load_musicxml_into_player(item.output_musicxml_path, pdf_path=item.pdf_path)

    def _on_pdf_tree_space(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        for row_id in self.pdf_tree.selection():
            if row_id in self._row_to_item:
                item = self._row_to_item[row_id]
                item.selected = not item.selected
                self._refresh_single_pdf_row(item)

    def _on_pdf_tree_double_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        col = self.pdf_tree.identify_column(event.x)
        if col == "#1":
            return
        self._preview_highlighted_row()

    # -------------------------------------------------------------------------
    # Batch PDF -> MusicXML Conversion Worker
    # -------------------------------------------------------------------------
    def _start_batch_conversion(self) -> None:
        selected_items = [it for it in self._items if it.selected]
        if not selected_items:
            messagebox.showinfo(
                "No Files Selected",
                "Please select at least one PDF file (using the ☑ checkboxes) to convert.",
            )
            return

        config = self._build_omr_config()
        self._cancel_event = threading.Event()
        self.convert_btn.configure(state=tk.DISABLED)
        self.stop_conv_btn.configure(state=tk.NORMAL)
        self.progress.configure(maximum=len(selected_items), value=0)
        self.status_var.set(
            f"Converting {len(selected_items)} selected PDF(s) with homr..."
        )

        def _worker() -> None:
            try:
                def _on_prog(item: PdfConversionItem, idx: int, total: int) -> None:
                    self._event_queue.put(("conv_progress", (item, idx, total)))

                batch_convert_pdfs(
                    self._items,
                    config=config,
                    progress_callback=_on_prog,
                    cancel_check=lambda: bool(self._cancel_event and self._cancel_event.is_set()),
                )
                self._event_queue.put(("conv_done", None))
            except Exception as exc:
                self._event_queue.put(("conv_error", str(exc)))

        self._worker_thread = threading.Thread(target=_worker, daemon=True)
        self._worker_thread.start()

    def _cancel_batch_conversion(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
            self.status_var.set("Stopping batch conversion after current file...")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self._event_queue.get_nowait()
                if kind == "conv_progress":
                    item, idx, total = payload  # type: ignore[misc]
                    self.progress.configure(maximum=total, value=idx)
                    self._refresh_single_pdf_row(item)
                    self.status_var.set(
                        f"[{idx}/{total}] {item.status.upper()}: {item.pdf_path.name} "
                        f"({item.error_message or item.engine_used}, {item.duration_sec:.1f}s)"
                    )
                    if idx == 1 and item.output_musicxml_path and item.output_musicxml_path.is_file():
                        self._load_musicxml_into_player(item.output_musicxml_path, pdf_path=item.pdf_path)
                elif kind == "engine_status":
                    request, info = payload  # type: ignore[misc]
                    self._show_engine_status(request, info)
                elif kind == "conv_done":
                    self.convert_btn.configure(state=tk.NORMAL)
                    self.stop_conv_btn.configure(state=tk.DISABLED)
                    ok_count = sum(1 for it in self._items if it.selected and it.status == "converted")
                    flagged_items = [
                        it for it in self._items if it.selected and it.quality and it.quality.level != "good"
                    ]
                    flagged = len(flagged_items)
                    fail_count = sum(1 for it in self._items if it.selected and it.status == "failed")
                    self.status_var.set(
                        f"Batch conversion complete: {ok_count} converted ({flagged} flagged), {fail_count} failed. "
                        "Click any row above to visually compare its original PDF and generated MusicXML side-by-side."
                    )
                    if flagged_items:
                        shown = "\n\n".join(f"{it.pdf_path.name}\n{it.quality.summary}" for it in flagged_items[:6])
                        more = f"\n\n...and {flagged - 6} more" if flagged > 6 else ""
                        messagebox.showwarning("Check these exports", shown + more)
                    if self._current_score is None:
                        for it in self._items:
                            if it.selected and it.output_musicxml_path and it.output_musicxml_path.is_file():
                                self._load_musicxml_into_player(it.output_musicxml_path, pdf_path=it.pdf_path)
                                break
                elif kind == "conv_error":
                    self.convert_btn.configure(state=tk.NORMAL)
                    self.stop_conv_btn.configure(state=tk.DISABLED)
                    self.status_var.set(f"Conversion error: {payload}")
                    messagebox.showerror("Batch Conversion Error", str(payload))
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    # -------------------------------------------------------------------------
    # MusicXML Preview Player & Open-Source VST Rack
    # -------------------------------------------------------------------------
    def _preview_highlighted_row(self) -> None:
        sel = self.pdf_tree.selection()
        if not sel:
            messagebox.showinfo(
                "Select a Row",
                "Highlight a row in the table above (or double-click it) to compare its PDF and MusicXML.",
            )
            return
        item = self._row_to_item.get(sel[0])
        if not item:
            return
        self._load_pdf_into_reader(item.pdf_path, page_index=0)
        if not item.output_musicxml_path or not item.output_musicxml_path.is_file():
            if messagebox.askyesno(
                "Not Yet Converted",
                f"'{item.pdf_path.name}' has not been converted yet.\nConvert it now with homr?",
            ):
                for it in self._items:
                    it.selected = it is item
                    self._refresh_single_pdf_row(it)
                self._start_batch_conversion()
            return
        self._load_musicxml_into_player(item.output_musicxml_path, pdf_path=item.pdf_path)

    def _open_external_musicxml(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Open MusicXML File in VST Preview Player",
            initialdir=self.dir_var.get() or str(Path.home()),
            filetypes=[("MusicXML Files", "*.musicxml *.xml *.mxl"), ("All Files", "*.*")],
        )
        if chosen:
            xml_p = Path(chosen)
            # Check if a matching PDF sits alongside the MusicXML file
            sibling_pdf = xml_p.with_suffix(".pdf")
            matched_pdf = sibling_pdf if sibling_pdf.is_file() else None
            self._load_musicxml_into_player(xml_p, pdf_path=matched_pdf)

    def _load_musicxml_into_player(self, xml_path: Path, pdf_path: Path | None = None) -> None:
        try:
            self._stop_score()
            if pdf_path and pdf_path.is_file():
                self._load_pdf_into_reader(pdf_path, page_index=0)
            else:
                # Look for a matching PDF in imported items or sibling file
                sibling_pdf = xml_path.with_suffix(".pdf")
                if sibling_pdf.is_file():
                    self._load_pdf_into_reader(sibling_pdf, page_index=0)
                else:
                    for it in self._items:
                        if it.output_musicxml_path == xml_path or it.pdf_path.stem == xml_path.stem:
                            self._load_pdf_into_reader(it.pdf_path, page_index=0)
                            break

            score = parse_musicxml(xml_path)
            source_all_recommended_vsts(score.parts, query_github_release=False)
            self._current_score = score
            self._audio_dirty = True
            self.tempo_var.set(round(score.tempo_bpm))

            ts_num, ts_den = score.time_signature
            self.score_header_var.set(
                f"{score.title} ({score.composer})  •  {ts_num}/{ts_den}  •  "
                f"{score.total_measures} m.  •  {self._format_sec(score.total_duration_sec)}"
            )
            self.time_label_var.set(
                f"00:00 / {self._format_sec(score.total_duration_sec)}  |  Measure 1 / {score.total_measures}"
            )
            self.seek_slider.configure(to=max(1.0, score.total_duration_sec))
            self.seek_var.set(0.0)

            self._populate_vst_tree()
            self._redraw_score_canvas()
        except Exception as exc:
            messagebox.showerror("Failed to Load MusicXML", f"Could not parse {xml_path.name}:\n{exc}")

    def _populate_vst_tree(self) -> None:
        for row_id in self.vst_tree.get_children():
            self.vst_tree.delete(row_id)
        self._part_row_map.clear()

        if not self._current_score:
            return

        for part in self._current_score.parts:
            status_txt = (
                f"✔ Sourced ({part.local_vst_path.name})"
                if part.local_vst_path
                else "Recommended Open-Source VST"
            )
            audio_state = "Muted" if part.muted else f"Active ({int(part.volume * 100)}%)"
            row_id = self.vst_tree.insert(
                "",
                tk.END,
                values=(
                    part.part_name,
                    part.instrument_category.title(),
                    str(len(part.playable_notes)),
                    part.assigned_vst_name,
                    status_txt,
                    audio_state,
                ),
            )
            self._part_row_map[row_id] = part

        children = self.vst_tree.get_children()
        if children:
            self.vst_tree.selection_set(children[0])
            self._on_vst_part_selected()

    def _on_vst_part_selected(self, _event: object = None) -> None:
        sel = self.vst_tree.selection()
        if not sel or sel[0] not in self._part_row_map:
            return
        part = self._part_row_map[sel[0]]
        spec = VST_BY_ID.get(part.assigned_vst_id)
        if spec:
            self.part_vst_combo_var.set(f"{spec.id} — {spec.name}")

    def _on_part_vst_combo_changed(self, _event: object = None) -> None:
        sel = self.vst_tree.selection()
        if not sel or sel[0] not in self._part_row_map:
            return
        part = self._part_row_map[sel[0]]
        raw_val = self.part_vst_combo_var.get()
        vst_id = raw_val.split(" — ", 1)[0].strip()
        if vst_id in VST_BY_ID:
            spec = VST_BY_ID[vst_id]
            part.assigned_vst_id = spec.id
            part.assigned_vst_name = spec.name
            part.local_vst_path = source_open_source_vst_bundle(spec.id, query_github_release=False)
            self._audio_dirty = True
            self._populate_vst_tree()
            self.status_var.set(f"Assigned open-source VST '{spec.name}' to part '{part.part_name}'.")

    def _toggle_selected_part_mute(self) -> None:
        sel = self.vst_tree.selection()
        if not sel or sel[0] not in self._part_row_map:
            return
        part = self._part_row_map[sel[0]]
        part.muted = not part.muted
        self._audio_dirty = True
        self._populate_vst_tree()

    def _browse_custom_vst_for_part(self) -> None:
        sel = self.vst_tree.selection()
        if not sel or sel[0] not in self._part_row_map:
            messagebox.showinfo("Select an Instrument Part", "Select an instrument part in the VST Rack first.")
            return
        part = self._part_row_map[sel[0]]
        chosen = filedialog.askopenfilename(
            title=f"Select Open-Source .vst3 or .dll Plugin for {part.part_name}",
            initialdir=str(get_managed_vst_directory()),
            filetypes=[("VST Plugins", "*.vst3 *.dll *.vstprofile.json"), ("All Files", "*.*")],
        )
        if chosen:
            p = Path(chosen)
            part.local_vst_path = p
            part.assigned_vst_name = f"Custom VST ({p.name})"
            self._audio_dirty = True
            self._populate_vst_tree()

    def _source_vsts_for_current_score(self) -> None:
        parts = self._current_score.parts if self._current_score else None
        sourced_paths = source_all_recommended_vsts(parts=parts, query_github_release=True)
        if self._current_score:
            assign_recommended_vsts_to_parts(self._current_score.parts)
            self._populate_vst_tree()
            self._audio_dirty = True
        managed_dir = get_managed_vst_directory()
        self.status_var.set(
            f"Sourced {len(sourced_paths)} recommended open-source VST profile(s) into {managed_dir}."
        )
        messagebox.showinfo(
            "Open-Source VSTs Sourced",
            f"Successfully sourced and configured {len(sourced_paths)} recommended open-source VST instrument "
            f"bundle(s) in:\n{managed_dir}\n\n"
            "Each instrument part in your MusicXML score is now mapped to its top open-source VST acoustic profile.",
        )

    # -------------------------------------------------------------------------
    # Audio Playback & Live Playhead Cursor
    # -------------------------------------------------------------------------
    def _mark_audio_dirty(self) -> None:
        self._audio_dirty = True

    def _play_score(self) -> None:
        if not self._current_score:
            messagebox.showinfo("No MusicXML Loaded", "Convert a PDF or open a MusicXML file first.")
            return

        try:
            tempo_bpm = float(self.tempo_var.get())
        except (ValueError, tk.TclError):
            tempo_bpm = self._current_score.tempo_bpm

        if self._audio_dirty or not self._audio_player.is_paused:
            self.status_var.set("Synthesizing MusicXML parts with assigned open-source VST profiles...")
            self.root.update_idletasks()
            self._audio_player.load_and_render_score(self._current_score, tempo_override_bpm=tempo_bpm)
            self._audio_dirty = False
            self.seek_slider.configure(to=max(1.0, self._audio_player.duration_sec))

        start_pos = float(self.seek_var.get()) if self._audio_player.is_paused else 0.0
        self._audio_player.play(start_sec=start_pos)
        self.status_var.set(f"Playing '{self._current_score.title}' — Comparing PDF & MusicXML side-by-side...")

    def _pause_score(self) -> None:
        if self._audio_player.is_playing:
            self._audio_player.pause()
            self.status_var.set("Playback paused.")
        elif self._audio_player.is_paused:
            self._audio_player.play()
            self.status_var.set("Playback resumed.")

    def _stop_score(self) -> None:
        self._audio_player.stop()
        self.seek_var.set(0.0)
        self._pdf_highlight_ratio = None
        if self._current_pdf_path:
            self._render_current_pdf_page()
        self._update_playhead_cursor(0.0)

    def _on_seek_drag(self, _val: str) -> None:
        self._seeking_slider = True

    def _on_seek_release(self, _event: object) -> None:
        self._seeking_slider = False
        if self._current_score:
            target_sec = float(self.seek_var.get())
            self._audio_player.seek(target_sec)
            self._update_playhead_cursor(target_sec)

    def _export_wav(self) -> None:
        if not self._current_score:
            messagebox.showinfo("No MusicXML Loaded", "Load or convert a MusicXML file first.")
            return
        chosen = filedialog.asksaveasfilename(
            title="Export Synthesized Open-Source VST Audio to WAV",
            defaultextension=".wav",
            initialfile=f"{self._current_score.musicxml_path.stem}.wav",
            filetypes=[("WAV Audio", "*.wav")],
        )
        if not chosen:
            return
        try:
            tempo_bpm = float(self.tempo_var.get())
        except (ValueError, tk.TclError):
            tempo_bpm = self._current_score.tempo_bpm
        out_wav = synthesize_score_to_wav(
            self._current_score, Path(chosen), sample_rate=44100, tempo_override_bpm=tempo_bpm
        )
        messagebox.showinfo("WAV Exported", f"Audio rendered with open-source VST profiles to:\n{out_wav}")

    def _update_playhead_loop(self) -> None:
        if self._current_score and (self._audio_player.is_playing or self._audio_player.is_paused):
            pos = self._audio_player.get_position_sec()
            if not self._seeking_slider:
                self.seek_var.set(pos)
            self._update_playhead_cursor(pos)
        self.root.after(45, self._update_playhead_loop)

    def _update_playhead_cursor(self, pos_sec: float) -> None:
        if not self._current_score:
            return
        dur = max(0.01, self._audio_player.duration_sec or self._current_score.total_duration_sec)
        ratio = max(0.0, min(1.0, pos_sec / dur))
        cur_measure = min(
            self._current_score.total_measures,
            max(1, int(ratio * self._current_score.total_measures) + 1),
        )
        self.time_label_var.set(
            f"{self._format_sec(pos_sec)} / {self._format_sec(dur)}  |  "
            f"Measure {cur_measure} / {self._current_score.total_measures}"
        )

        total_w = getattr(self, "_canvas_score_width", 800)
        left_margin = 76
        x_pos = left_margin + ratio * max(100, total_w - left_margin - 30)
        self.score_canvas.coords("playhead", x_pos, 10, x_pos, max(200, self.score_canvas.winfo_height() - 10))

        # Auto-scroll MusicXML canvas to keep the red playhead in view during playback
        if self._audio_player.is_playing and total_w > 0:
            vis_w = max(200, self.score_canvas.winfo_width())
            target_frac = max(0.0, min(1.0, (x_pos - vis_w * 0.35) / total_w))
            self.score_canvas.xview_moveto(target_frac)

        # Synchronize the side-by-side PDF Reader page & active system highlight band
        if self._audio_player.is_playing or pos_sec > 0.0:
            self._sync_pdf_reader_to_playback_ratio(ratio)

    @staticmethod
    def _format_sec(seconds: float) -> str:
        s = max(0, int(round(seconds)))
        return f"{s // 60:02d}:{s % 60:02d}"

    # -------------------------------------------------------------------------
    # Visual Score Canvas (Staff Notation & Color Piano-Roll)
    # -------------------------------------------------------------------------
    def _on_score_canvas_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if not self._current_score:
            return
        canvas_x = self.score_canvas.canvasx(event.x)
        left_margin = 76
        total_w = getattr(self, "_canvas_score_width", 800)
        usable_w = max(100, total_w - left_margin - 30)
        ratio = max(0.0, min(1.0, (canvas_x - left_margin) / usable_w))
        dur = max(0.01, self._audio_player.duration_sec or self._current_score.total_duration_sec)
        target_sec = ratio * dur
        self.seek_var.set(target_sec)
        self._audio_player.seek(target_sec)
        self._update_playhead_cursor(target_sec)

    def _redraw_score_canvas(self) -> None:
        self.score_canvas.delete("all")
        w = max(420, self.score_canvas.winfo_width())
        h = max(180, self.score_canvas.winfo_height())

        if not self._current_score or not self._current_score.parts:
            self.score_canvas.create_text(
                w // 2,
                h // 2,
                text="Convert a PDF or select a converted row above\nto compare its MusicXML notation side-by-side with the PDF.",
                fill="#666666",
                font=("Segoe UI", 10),
                justify=tk.CENTER,
            )
            return

        score = self._current_score
        left_margin = 76
        px_per_beat = 34.0
        total_beats = max(8.0, score.total_beats)
        total_w = max(w, int(left_margin + total_beats * px_per_beat + 60))
        self._canvas_score_width = total_w
        self.score_canvas.configure(scrollregion=(0, 0, total_w, h))

        mode = self.view_mode_var.get()
        if mode == "staff":
            self._draw_staff_notation(score, total_w, h, left_margin, px_per_beat)
        else:
            self._draw_piano_roll(score, total_w, h, left_margin, px_per_beat)

        self.score_canvas.create_line(
            left_margin, 10, left_margin, h - 10, fill="#dc2626", width=2.5, tags=("playhead",)
        )

    def _draw_staff_notation(
        self,
        score: ParsedScore,
        total_w: int,
        h: int,
        left_margin: int,
        px_per_beat: float,
    ) -> None:
        """Render a readable 5-line Treble + Bass Grand Staff notation view of the parsed MusicXML."""
        treble_top = max(34, int(h * 0.20))
        line_spacing = 10
        bass_top = treble_top + 5 * line_spacing + 26

        self.score_canvas.create_text(
            14,
            treble_top + 2 * line_spacing,
            text="Treble\n(G Clef)",
            anchor=tk.W,
            fill="#333333",
            font=("Segoe UI", 8, "bold"),
        )
        self.score_canvas.create_text(
            14,
            bass_top + 2 * line_spacing,
            text="Bass\n(F Clef)",
            anchor=tk.W,
            fill="#333333",
            font=("Segoe UI", 8, "bold"),
        )

        for i in range(5):
            ty = treble_top + i * line_spacing
            by = bass_top + i * line_spacing
            self.score_canvas.create_line(left_margin, ty, total_w - 20, ty, fill="#888888")
            self.score_canvas.create_line(left_margin, by, total_w - 20, by, fill="#888888")

        beats_per_measure = max(1, score.time_signature[0]) * (4.0 / max(1, score.time_signature[1]))
        num_measures = max(1, score.total_measures)
        for m in range(num_measures + 1):
            bx = left_margin + m * beats_per_measure * px_per_beat
            self.score_canvas.create_line(
                bx, treble_top, bx, bass_top + 4 * line_spacing, fill="#bbbbbb", dash=(2, 2) if m > 0 else ()
            )
            if m < num_measures:
                self.score_canvas.create_text(
                    bx + 4, treble_top - 14, text=f"m.{m + 1}", anchor=tk.W, fill="#666666", font=("Segoe UI", 8)
                )

        diatonic_map = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
        treble_bottom_step = 4 * 7 + 2  # E4
        treble_bottom_y = treble_top + 4 * line_spacing
        bass_bottom_step = 2 * 7 + 4  # G2
        bass_bottom_y = bass_top + 4 * line_spacing

        for p_idx, part in enumerate(score.parts):
            if part.muted:
                continue
            color = PART_COLORS[p_idx % len(PART_COLORS)]
            for note in part.playable_notes:
                nx = left_margin + note.start_beat * px_per_beat + 6
                step_char = note.pitch_name[0].upper() if note.pitch_name else "C"
                oct_digits = "".join(ch for ch in note.pitch_name if ch.isdigit())
                octave = int(oct_digits) if oct_digits else (note.pitch_midi // 12 - 1)
                diatonic_pos = octave * 7 + diatonic_map.get(step_char, 0)

                if note.pitch_midi >= 60:
                    step_offset = diatonic_pos - treble_bottom_step
                    ny = treble_bottom_y - step_offset * (line_spacing / 2.0)
                else:
                    step_offset = diatonic_pos - bass_bottom_step
                    ny = bass_bottom_y - step_offset * (line_spacing / 2.0)

                if note.pitch_midi in (60, 61):
                    self.score_canvas.create_line(nx - 7, ny, nx + 7, ny, fill="#555555", width=1.2)

                filled = color if note.duration_beats < 2.0 else "#fdfbf7"
                self.score_canvas.create_oval(
                    nx - 5, ny - 3.5, nx + 5, ny + 3.5, fill=filled, outline=color, width=1.8
                )
                if note.duration_beats < 4.0:
                    self.score_canvas.create_line(nx + 4.5, ny, nx + 4.5, ny - 22, fill=color, width=1.5)

    def _draw_piano_roll(
        self,
        score: ParsedScore,
        total_w: int,
        h: int,
        left_margin: int,
        px_per_beat: float,
    ) -> None:
        """Render a multi-instrument color-coded Piano Roll view of the parsed MusicXML."""
        all_pitches = [n.pitch_midi for p in score.parts if not p.muted for n in p.playable_notes]
        min_pitch = max(21, (min(all_pitches) - 3) if all_pitches else 48)
        max_pitch = min(108, (max(all_pitches) + 3) if all_pitches else 84)
        pitch_span = max(12, max_pitch - min_pitch)

        top_pad = 22
        bot_pad = 16
        usable_h = max(80, h - top_pad - bot_pad)

        for midi_num in range(min_pitch, max_pitch + 1):
            if midi_num % 12 == 0:
                y = top_pad + usable_h * (1.0 - (midi_num - min_pitch) / pitch_span)
                oct_num = (midi_num // 12) - 1
                self.score_canvas.create_line(left_margin, y, total_w - 20, y, fill="#e5e7eb")
                self.score_canvas.create_text(
                    left_margin - 8, y, text=f"C{oct_num}", anchor=tk.E, fill="#555555", font=("Segoe UI", 8)
                )

        beats_per_measure = max(1, score.time_signature[0]) * (4.0 / max(1, score.time_signature[1]))
        for m in range(score.total_measures + 1):
            bx = left_margin + m * beats_per_measure * px_per_beat
            self.score_canvas.create_line(bx, top_pad, bx, h - bot_pad, fill="#d1d5db", dash=(2, 2))
            if m < score.total_measures:
                self.score_canvas.create_text(
                    bx + 3, 10, text=f"m.{m + 1}", anchor=tk.W, fill="#666666", font=("Segoe UI", 8)
                )

        note_h = max(4.0, min(12.0, usable_h / pitch_span))
        for p_idx, part in enumerate(score.parts):
            if part.muted:
                continue
            color = PART_COLORS[p_idx % len(PART_COLORS)]
            for note in part.playable_notes:
                x0 = left_margin + note.start_beat * px_per_beat
                x1 = max(x0 + 6, x0 + note.duration_beats * px_per_beat - 2)
                y_center = top_pad + usable_h * (1.0 - (note.pitch_midi - min_pitch) / pitch_span)
                self.score_canvas.create_rectangle(
                    x0,
                    y_center - note_h / 2,
                    x1,
                    y_center + note_h / 2,
                    fill=color,
                    outline="#ffffff",
                )

    # -------------------------------------------------------------------------
    # Dialogs: OMR Engine Settings & Open-Source VST Catalog Manager
    # -------------------------------------------------------------------------
    def _open_engine_settings_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("OMR Engine Configuration")
        dlg.geometry("680x310")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, textvariable=self.engine_status_var, wraplength=640).pack(anchor=tk.W, pady=(0, 8))
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="homr python.exe (blank = find it):").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.homr_python_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        def _browse() -> None:
            p = filedialog.askopenfilename(
                parent=dlg,
                title="Locate python.exe in homr's .venv\\Scripts folder",
                filetypes=[("Python Executable", "python.exe"), ("All Files", "*.*")],
            )
            if p:
                self.homr_python_var.set(p)
                self._refresh_engine_status()

        ttk.Button(row, text="Browse...", command=_browse).pack(side=tk.LEFT)

        arow = ttk.Frame(frame)
        arow.pack(fill=tk.X, pady=4)
        ttk.Label(arow, text="Audiveris.exe (blank = find it):").pack(side=tk.LEFT)
        ttk.Entry(arow, textvariable=self.audiveris_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        def _browse_audiveris() -> None:
            p = filedialog.askopenfilename(
                parent=dlg,
                title="Locate Audiveris.exe (usually in Program Files\\Audiveris)",
                filetypes=[("Audiveris", "Audiveris.exe"), ("All Files", "*.*")],
            )
            if p:
                self.audiveris_path_var.set(p)
                self._refresh_engine_status()

        ttk.Button(arow, text="Browse...", command=_browse_audiveris).pack(side=tk.LEFT)

        lrow = ttk.Frame(frame)
        lrow.pack(fill=tk.X, pady=4)
        ttk.Label(lrow, text="Legato python.exe (blank = find it):").pack(side=tk.LEFT)
        ttk.Entry(lrow, textvariable=self.legato_python_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        def _browse_legato() -> None:
            p = filedialog.askopenfilename(
                parent=dlg,
                title="Locate python.exe in Legato's .venv\\Scripts folder",
                filetypes=[("Python Executable", "python.exe"), ("All Files", "*.*")],
            )
            if p:
                self.legato_python_var.set(p)
                self._refresh_engine_status()

        ttk.Button(lrow, text="Browse...", command=_browse_legato).pack(side=tk.LEFT)

        def _save_and_close() -> None:
            self._refresh_engine_status()
            dlg.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(
            buttons,
            text="Open homr Repo (GitHub)",
            command=lambda: webbrowser.open("https://github.com/liebharc/homr"),
        ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Apply & Close", style="Accent.TButton", command=_save_and_close).pack(side=tk.RIGHT)

    def _open_vst_catalog_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Recommended Open-Source VST / VST3 Instrument Catalog")
        dlg.geometry("920x520")
        dlg.transient(self.root)

        frame = ttk.Frame(dlg, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Most Popular & Highly Recommended Open-Source .VST / .VST3 Plugins by Instrument",
            style="SubHeader.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))

        cols = ("category", "name", "developer", "license", "format", "instruments")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for col, (lbl, w) in {
            "category": ("Family", 85),
            "name": ("Open-Source VST Plugin", 250),
            "developer": ("Developer", 160),
            "license": ("License", 95),
            "format": ("Format", 115),
            "instruments": ("Matched Instruments", 180),
        }.items():
            tree.heading(col, text=lbl)
            tree.column(col, width=w, anchor=tk.W)

        spec_by_row: dict[str, str] = {}
        for spec in OPEN_SOURCE_VST_CATALOG:
            rid = tree.insert(
                "",
                tk.END,
                values=(
                    spec.instrument_category.title(),
                    spec.name,
                    spec.developer,
                    spec.license,
                    spec.plugin_format,
                    ", ".join(spec.instruments_matched[:4]),
                ),
            )
            spec_by_row[rid] = spec.id

        tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        desc_var = tk.StringVar(
            value="Select an open-source VST above to view details, source its profile, or open its GitHub release page."
        )
        ttk.Label(frame, textvariable=desc_var, wraplength=880, style="Subtle.TLabel").pack(
            anchor=tk.W, pady=(0, 8)
        )

        def _on_sel(_e: object = None) -> None:
            s = tree.selection()
            if s and s[0] in spec_by_row:
                sp = VST_BY_ID[spec_by_row[s[0]]]
                desc_var.set(f"{sp.name} ({sp.license}): {sp.description}  |  Repo: {sp.repo_url}")

        tree.bind("<<TreeviewSelect>>", _on_sel)

        btn_bar = ttk.Frame(frame)
        btn_bar.pack(fill=tk.X)

        def _source_selected() -> None:
            s = tree.selection()
            if not s or s[0] not in spec_by_row:
                return
            vid = spec_by_row[s[0]]
            out = source_open_source_vst_bundle(vid, query_github_release=True)
            if self._current_score:
                assign_recommended_vsts_to_parts(self._current_score.parts)
                self._populate_vst_tree()
            messagebox.showinfo(
                "Open-Source VST Sourced", f"Sourced '{VST_BY_ID[vid].name}' profile to:\n{out}", parent=dlg
            )

        def _open_github() -> None:
            s = tree.selection()
            if not s or s[0] not in spec_by_row:
                return
            vid = spec_by_row[s[0]]
            webbrowser.open(VST_BY_ID[vid].download_url)

        ttk.Button(
            btn_bar,
            text="⬇ Source Selected VST Profile",
            style="Accent.TButton",
            command=_source_selected,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btn_bar,
            text="⬇ Source All 12 Recommended Open-Source VSTs",
            command=self._source_vsts_for_current_score,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btn_bar,
            text="🔎 Deep Search & Auto-Download VSTs...",
            style="Accent.TButton",
            command=self._open_deep_vst_search_dialog,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btn_bar,
            text="🌐 Open Official GitHub Release / Download Page",
            command=_open_github,
        ).pack(side=tk.LEFT)
        ttk.Button(btn_bar, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)

    def _open_deep_vst_search_dialog(self) -> None:
        """Open the Deep Open-Source VST Search, Auto-Downloader & Manual Intervention Links dialog."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Deep Open-Source VST Search — Auto-Downloader & Manual Intervention Link Reporter")
        dlg.geometry("1120x680")
        dlg.minsize(920, 560)
        dlg.transient(self.root)

        scope_var = tk.StringVar(value="all")
        auto_dl_var = tk.BooleanVar(value=True)
        gh_search_var = tk.BooleanVar(value=True)
        summary_var = tk.StringVar(
            value="Click 'Run Deep VST Search & Auto-Download' to scan repositories, download available assets, and list manual links."
        )
        detail_var = tk.StringVar(value="Select any row below to inspect its local files, manual instructions, and clickable links.")

        report_holder: list[VSTDeepSearchReport | None] = [None]
        auto_row_map: dict[str, VSTDeepSearchItem] = {}
        manual_row_map: dict[str, VSTDeepSearchItem] = {}
        disc_row_map: dict[str, dict[str, object]] = {}

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # Top control bar
        top_box = ttk.LabelFrame(outer, text="1. Deep Search & Auto-Download Options", padding=8)
        top_box.pack(fill=tk.X, pady=(0, 8))

        ctrl_row = ttk.Frame(top_box)
        ctrl_row.pack(fill=tk.X)
        ttk.Label(ctrl_row, text="Search Scope:", style="SubHeader.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            ctrl_row,
            text="All Instrument Categories (Full Catalog)",
            value="all",
            variable=scope_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(
            ctrl_row,
            text="Current Score's Instruments Only",
            value="score",
            variable=scope_var,
        ).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Checkbutton(
            ctrl_row,
            text="Auto-download portable .zip / .vst3 / .sfz assets",
            variable=auto_dl_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            ctrl_row,
            text="Search GitHub API for additional open-source VST3 repos",
            variable=gh_search_var,
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(top_box, textvariable=summary_var, style="Subtle.TLabel").pack(anchor=tk.W, pady=(6, 0))

        # Notebook with 3 tabs: Auto-Downloaded, Manual Intervention Required, Live GitHub Discoveries
        nb = ttk.Notebook(outer)
        nb.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Tab 1: Automatically Downloaded
        tab_auto = ttk.Frame(nb, padding=6)
        nb.add(tab_auto, text="✔ Automatically Downloaded & Ready (0)")

        auto_cols = ("category", "name", "tag", "files", "repo")
        auto_tree = ttk.Treeview(tab_auto, columns=auto_cols, show="headings", selectmode="browse")
        for col, (lbl, w) in {
            "category": ("Family", 85),
            "name": ("Open-Source VST Setup", 250),
            "tag": ("Release", 80),
            "files": ("Auto-Downloaded Local Files (.vstprofile / .sfz / .vst3)", 350),
            "repo": ("Official Repository Link", 260),
        }.items():
            auto_tree.heading(col, text=lbl)
            auto_tree.column(col, width=w, anchor=tk.W)
        auto_vsb = ttk.Scrollbar(tab_auto, orient=tk.VERTICAL, command=auto_tree.yview)
        auto_tree.configure(yscrollcommand=auto_vsb.set)
        auto_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        auto_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tab 2: Manual Intervention Required (with Associated Links)
        tab_man = ttk.Frame(nb, padding=6)
        nb.add(tab_man, text="⚠ Requires Manual Intervention — Associated Links (0)")

        man_cols = ("category", "name", "reason", "release_url", "sample_url")
        man_tree = ttk.Treeview(tab_man, columns=man_cols, show="headings", selectmode="browse")
        for col, (lbl, w) in {
            "category": ("Family", 80),
            "name": ("Recommended VST / Library", 230),
            "reason": ("Why Manual Intervention is Required", 340),
            "release_url": ("Installer / Release Link", 210),
            "sample_url": ("Sample Library / SFZ Bank Link", 210),
        }.items():
            man_tree.heading(col, text=lbl)
            man_tree.column(col, width=w, anchor=tk.W)
        man_vsb = ttk.Scrollbar(tab_man, orient=tk.VERTICAL, command=man_tree.yview)
        man_tree.configure(yscrollcommand=man_vsb.set)
        man_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        man_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tab 3: Live GitHub Discoveries
        tab_disc = ttk.Frame(nb, padding=6)
        nb.add(tab_disc, text="🌟 Live GitHub VST3 Discoveries (0)")

        disc_cols = ("name", "stars", "license", "description", "url")
        disc_tree = ttk.Treeview(tab_disc, columns=disc_cols, show="headings", selectmode="browse")
        for col, (lbl, w) in {
            "name": ("Repository", 190),
            "stars": ("Stars", 65),
            "license": ("License", 90),
            "description": ("Description", 420),
            "url": ("GitHub URL", 260),
        }.items():
            disc_tree.heading(col, text=lbl)
            disc_tree.column(col, width=w, anchor=tk.W)
        disc_tree.pack(fill=tk.BOTH, expand=True)

        # Details & Clickable Link Action Box
        detail_box = ttk.LabelFrame(outer, text="Selected VST Details, Instructions & Direct Links", padding=8)
        detail_box.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(detail_box, textvariable=detail_var, wraplength=1060).pack(anchor=tk.W, pady=(0, 6))

        link_btns = ttk.Frame(detail_box)
        link_btns.pack(fill=tk.X)

        def _get_active_item() -> VSTDeepSearchItem | None:
            cur_tab = nb.index(nb.select())
            if cur_tab == 0:
                s = auto_tree.selection()
                if s and s[0] in auto_row_map:
                    return auto_row_map[s[0]]
            elif cur_tab == 1:
                s = man_tree.selection()
                if s and s[0] in manual_row_map:
                    return manual_row_map[s[0]]
            return None

        def _open_url_field(field_name: str) -> None:
            cur_tab = nb.index(nb.select())
            if cur_tab == 2:
                s = disc_tree.selection()
                if s and s[0] in disc_row_map:
                    url = str(disc_row_map[s[0]].get("releases_url") or disc_row_map[s[0]].get("repo_url") or "")
                    if url:
                        webbrowser.open(url)
                return
            item = _get_active_item()
            if not item:
                messagebox.showinfo("Select a VST", "Select a VST row in the table above first.", parent=dlg)
                return
            url = getattr(item, field_name, "") or item.release_page_url or item.repo_url
            if url:
                webbrowser.open(url)

        ttk.Button(
            link_btns,
            text="🌐 Open Direct Download / Release Page",
            style="Accent.TButton",
            command=lambda: _open_url_field("direct_asset_url"),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            link_btns,
            text="🌐 Open Sample Library / SFZ Bank Link",
            command=lambda: _open_url_field("sample_library_url"),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            link_btns,
            text="🌐 Open Official GitHub Repository",
            command=lambda: _open_url_field("repo_url"),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            link_btns,
            text="🌐 Open Documentation / Setup Guide",
            command=lambda: _open_url_field("docs_url"),
        ).pack(side=tk.LEFT, padx=(0, 6))

        def _open_markdown_report() -> None:
            rep = report_holder[0]
            if rep and rep.markdown_report_path and rep.markdown_report_path.is_file():
                webbrowser.open(rep.markdown_report_path.as_uri())
            else:
                messagebox.showinfo("Run Search First", "Run the deep search first to generate the report.", parent=dlg)

        ttk.Button(
            link_btns,
            text="📄 Open Full Markdown Report",
            command=_open_markdown_report,
        ).pack(side=tk.RIGHT)
        ttk.Button(
            link_btns,
            text="📂 Open Local VST Folder",
            command=lambda: webbrowser.open(get_managed_vst_directory().as_uri()),
        ).pack(side=tk.RIGHT, padx=(0, 6))

        def _on_tree_select(_e: object = None) -> None:
            cur_tab = nb.index(nb.select())
            if cur_tab == 2:
                s = disc_tree.selection()
                if s and s[0] in disc_row_map:
                    d = disc_row_map[s[0]]
                    detail_var.set(
                        f"GitHub Discovery: {d.get('name')} (★ {d.get('stars')}) — {d.get('description')}\n"
                        f"Releases Link: {d.get('releases_url')}"
                    )
                return
            item = _get_active_item()
            if not item:
                return
            links_txt = "  |  ".join(f"{k}: {v}" for k, v in item.associated_links.items())
            detail_var.set(
                f"{item.name} ({item.developer}, {item.license})\n"
                f"Status / Reason: {item.manual_reason}\n"
                f"Steps: {item.manual_instructions}\n"
                f"Links: {links_txt}"
            )

        auto_tree.bind("<<TreeviewSelect>>", _on_tree_select)
        man_tree.bind("<<TreeviewSelect>>", _on_tree_select)
        disc_tree.bind("<<TreeviewSelect>>", _on_tree_select)
        man_tree.bind("<Double-1>", lambda _e: _open_url_field("direct_asset_url"))
        auto_tree.bind("<Double-1>", lambda _e: _open_url_field("release_page_url"))
        disc_tree.bind("<Double-1>", lambda _e: _open_url_field("repo_url"))

        def _run_deep_search() -> None:
            summary_var.set("Running deep search across open-source VST repositories and downloading available assets...")
            dlg.update_idletasks()
            parts = (
                self._current_score.parts
                if (scope_var.get() == "score" and self._current_score)
                else None
            )

            def _prog(msg: str, _i: int, _t: int) -> None:
                summary_var.set(msg)
                dlg.update_idletasks()

            rep = deep_search_and_download_vsts(
                parts=parts,
                download_portable_assets=auto_dl_var.get(),
                search_github_live=gh_search_var.get(),
                progress_callback=_prog,
            )
            report_holder[0] = rep

            # Populate Tab 1 (Auto-downloaded)
            for rid in auto_tree.get_children():
                auto_tree.delete(rid)
            auto_row_map.clear()
            for item in rep.auto_downloaded:
                files_str = ", ".join(p.name for p in item.auto_downloaded_files)
                rid = auto_tree.insert(
                    "",
                    tk.END,
                    values=(
                        item.instrument_category.title(),
                        item.name,
                        item.release_tag or "Latest",
                        files_str,
                        item.repo_url,
                    ),
                )
                auto_row_map[rid] = item

            # Populate Tab 2 (Manual intervention required)
            for rid in man_tree.get_children():
                man_tree.delete(rid)
            manual_row_map.clear()
            for item in rep.manual_intervention:
                rid = man_tree.insert(
                    "",
                    tk.END,
                    values=(
                        item.instrument_category.title(),
                        item.name,
                        item.manual_reason,
                        item.direct_asset_url or item.release_page_url,
                        item.sample_library_url,
                    ),
                )
                manual_row_map[rid] = item

            # Populate Tab 3 (Live GitHub discoveries)
            for rid in disc_tree.get_children():
                disc_tree.delete(rid)
            disc_row_map.clear()
            for d in rep.live_github_discoveries:
                rid = disc_tree.insert(
                    "",
                    tk.END,
                    values=(
                        d.get("name", ""),
                        str(d.get("stars", 0)),
                        d.get("license", ""),
                        d.get("description", ""),
                        d.get("releases_url", ""),
                    ),
                )
                disc_row_map[rid] = d

            nb.tab(tab_auto, text=f"✔ Automatically Downloaded & Ready ({len(rep.auto_downloaded)})")
            nb.tab(tab_man, text=f"⚠ Requires Manual Intervention — Associated Links ({len(rep.manual_intervention)})")
            nb.tab(tab_disc, text=f"🌟 Live GitHub VST3 Discoveries ({len(rep.live_github_discoveries)})")

            summary_var.set(
                f"Deep search complete: {len(rep.auto_downloaded)} VST bundle(s) auto-downloaded, "
                f"{len(rep.manual_intervention)} item(s) have manual installer/sample links. "
                f"Report saved to: {rep.markdown_report_path}"
            )
            if self._current_score:
                assign_recommended_vsts_to_parts(self._current_score.parts)
                self._populate_vst_tree()

            if man_tree.get_children():
                man_tree.selection_set(man_tree.get_children()[0])
            if auto_tree.get_children():
                auto_tree.selection_set(auto_tree.get_children()[0])
            _on_tree_select()

        ttk.Button(
            ctrl_row,
            text="🔎 Run Deep VST Search & Auto-Download",
            style="Accent.TButton",
            command=_run_deep_search,
        ).pack(side=tk.RIGHT)

        dlg.after(120, _run_deep_search)

    def _open_multi_piece_splitter_dialog(self) -> None:
        """Open the Multi-Piece PDF Splitter on the highlighted PDF (also a program of its own: `split_tool`)."""
        dlg = tk.Toplevel(self.root)
        dlg.transient(self.root)
        initial_pdf: Path | None = None
        sel = self.pdf_tree.selection()
        if sel and sel[0] in self._row_to_item:
            initial_pdf = Path(self._row_to_item[sel[0]].pdf_path)
        elif self._current_pdf_path:
            initial_pdf = Path(self._current_pdf_path)

        def _after_split(pdf: Path, created: list[Path], out_folder: Path, queue_them: bool) -> None:
            self.status_var.set(f"Split '{pdf.name}' into {len(created)} separate PDF file(s) in {out_folder}.")
            if queue_them:
                self.dir_var.set(str(out_folder))
                self._load_folder()

        build_split_window(dlg, initial_pdf, browse_dir=self.dir_var.get, on_split=_after_split)

    def _on_close(self) -> None:
        self._stop_score()
        self.root.destroy()


def launch_gui(initial_directory: Path | None = None) -> int:
    """Launch the Lento_ConvertPDF converter & Open-Source VST Player desktop GUI."""
    root = tk.Tk()
    LentoConvertPDFApp(root, initial_directory=initial_directory)
    root.mainloop()
    return 0
