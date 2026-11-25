"""Locate 5-line staves on a page image, for the PDF splitter. Not used for transcription."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass
class DetectedStaff:
    """A 5-line musical staff detected via horizontal dark-pixel projection."""

    line_ys: list[int]  # 5 y-coordinates from top line (line 1) to bottom line (line 5)
    interline: float  # Average vertical distance between adjacent staff lines

    @property
    def top_y(self) -> int:
        return self.line_ys[0]

    @property
    def bottom_y(self) -> int:
        return self.line_ys[-1]


def _get_pixels_2d(gray_img: Image.Image) -> tuple[int, int, list[int]]:
    w, h = gray_img.size
    flat = (
        list(gray_img.get_flattened_data())
        if hasattr(gray_img, "get_flattened_data")
        else list(gray_img.getdata())
    )
    return w, h, flat


def detect_staves_in_image(gray_img: Image.Image) -> list[DetectedStaff]:
    """Detect 5-line musical staves using horizontal dark-pixel projection."""
    # Downsample width slightly for fast horizontal projection while preserving full vertical resolution
    orig_w, orig_h = gray_img.size
    proj_w = min(orig_w, 480)
    small = gray_img.resize((proj_w, orig_h), Image.Resampling.BILINEAR)
    w, h, flat = _get_pixels_2d(small)

    # Compute dark pixel count per row (threshold < 185)
    row_dark: list[int] = [0] * h
    for y in range(h):
        row_start = y * w
        cnt = 0
        for x in range(int(w * 0.12), int(w * 0.88)):
            if flat[row_start + x] < 185:
                cnt += 1
        row_dark[y] = cnt

    span_w = max(1, int(w * 0.76))
    # Staff lines span across the printable page width (at least 50% of the central span)
    min_line_hits = int(span_w * 0.50)
    max_line_thickness = max(7, int(h * 0.010))

    # Cluster contiguous dark rows into single thin horizontal line centers
    candidate_ys: list[int] = []
    y = 2
    while y < h - 2:
        if row_dark[y] >= min_line_hits:
            run_start = y
            while y < h - 2 and row_dark[y] >= min_line_hits:
                y += 1
            run_end = y - 1
            run_thickness = run_end - run_start + 1
            if run_thickness <= max_line_thickness:
                candidate_ys.append((run_start + run_end) // 2)
        else:
            y += 1

    # Group candidate horizontal lines into 5-line staves with consistent spacing and white interline spaces
    staves: list[DetectedStaff] = []
    idx = 0
    while idx + 4 < len(candidate_ys):
        group = candidate_ys[idx : idx + 5]
        gaps = [group[i + 1] - group[i] for i in range(4)]
        avg_gap = sum(gaps) / 4.0
        if 4.0 <= avg_gap <= 45.0 and all(abs(g - avg_gap) <= max(3.5, avg_gap * 0.45) for g in gaps):
            avg_line_dark = sum(row_dark[ly] for ly in group) / 5.0
            mid_darks = [row_dark[(group[i] + group[i + 1]) // 2] for i in range(4)]
            avg_mid_dark = sum(mid_darks) / 4.0
            if avg_mid_dark < avg_line_dark * 0.75:
                staves.append(DetectedStaff(line_ys=group, interline=avg_gap))
                idx += 5
                continue
        idx += 1

    return staves
