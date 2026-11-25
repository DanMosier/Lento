"""Multi-piece sheet music PDF analyzer and splitter with overlapping page & mid-page cutoff support.

Automatically recognizes whether a multi-score PDF can be split easily using `pypdf`
(via PDF bookmark outlines or embedded text headers/page resets) vs. requiring a
more robust Vision System (combining `pypdfium2` staff-top layout geometry,
mid-page inter-staff gap & title-block analysis, native Windows WinRT OCR, and optional Vision LLM).

Supports overlapping page ranges (e.g., Piece 1 = pages 20-26, Piece 2 = pages 26-30) where
a new piece starts partway down a shared page, automatically finding the vertical cutoff
point (`cutoff_y_ratio`) on the shared page and cropping each split PDF cleanly at the cut line.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pypdf
from PIL import Image

from .staff_detection import detect_staves_in_image

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None  # type: ignore[assignment]


@dataclass
class PdfPieceSegment:
    """Represents a single musical piece (page range + optional mid-page vertical cutoffs) inside a PDF."""

    index: int  # 1-based piece index
    title: str
    composer: str = ""
    start_page: int = 1  # 1-based inclusive
    end_page: int = 1  # 1-based inclusive
    start_y_ratio: float = 0.0  # 0.0 = top of start_page; >0.0 = starts partway down start_page
    end_y_ratio: float = 1.0  # 1.0 = bottom of end_page; <1.0 = ends partway down end_page
    confidence: float = 0.85
    detection_source: str = "pypdf-text"
    notes: str = ""
    selected: bool = True
    output_path: Path | None = None

    @property
    def page_count(self) -> int:
        return max(1, self.end_page - self.start_page + 1)

    @property
    def has_midpage_start(self) -> bool:
        return 0.02 < self.start_y_ratio < 0.98

    @property
    def has_midpage_end(self) -> bool:
        return 0.02 < self.end_y_ratio < 0.98

    @property
    def page_range_label(self) -> str:
        start_str = f"{self.start_page} ({int(round(self.start_y_ratio * 100))}%↓)" if self.has_midpage_start else f"{self.start_page}"
        end_str = f"{self.end_page} (↑{int(round(self.end_y_ratio * 100))}%)" if self.has_midpage_end else f"{self.end_page}"
        return f"p. {start_str}–{end_str}"

    @property
    def proposed_filename(self) -> str:
        safe_title = _sanitize_filename(self.title or f"Piece {self.index}")
        safe_comp = _sanitize_filename(self.composer) if self.composer else ""
        if safe_comp and safe_comp.lower() not in safe_title.lower():
            return f"{safe_comp} - {safe_title}.pdf"
        return f"{safe_title}.pdf"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "composer": self.composer,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "start_y_ratio": round(self.start_y_ratio, 3),
            "end_y_ratio": round(self.end_y_ratio, 3),
            "page_count": self.page_count,
            "confidence": round(self.confidence, 3),
            "detection_source": self.detection_source,
            "notes": self.notes,
            "selected": self.selected,
            "proposed_filename": self.proposed_filename,
            "output_path": str(self.output_path) if self.output_path else None,
        }


@dataclass
class SplitAnalysisReport:
    """Result of inspecting a PDF for multiple pieces and determining pypdf vs. Vision splitting."""

    pdf_path: Path
    total_pages: int = 0
    recommended_method: str = "pypdf"  # "pypdf" | "vision"
    method_used: str = "pypdf"  # "pypdf" | "vision"
    method_reason: str = ""
    embedded_text_page_ratio: float = 0.0
    has_bookmarks: bool = False
    segments: list[PdfPieceSegment] = field(default_factory=list)

    @property
    def is_multi_piece(self) -> bool:
        return len(self.segments) > 1


_TITLE_KEYWORDS_RE = re.compile(
    r"\b(?:sonata|sonatina|prelude|pr[eé]lude|fugue|etude|[eé]tude|nocturne|waltz|valse|"
    r"mazurka|polonaise|impromptu|ballade|scherzo|rhapsody|minuet|menuet|gavotte|bourr[eé]e|"
    r"gigue|sarabande|allemande|courante|aria|canon|concerto|symphony|quartet|trio|duet|"
    r"march|fantasia|fantasy|caprice|capriccio|intermezzo|romance|serenade|lied|song|"
    r"op\.\s*\d+|bwv\s*\d+|k\.\s*\d+|no\.\s*\d+|movement\s+[ivx\d]+)\b",
    flags=re.IGNORECASE,
)

_NEW_PIECE_HEADER_RE = re.compile(
    r"^(?:(?:no\.|number|piece|movement|suite|part)\s*\d+|[ivx]{1,4}\.\s+[A-Z]|"
    r"\d+\.\s+[A-Z][a-zA-Z\s]{2,})",
    flags=re.IGNORECASE,
)

_PAGE_ONE_RESET_RE = re.compile(
    r"(?:^\s*1\s*$|^\s*page\s*1\b|^\s*-\s*1\s*-\s*$|^\s*1\s*/\s*\d+\s*$)",
    flags=re.IGNORECASE,
)

_COPYRIGHT_RE = re.compile(r"(?:©|copyright|\ball\s+rights\s+reserved\b|\bpublic\s+domain\b)", flags=re.IGNORECASE)


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned[:110] if cleaned else "Untitled Piece"


def _extract_outline_bookmarks(reader: pypdf.PdfReader) -> list[tuple[str, int, float]]:
    """Extract `(bookmark_title, 1-based_page_number, top_y_ratio)` from a pypdf PdfReader outline.

    Note: unlike top-of-page-only bookmark extractors, this preserves multiple bookmarks on the
    SAME page (when a second piece starts midway down a shared page).
    """
    raw_bookmarks: list[tuple[str, int, float]] = []
    try:
        outline = getattr(reader, "outline", None)
        if not outline:
            return []

        def _walk(items: list[Any]) -> None:
            for item in items:
                if isinstance(item, list):
                    _walk(item)
                else:
                    title = str(getattr(item, "title", "") or "").strip()
                    try:
                        page_idx = reader.get_destination_page_number(item)
                        if page_idx is not None and title:
                            pnum = int(page_idx) + 1
                            # Check if destination carries a vertical top coordinate
                            y_ratio = 0.0
                            top_val = getattr(item, "top", None)
                            if isinstance(top_val, (int, float)):
                                page_obj = reader.pages[int(page_idx)]
                                page_h = float(page_obj.mediabox.height or 792.0)
                                if 0 < float(top_val) < page_h:
                                    r = 1.0 - (float(top_val) / page_h)
                                    if 0.12 <= r <= 0.88:
                                        y_ratio = round(r, 3)
                            raw_bookmarks.append((title, pnum, y_ratio))
                    except Exception:
                        pass

        _walk(outline)
    except Exception:
        return []

    valid = [(t, p, yr) for t, p, yr in raw_bookmarks if 1 <= p <= len(reader.pages)]
    valid.sort(key=lambda x: (x[1], x[2]))
    return valid


def find_midpage_cutoff_y_ratio(
    pdf_path: Path,
    page_number: int,
    search_min_ratio: float = 0.16,
    search_max_ratio: float = 0.84,
) -> tuple[float, bool, str]:
    """Find the optimal vertical cutoff ratio (`0.0` = top, `1.0` = bottom) partway through a page.

    Returns `(cutoff_y_ratio, is_confident_midpage_split, reason)`:
    - Inspects 5-line musical staves and horizontal ink projection on `page_number` (1-based).
    - Looks for an abnormally wide inter-staff vertical gap in the middle of the page (especially one
      containing a centered title header block below a whitespace separator band).
    - Places the cutoff line in the clean whitespace band just below the upper piece's last staff and
      just above the lower piece's title header.
    """
    if pdfium is None:
        return 0.50, False, "default 50% midpoint (pypdfium2 unavailable)"

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        total = len(doc)
        if total == 0:
            return 0.50, False, "empty PDF"
        p_idx = max(0, min(total - 1, page_number - 1))
        page = doc[p_idx]
        bitmap = page.render(scale=1.5)
        pil_gray = bitmap.to_pil().convert("L")
    finally:
        doc.close()

    w, h = pil_gray.size
    if h < 100 or w < 100:
        return 0.50, False, "page too small"

    staves = detect_staves_in_image(pil_gray)
    flat = (
        list(pil_gray.get_flattened_data())
        if hasattr(pil_gray, "get_flattened_data")
        else list(pil_gray.getdata())
    )

    # Compute row-by-row dark ink count in the central printable column [15%..85%]
    x0 = int(w * 0.15)
    x1 = int(w * 0.85)
    center_x0 = int(w * 0.25)
    center_x1 = int(w * 0.75)

    row_dark = [0] * h
    center_dark = [0] * h
    for y in range(h):
        roff = y * w
        c_all = 0
        c_mid = 0
        for x in range(x0, x1):
            if flat[roff + x] < 185:
                c_all += 1
                if center_x0 <= x < center_x1:
                    c_mid += 1
        row_dark[y] = c_all
        center_dark[y] = c_mid

    # Case 1: Multiple 5-line staves detected on the page -> inspect inter-staff gaps
    if len(staves) >= 2:
        gaps: list[tuple[int, int, int, float]] = []  # (gap_idx, gap_top_y, gap_bot_y, gap_height)
        for i in range(len(staves) - 1):
            g_top = staves[i].bottom_y + int(max(4, staves[i].interline * 0.8))
            g_bot = staves[i + 1].top_y - int(max(4, staves[i + 1].interline * 0.8))
            g_h = float(max(1, staves[i + 1].top_y - staves[i].bottom_y))
            mid_ratio = ((staves[i].bottom_y + staves[i + 1].top_y) * 0.5) / h
            if search_min_ratio <= mid_ratio <= search_max_ratio:
                gaps.append((i, g_top, g_bot, g_h))

        if gaps:
            all_raw_gaps = [float(staves[i + 1].top_y - staves[i].bottom_y) for i in range(len(staves) - 1)]
            median_gap = sorted(all_raw_gaps)[len(all_raw_gaps) // 2] if all_raw_gaps else 60.0

            best_cut_y = int(h * 0.50)
            best_score = -1.0
            best_reason = ""
            is_strong_midpage = False

            for i, g_top, g_bot, g_h in gaps:
                if g_bot <= g_top + 6:
                    continue
                # Check if there is a whitespace band in the top portion of the gap followed by centered title ink
                gap_span = g_bot - g_top
                top_band_end = g_top + max(4, int(gap_span * 0.45))
                bot_band_start = top_band_end

                # Find the whitest row in [g_top .. top_band_end] for the cleanest cut line
                whitest_y = g_top + (top_band_end - g_top) // 2
                min_ink = 999999
                for y in range(g_top, top_band_end + 1):
                    # Smooth 3-row window
                    y_clamped = max(1, min(h - 2, y))
                    ink = row_dark[y_clamped - 1] + row_dark[y_clamped] + row_dark[y_clamped + 1]
                    if ink < min_ink:
                        min_ink = ink
                        whitest_y = y_clamped

                # Measure centered title ink in [bot_band_start .. g_bot] (where the new piece's title sits)
                title_zone_rows = max(1, g_bot - bot_band_start)
                title_zone_ink = sum(center_dark[y] for y in range(bot_band_start, g_bot))
                title_ink_density = title_zone_ink / max(1.0, title_zone_rows * (center_x1 - center_x0))

                gap_expansion = g_h / max(10.0, median_gap)
                score = gap_expansion * 0.55 + (1.0 if title_ink_density >= 0.025 else 0.0) * 0.45 - (min_ink / max(1.0, w))

                if score > best_score:
                    best_score = score
                    best_cut_y = whitest_y
                    # Confident mid-page new piece if gap is noticeably larger than normal inter-staff gap
                    # and contains a centered title block above the next staff
                    if (gap_expansion >= 1.28 and title_ink_density >= 0.02) or gap_expansion >= 1.55:
                        is_strong_midpage = True
                    best_reason = (
                        f"mid-page cutoff at {best_cut_y / h:.0%} between staff {i + 1} and staff {i + 2} "
                        f"(gap={int(g_h)}px, title-ink={title_ink_density:.1%})"
                    )

            cutoff_ratio = round(max(search_min_ratio, min(search_max_ratio, best_cut_y / h)), 3)
            return cutoff_ratio, is_strong_midpage, best_reason

    # Case 2: Fallback horizontal whitespace band search across [search_min_ratio .. search_max_ratio]
    y_min = max(10, int(h * search_min_ratio))
    y_max = min(h - 10, int(h * search_max_ratio))
    window = max(6, int(h * 0.015))

    best_y = (y_min + y_max) // 2
    lowest_window_ink = 999999999
    for y in range(y_min, y_max):
        w_ink = sum(row_dark[max(0, y - window) : min(h, y + window)])
        if w_ink < lowest_window_ink:
            lowest_window_ink = w_ink
            best_y = y

    cutoff_ratio = round(best_y / h, 3)
    return cutoff_ratio, False, f"whitespace band cutoff at {cutoff_ratio:.0%} of page height"


def resolve_overlapping_page_cutoffs(
    pdf_path: Path,
    segments: list[PdfPieceSegment],
) -> list[PdfPieceSegment]:
    """Ensure any consecutive segments sharing an overlapping boundary page have a mid-page cutoff ratio."""
    if len(segments) < 2:
        return segments

    for i in range(len(segments) - 1):
        curr_seg = segments[i]
        next_seg = segments[i + 1]

        # If Piece i ends on the same page where Piece i+1 starts (e.g. 20-26 and 26-30)
        if curr_seg.end_page == next_seg.start_page:
            shared_page = curr_seg.end_page
            # If user or analyzer already set a custom mid-page cutoff on either segment, synchronize them
            if curr_seg.has_midpage_end and not next_seg.has_midpage_start:
                next_seg.start_y_ratio = curr_seg.end_y_ratio
            elif next_seg.has_midpage_start and not curr_seg.has_midpage_end:
                curr_seg.end_y_ratio = next_seg.start_y_ratio
            elif not curr_seg.has_midpage_end and not next_seg.has_midpage_start:
                cutoff_y, _, reason = find_midpage_cutoff_y_ratio(pdf_path, shared_page)
                curr_seg.end_y_ratio = cutoff_y
                next_seg.start_y_ratio = cutoff_y
                note_add = f"shared page {shared_page} split at {cutoff_y:.0%} ({reason})"
                if note_add not in curr_seg.notes:
                    curr_seg.notes = f"{curr_seg.notes}; {note_add}".strip("; ")
                if note_add not in next_seg.notes:
                    next_seg.notes = f"{next_seg.notes}; {note_add}".strip("; ")
        else:
            # Non-overlapping boundary between curr_seg and next_seg
            if curr_seg.end_page < next_seg.start_page:
                curr_seg.end_y_ratio = 1.0
                next_seg.start_y_ratio = 0.0

    return segments


def _analyze_page_embedded_text(page_text: str, page_num: int) -> tuple[bool, float, str, str, str]:
    """Check if a page's embedded text indicates the start of a new piece at the top of the page."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in page_text.splitlines() if ln.strip()]
    if not lines:
        return False, 0.0, "", "", ""

    top_lines = lines[:5]
    bottom_lines = lines[-3:]

    score = 0.0
    reasons: list[str] = []
    candidate_title = ""
    candidate_composer = ""

    for idx, ln in enumerate(top_lines):
        if len(ln) <= 3 and ln.isdigit():
            continue
        if _NEW_PIECE_HEADER_RE.search(ln):
            score += 0.45
            reasons.append(f"numbered header '{ln[:40]}'")
            if not candidate_title:
                candidate_title = ln
        if _TITLE_KEYWORDS_RE.search(ln):
            score += 0.40 if idx <= 2 else 0.25
            reasons.append(f"title keyword in '{ln[:40]}'")
            if not candidate_title:
                candidate_title = ln
        if " - " in ln and not candidate_title:
            parts = ln.split(" - ", 1)
            candidate_composer = parts[0].strip()
            candidate_title = parts[1].strip()
            score += 0.35

    if page_num > 1:
        for ln in top_lines[:2] + bottom_lines:
            if _PAGE_ONE_RESET_RE.match(ln):
                score += 0.45
                reasons.append("page number reset to 1")
                break

    for ln in bottom_lines:
        if _COPYRIGHT_RE.search(ln):
            score += 0.25
            reasons.append("first-page copyright footer")
            break

    for ln in top_lines[1:4]:
        if re.search(
            r"\b(?:bach|mozart|beethoven|chopin|schubert|brahms|debussy|ravel|liszt|mendelssohn|"
            r"schumann|handel|haydn|vivaldi|tchaikovsky|rachmaninoff|prokofiev|shostakovich|"
            r"faur[eé]|satie|grieg|dvorak|mahler|strauss)\b",
            ln,
            flags=re.IGNORECASE,
        ):
            if not candidate_composer:
                candidate_composer = ln
            score += 0.20
            reasons.append(f"composer header '{ln[:35]}'")
            break

    if not candidate_title:
        for ln in top_lines:
            if sum(1 for c in ln if c.isalpha()) >= 3:
                candidate_title = ln
                break

    is_start = (page_num == 1) or (score >= 0.45)
    conf = min(0.98, max(0.55, score + (0.30 if page_num == 1 else 0.15)))
    return is_start, conf, candidate_title or f"Piece starting on Page {page_num}", candidate_composer, ", ".join(reasons)


