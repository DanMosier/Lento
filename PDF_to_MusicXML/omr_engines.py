"""Folder scanning and batch conversion of PDFs with homr."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Callable

from .homr_runner import EngineAvailability, OMRConfig, check_homr, run_homr
from .models import VALID_ENGINES, PdfConversionItem

try:
    import pypdf
except ImportError:  # pragma: no cover
    pypdf = None  # type: ignore[assignment]

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None  # type: ignore[assignment]


def get_pdf_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF file using pypdfium2 or pypdf."""
    if pdfium is not None:
        try:
            doc = pdfium.PdfDocument(str(pdf_path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            pass
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(str(pdf_path))
            return len(reader.pages)
        except Exception:
            pass
    return 1


def scan_folder_for_pdfs(
    folder: Path,
    recursive: bool = True,
    output_dir: Path | None = None,
) -> list[PdfConversionItem]:
    """Import all PDF files within a folder (and optionally subfolders) for batch conversion."""
    folder = folder.resolve()
    if not folder.is_dir():
        return []

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_paths = sorted(
        (p for p in folder.glob(pattern) if p.is_file() and "_duplicates" not in p.parts),
        key=lambda p: str(p.relative_to(folder)).lower(),
    )

    items: list[PdfConversionItem] = []
    for pdf_path in pdf_paths:
        try:
            rel_path = str(pdf_path.relative_to(folder))
        except ValueError:
            rel_path = pdf_path.name

        try:
            size_bytes = pdf_path.stat().st_size
        except OSError:
            size_bytes = 0

        page_count = get_pdf_page_count(pdf_path)

        # Check if an existing MusicXML already sits in the target output dir
        target_dir = output_dir.resolve() if output_dir else pdf_path.parent
        existing_xml: Path | None = None
        for ext in (".musicxml", ".xml", ".mxl"):
            candidate = target_dir / f"{pdf_path.stem}{ext}"
            if candidate.is_file():
                existing_xml = candidate
                break

        item = PdfConversionItem(
            pdf_path=pdf_path,
            relative_path=rel_path,
            selected=True,
            page_count=page_count,
            file_size_bytes=size_bytes,
            status="converted" if existing_xml else "pending",
            output_musicxml_path=existing_xml,
        )
        items.append(item)

    return items


def extract_mxl_to_musicxml(mxl_path: Path, dest_musicxml_path: Path) -> Path:
    """Unpack a compressed MusicXML (.mxl) archive into a standard uncompressed .musicxml file."""
    with zipfile.ZipFile(mxl_path, "r") as zf:
        names = zf.namelist()
        rootfile_path: str | None = None
        if "META-INF/container.xml" in names:
            try:
                container_bytes = zf.read("META-INF/container.xml")
                c_root = ET.fromstring(container_bytes)
                for elem in c_root.iter():
                    if elem.tag.endswith("rootfile") and elem.attrib.get("full-path"):
                        rootfile_path = elem.attrib["full-path"]
                        break
            except Exception:
                pass
        if not rootfile_path or rootfile_path not in names:
            xml_candidates = [
                n for n in names if n.lower().endswith((".xml", ".musicxml")) and not n.startswith("META-INF")
            ]
            if not xml_candidates:
                raise ValueError(f"No XML score found inside {mxl_path}")
            rootfile_path = xml_candidates[0]

        xml_bytes = zf.read(rootfile_path)
        dest_musicxml_path.parent.mkdir(parents=True, exist_ok=True)
        dest_musicxml_path.write_bytes(xml_bytes)
    return dest_musicxml_path


def convert_single_pdf(
    item: PdfConversionItem, config: OMRConfig, availability: EngineAvailability | None = None
) -> PdfConversionItem:
    """Convert one PDF with homr. Failures are recorded on the item; nothing is written for them."""
    if config.engine not in VALID_ENGINES:
        raise ValueError(f"Unsupported OMR engine '{config.engine}'. Choose from {VALID_ENGINES}.")

    start_t = time.perf_counter()
    item.status = "converting"
    item.engine_used = config.engine
    item.error_message = ""
    item.detected_instruments = []
    item.quality = None

    out_dir = config.output_dir.resolve() if config.output_dir else item.pdf_path.parent
    target = out_dir / f"{item.pdf_path.stem}.musicxml"
    try:
        if config.overwrite_existing or not target.is_file():
            status = availability or check_homr(config)
            if not status.installed:
                raise RuntimeError(status.details)
            if config.gpu == "force" and not status.cuda:
                raise RuntimeError(f"GPU required but not in use: {status.details}")
            item.detected_instruments, item.quality = run_homr(
                item.pdf_path, target, config, page_count=get_pdf_page_count(item.pdf_path)
            )
        item.output_musicxml_path = target
        item.status = "converted"
    except Exception as exc:
        item.status = "failed"
        item.output_musicxml_path = None
        item.error_message = str(exc)
    finally:
        item.duration_sec = time.perf_counter() - start_t

    return item


def batch_convert_pdfs(
    items: list[PdfConversionItem],
    config: OMRConfig,
    progress_callback: Callable[[PdfConversionItem, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[PdfConversionItem]:
    """Batch-convert all selected PdfConversionItems in order."""
    selected_items = [it for it in items if it.selected]
    total = len(selected_items)
    availability = check_homr(config) if selected_items else None

    for idx, item in enumerate(selected_items, start=1):
        if cancel_check and cancel_check():
            break
        convert_single_pdf(item, config, availability)
        if progress_callback:
            progress_callback(item, idx, total)

    return items