def _detect_midpage_embedded_text_header(page_text: str) -> tuple[bool, float, str, float]:
    """Check if a page's embedded text contains a new piece header midway down the page (lines 5..-2).

    Returns `(found_midpage_start, estimated_y_ratio, detected_title, confidence)`.
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in page_text.splitlines() if ln.strip()]
    if len(lines) < 7:
        return False, 0.5, "", 0.0

    for idx in range(3, len(lines) - 1):
        ln = lines[idx]
        if _NEW_PIECE_HEADER_RE.search(ln) or (
            _TITLE_KEYWORDS_RE.search(ln) and len(ln) <= 55 and ln[0].isupper()
        ):
            est_ratio = round(max(0.20, min(0.80, idx / max(1, len(lines)))), 3)
            return True, est_ratio, ln, 0.78
    return False, 0.5, "", 0.0


def _run_winrt_ocr_on_header(pil_img: Image.Image) -> list[str]:
    """Run native in-process Windows WinRT OCR on a header crop of a rendered PDF page."""
    if sys.platform != "win32":
        return []
    try:
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter

        async def _ocr_async() -> list[str]:
            rgba = pil_img.convert("RGBA")
            w, h = rgba.size
            writer = DataWriter()
            writer.write_bytes(rgba.tobytes())
            ibuf = writer.detach_buffer()
            bmp = SoftwareBitmap.create_copy_from_buffer(
                ibuf, BitmapPixelFormat.RGBA8, w, h, BitmapAlphaMode.PREMULTIPLIED
            )
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                langs = list(OcrEngine.available_recognizer_languages)
                if not langs:
                    return []
                engine = OcrEngine.try_create_from_language(langs[0])
            if engine is None:
                return []
            res = await engine.recognize_async(bmp)
            return [re.sub(r"\s+", " ", ln.text or "").strip() for ln in res.lines if (ln.text or "").strip()]

        return asyncio.run(_ocr_async())
    except Exception:
        return []


def _query_vision_llm_for_page_header(pil_img: Image.Image) -> tuple[bool, str, str, float] | None:
    """Optional Gemini / OpenAI Vision LLM check on a page header when API key is configured."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        import requests

        buf = io.BytesIO()
        rgb = pil_img.convert("RGB")
        rgb.thumbnail((1000, 600))
        rgb.save(buf, format="JPEG", quality=82)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        prompt = (
            "Inspect this sheet music page region. Does a NEW musical piece/score start here "
            "(with a title header above the staff), or is it a continuation of a previous piece? "
            'Respond ONLY with JSON: {"is_new_piece": true/false, "title": "Piece Title or null", '
            '"composer": "Composer or null", "confidence": 0.9}'
        )
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        resp = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            cands = data.get("candidates") or []
            if cands:
                txt = "".join(str(p.get("text", "")) for p in cands[0].get("content", {}).get("parts", []))
                parsed = json.loads(txt)
                return (
                    bool(parsed.get("is_new_piece")),
                    str(parsed.get("title") or "").strip(),
                    str(parsed.get("composer") or "").strip(),
                    float(parsed.get("confidence") or 0.8),
                )
    except Exception:
        pass
    return None


def _analyze_pages_with_vision(
    pdf_path: Path,
    use_winrt_ocr: bool = True,
    use_vision_llm: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> list[PdfPieceSegment]:
    """Inspect rendered PDF pages using visual layout geometry (top-of-page AND mid-page new piece starts)."""
    if pdfium is None:
        raise RuntimeError("pypdfium2 is required for the Vision PDF splitter.")

    doc = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        return []

    # Tuple: (1-based_page_num, start_y_ratio, title, composer, confidence, source, notes)
    page_starts: list[tuple[int, float, str, str, float, str, str]] = []
    prev_page_bottom_blank_ratio = 0.0

    try:
        for idx in range(total_pages):
            pnum = idx + 1
            if progress_callback:
                progress_callback(f"Vision system inspecting page {pnum} / {total_pages}...", pnum, total_pages)

            page = doc[idx]
            bitmap = page.render(scale=1.5)
            pil_gray = bitmap.to_pil().convert("L")
            w, h = pil_gray.size

            staves = detect_staves_in_image(pil_gray)
            if staves:
                first_staff_top_ratio = staves[0].top_y / max(1.0, float(h))
                last_staff_bot_ratio = staves[-1].bottom_y / max(1.0, float(h))
            else:
                first_staff_top_ratio = 0.15
                last_staff_bot_ratio = 0.85

            header_bot_y = int(h * min(0.26, max(0.14, first_staff_top_ratio - 0.02)))
            header_crop = pil_gray.crop(
                (int(w * 0.18), int(h * 0.04), int(w * 0.82), max(int(h * 0.08), header_bot_y))
            )
            small_hdr = header_crop.resize((64, 24))
            hdr_pixels = (
                list(small_hdr.get_flattened_data())
                if hasattr(small_hdr, "get_flattened_data")
                else list(small_hdr.getdata())
            )
            dark_hdr_count = sum(1 for px in hdr_pixels if px < 175)
            header_ink_ratio = dark_hdr_count / max(1, len(hdr_pixels))

            visual_score = 0.0
            visual_notes: list[str] = []

            if pnum == 1:
                visual_score = 0.90
                visual_notes.append("first page of PDF")
            else:
                if first_staff_top_ratio >= 0.22:
                    visual_score += 0.45
                    visual_notes.append(f"large top title margin (first staff at {first_staff_top_ratio:.0%})")
                elif first_staff_top_ratio >= 0.18 and header_ink_ratio >= 0.025:
                    visual_score += 0.30
                    visual_notes.append(f"indented first staff ({first_staff_top_ratio:.0%})")

                if header_ink_ratio >= 0.03:
                    visual_score += 0.25
                    visual_notes.append(f"centered title banner ink ({header_ink_ratio:.1%})")

                if prev_page_bottom_blank_ratio >= 0.25:
                    visual_score += 0.30
                    visual_notes.append(
                        f"previous page ended early ({prev_page_bottom_blank_ratio:.0%} bottom margin)"
                    )

            prev_page_bottom_blank_ratio = max(0.0, 1.0 - last_staff_bot_ratio)

            ocr_title = ""
            ocr_composer = ""
            detection_source = "vision-layout"

            if pnum == 1 or visual_score >= 0.30 or use_winrt_ocr:
                top_crop = pil_gray.crop((0, 0, w, int(h * 0.28)))
                ocr_lines = _run_winrt_ocr_on_header(top_crop) if use_winrt_ocr else []
                if ocr_lines:
                    detection_source = "vision-layout+ocr"
                    ocr_text = "\n".join(ocr_lines)
                    is_txt_start, txt_conf, t_title, t_comp, t_reason = _analyze_page_embedded_text(ocr_text, pnum)
                    if is_txt_start and pnum > 1:
                        visual_score = max(visual_score, txt_conf)
                        if t_reason:
                            visual_notes.append(f"OCR: {t_reason}")
                    ocr_title = t_title
                    ocr_composer = t_comp

                if use_vision_llm and (pnum == 1 or visual_score >= 0.35):
                    llm_res = _query_vision_llm_for_page_header(top_crop)
                    if llm_res is not None:
                        llm_is_new, llm_title, llm_comp, llm_conf = llm_res
                        detection_source = "vision-llm"
                        if llm_is_new:
                            visual_score = max(visual_score, llm_conf)
                            ocr_title = llm_title or ocr_title
                            ocr_composer = llm_comp or ocr_composer
                            visual_notes.append("verified by Vision LLM")
                        elif pnum > 1 and llm_conf >= 0.80:
                            visual_score = min(visual_score, 0.25)

            top_piece_started_on_this_page = False
            if pnum == 1 or visual_score >= 0.45:
                top_piece_started_on_this_page = True
                piece_num = len(page_starts) + 1
                final_title = ocr_title or f"{pdf_path.stem} - Piece {piece_num}"
                page_starts.append(
                    (
                        pnum,
                        0.0,
                        final_title,
                        ocr_composer,
                        min(0.98, max(0.60, visual_score)),
                        detection_source,
                        "; ".join(visual_notes) or "visual piece boundary",
                    )
                )

            # Check if a NEW piece starts MIDWAY through this page (creating an overlapping shared page!)
            if not top_piece_started_on_this_page or pnum == 1:
                cutoff_y, is_midpage_split, mid_reason = find_midpage_cutoff_y_ratio(pdf_path, pnum)
                if is_midpage_split and (not top_piece_started_on_this_page or cutoff_y >= 0.38):
                    mid_title = ""
                    mid_comp = ""
                    if use_winrt_ocr:
                        mid_crop = pil_gray.crop((0, int(h * cutoff_y), w, min(h, int(h * (cutoff_y + 0.22)))))
                        mid_ocr_lines = _run_winrt_ocr_on_header(mid_crop)
                        if mid_ocr_lines:
                            _, _, mid_title, mid_comp, _ = _analyze_page_embedded_text(
                                "\n".join(mid_ocr_lines), pnum
                            )
                    piece_num = len(page_starts) + 1
                    page_starts.append(
                        (
                            pnum,
                            cutoff_y,
                            mid_title or f"{pdf_path.stem} - Piece {piece_num}",
                            mid_comp,
                            0.88,
                            "vision-midpage",
                            f"mid-page piece start on shared page {pnum} ({mid_reason})",
                        )
                    )
    finally:
        doc.close()

    segments = _build_segments_from_starts(page_starts, total_pages)
    return resolve_overlapping_page_cutoffs(pdf_path, segments)


def _build_segments_from_starts(
    page_starts: list[tuple[int, float, str, str, float, str, str]],
    total_pages: int,
) -> list[PdfPieceSegment]:
    """Convert a list of piece starts `(page_num, start_y_ratio, ...)` into `PdfPieceSegment` objects.

    When piece `i+1` has `start_y_ratio > 0.02` on page `P` (starts partway down page `P`),
    piece `i` ends on that SAME overlapping page `P` with `end_y_ratio = start_y_ratio`!
    """
    if not page_starts:
        return [
            PdfPieceSegment(
                index=1,
                title="Piece 1",
                start_page=1,
                end_page=max(1, total_pages),
                start_y_ratio=0.0,
                end_y_ratio=1.0,
                confidence=0.80,
                detection_source="pypdf-text",
                notes="Single piece spanning entire PDF",
            )
        ]

    segments: list[PdfPieceSegment] = []
    for i, (start_p, start_yr, title, composer, conf, src, notes) in enumerate(page_starts):
        if i + 1 < len(page_starts):
            next_p, next_yr, *_ = page_starts[i + 1]
            if next_p == start_p or next_yr > 0.02:
                # Overlapping shared boundary page! Piece i ends partway down `next_p`
                end_p = max(start_p, next_p)
                end_yr = next_yr if next_yr > 0.02 else 0.50
            else:
                end_p = max(start_p, next_p - 1)
                end_yr = 1.0
        else:
            end_p = total_pages
            end_yr = 1.0

        segments.append(
            PdfPieceSegment(
                index=i + 1,
                title=title,
                composer=composer,
                start_page=start_p,
                end_page=end_p,
                start_y_ratio=start_yr,
                end_y_ratio=end_yr,
                confidence=conf,
                detection_source=src,
                notes=notes,
                selected=True,
            )
        )
    return segments


def analyze_multi_piece_pdf(
    pdf_path: Path,
    mode: str = "auto",  # "auto" | "pypdf" | "vision"
    use_winrt_ocr: bool = True,
    use_vision_llm: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> SplitAnalysisReport:
    """Analyze a PDF to determine whether it can be split easily via `pypdf` vs. a Vision System, and detect piece ranges."""
    pdf_path = pdf_path.resolve()
    reader = pypdf.PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    if total_pages == 0:
        return SplitAnalysisReport(
            pdf_path=pdf_path,
            total_pages=0,
            recommended_method="pypdf",
            method_used="pypdf",
            method_reason="Empty PDF (0 pages).",
        )

    # 1. Inspect PDF bookmarks/outlines via pypdf (including multiple bookmarks sharing a page)
    bookmarks = _extract_outline_bookmarks(reader)
    has_bookmarks = len(bookmarks) >= 2

    # 2. Inspect embedded text on every page via pypdf
    page_texts: list[str] = []
    pages_with_meaningful_text = 0
    for idx, page in enumerate(reader.pages):
        if progress_callback and mode != "vision":
            progress_callback(f"pypdf scanning page {idx + 1} / {total_pages}...", idx + 1, total_pages)
        try:
            txt = (page.extract_text() or "").strip()
        except Exception:
            txt = ""
        page_texts.append(txt)
        alpha_count = sum(1 for c in txt if c.isalpha())
        if alpha_count >= 12:
            pages_with_meaningful_text += 1

    text_ratio = pages_with_meaningful_text / max(1, total_pages)

    # 3. Run pypdf bookmark / text boundary detection
    pypdf_starts: list[tuple[int, float, str, str, float, str, str]] = []
    if has_bookmarks:
        seen_pages_count: dict[int, int] = {}
        for b_title, b_page, b_yr in bookmarks:
            comp = ""
            title = b_title
            if " - " in b_title:
                comp, title = [s.strip() for s in b_title.split(" - ", 1)]
            count_on_page = seen_pages_count.get(b_page, 0)
            seen_pages_count[b_page] = count_on_page + 1

            # If this bookmark is the 2nd+ piece starting on the same page (or has a mid-page y_ratio),
            # find the exact visual cutoff point partway down that shared page!
            start_yr = b_yr
            if count_on_page >= 1 and start_yr <= 0.02:
                start_yr, _, _ = find_midpage_cutoff_y_ratio(pdf_path, b_page)
            pypdf_starts.append(
                (b_page, start_yr, title, comp, 0.96, "pypdf-outline", f"PDF bookmark '{b_title}'")
            )
    else:
        for idx, txt in enumerate(page_texts):
            pnum = idx + 1
            is_start, conf, title, comp, reason = _analyze_page_embedded_text(txt, pnum)
            if is_start:
                if pnum == 1 and not title:
                    title = f"{pdf_path.stem} - Piece 1"
                pypdf_starts.append(
                    (
                        pnum,
                        0.0,
                        title,
                        comp,
                        conf,
                        "pypdf-text",
                        reason or ("first page" if pnum == 1 else "embedded text header"),
                    )
                )
            else:
                # Check if a new piece starts midway down this page in embedded text
                found_mid, est_yr, mid_title, mid_conf = _detect_midpage_embedded_text_header(txt)
                if found_mid:
                    cut_yr, is_vis_mid, _ = find_midpage_cutoff_y_ratio(pdf_path, pnum)
                    final_yr = cut_yr if is_vis_mid else est_yr
                    pypdf_starts.append(
                        (
                            pnum,
                            final_yr,
                            mid_title,
                            "",
                            mid_conf,
                            "pypdf-midpage",
                            f"mid-page header '{mid_title[:35]}' at {final_yr:.0%}",
                        )
                    )

    # 4. Determine recommended method: "pypdf" vs. "vision"
    if has_bookmarks:
        recommended_method = "pypdf"
        method_reason = (
            f"Easy Split with pypdf — Found {len(bookmarks)} structured PDF bookmark outlines pointing directly to each piece."
        )
    elif text_ratio >= 0.60 and (len(pypdf_starts) >= 2 or total_pages == 1):
        recommended_method = "pypdf"
        method_reason = (
            f"Easy Split with pypdf — PDF has rich embedded text ({text_ratio:.0%} of pages) and clear text title/page-reset boundaries "
            f"({len(pypdf_starts)} piece(s) detected)."
        )
    elif text_ratio < 0.40:
        recommended_method = "vision"
        method_reason = (
            f"Robust Vision System Recommended — PDF is scanned/image-based (only {text_ratio:.0%} of pages have embedded text in pypdf). "
            "Using visual staff-top & mid-page layout geometry + OCR to find piece boundaries."
        )
    else:
        recommended_method = "vision"
        method_reason = (
            f"Robust Vision System Recommended — Embedded text ({text_ratio:.0%} of pages) lacks explicit title/bookmark markers in pypdf. "
            "Using visual staff-margin & mid-page cutoff inspection."
        )

    chosen_mode = recommended_method if mode == "auto" else mode.lower().strip()

    if chosen_mode == "pypdf":
        segments = _build_segments_from_starts(pypdf_starts, total_pages)
        segments = resolve_overlapping_page_cutoffs(pdf_path, segments)
    else:
        segments = _analyze_pages_with_vision(
            pdf_path,
            use_winrt_ocr=use_winrt_ocr,
            use_vision_llm=use_vision_llm,
            progress_callback=progress_callback,
        )
        pypdf_by_page = {p: (t, c) for p, yr, t, c, _, _, _ in pypdf_starts if t and yr <= 0.02}
        for seg in segments:
            if seg.start_page in pypdf_by_page and not seg.has_midpage_start:
                pt, pc = pypdf_by_page[seg.start_page]
                if pt and ("Piece " in seg.title or not seg.title):
                    seg.title = pt
                if pc and not seg.composer:
                    seg.composer = pc

    return SplitAnalysisReport(
        pdf_path=pdf_path,
        total_pages=total_pages,
        recommended_method=recommended_method,
        method_used=chosen_mode,
        method_reason=method_reason,
        embedded_text_page_ratio=text_ratio,
        has_bookmarks=has_bookmarks,
        segments=segments,
    )


def _crop_pdf_page_vertical(
    page: pypdf.PageObject,
    top_y_ratio: float,
    bottom_y_ratio: float,
) -> pypdf.PageObject:
    """Crop a deep-copied pypdf PageObject vertically between `top_y_ratio` (0=top) and `bottom_y_ratio` (1=bottom)."""
    cropped = copy.deepcopy(page)
    mb = cropped.mediabox
    left = float(mb.left)
    right = float(mb.right)
    bottom = float(mb.bottom)
    top = float(mb.top)
    height = top - bottom
    if height <= 0:
        return cropped

    clamped_top_r = max(0.0, min(0.95, top_y_ratio))
    clamped_bot_r = max(clamped_top_r + 0.05, min(1.0, bottom_y_ratio))

    # In PDF coordinate space, y=bottom is the bottom edge and y=top is the top edge
    new_upper_y = bottom + height * (1.0 - clamped_top_r)
    new_lower_y = bottom + height * (1.0 - clamped_bot_r)

    for box_attr in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
        box = getattr(cropped, box_attr, None)
        if box is not None:
            try:
                box.lower_left = (left, new_lower_y)
                box.upper_right = (right, new_upper_y)
            except Exception:
                pass
    return cropped


def execute_pdf_split(
    pdf_path: Path,
    segments: list[PdfPieceSegment],
    output_dir: Path | None = None,
    prefix_index: bool = True,
) -> list[Path]:
    """Split `pdf_path` into separate `.pdf` files for each selected `PdfPieceSegment`.

    Automatically resolves overlapping pages (e.g., Piece 1 = 20-26, Piece 2 = 26-30) by finding
    the mid-page vertical cutoff point on the shared page and cropping the top half into Piece 1's
    last page and the bottom half into Piece 2's first page.
    """
    pdf_path = pdf_path.resolve()
    dest_dir = output_dir.resolve() if output_dir else pdf_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Ensure any overlapping page ranges have resolved mid-page cutoff ratios
    resolve_overlapping_page_cutoffs(pdf_path, segments)

    reader = pypdf.PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    created_files: list[Path] = []
    used_paths: set[Path] = set()

    selected_segments = [s for s in segments if s.selected]
    for seg in selected_segments:
        writer = pypdf.PdfWriter()
        start_idx = max(0, min(total_pages - 1, seg.start_page - 1))
        end_idx = max(start_idx, min(total_pages - 1, seg.end_page - 1))

        for p_i in range(start_idx, end_idx + 1):
            top_r = seg.start_y_ratio if (p_i == start_idx and seg.has_midpage_start) else 0.0
            bot_r = seg.end_y_ratio if (p_i == end_idx and seg.has_midpage_end) else 1.0

            if top_r > 0.02 or bot_r < 0.98:
                cropped_page = _crop_pdf_page_vertical(reader.pages[p_i], top_y_ratio=top_r, bottom_y_ratio=bot_r)
                writer.add_page(cropped_page)
            else:
                writer.add_page(reader.pages[p_i])

        base_name = seg.proposed_filename
        if prefix_index and not re.match(r"^\d+\s*[-_.]", base_name):
            base_name = f"{seg.index:02d} - {base_name}"

        candidate_path = dest_dir / base_name
        counter = 2
        while candidate_path in used_paths or (candidate_path.exists() and candidate_path.resolve() == pdf_path):
            candidate_path = dest_dir / f"{Path(base_name).stem} ({counter}).pdf"
            counter += 1

        with candidate_path.open("wb") as f:
            writer.write(f)

        used_paths.add(candidate_path)
        seg.output_path = candidate_path
        created_files.append(candidate_path)

    return created_files
