"""Runs inside Legato's environment:  python legato_bridge.py SOURCE OUT.musicxml --model M --device D

LEGATO (https://github.com/guang-yng/legato, models at huggingface.co/guangyangmusic) reads a score image and
writes ABC notation. This script renders a PDF, runs the model, and turns the ABC into MusicXML with the
abc2xml.py that ships in the Legato repository (its utils/ folder).

Legato-2 (guangyangmusic/legato-2) reads a whole score as one tall image, finding the systems with its own YOLO
detector. Its pipeline (legato.pipeline.Legato2) is used when the installed code has it. Otherwise the original
model (LegatoModel, e.g. guangyangmusic/legato) reads each page on its own and the pages are joined.

Progress lines start with LENTO_; the last line is LENTO_DONE or an error.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

# This folder's file names (models.py, quality.py, ...) must not hide the modules Legato imports.
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p and Path(p).resolve() != Path(_HERE)]


def log(text: str) -> None:
    print(text, flush=True)


def legato_root(given: Path | None) -> Path:
    """The Legato repository: where its legato/ package and utils/abc2xml.py live. The repository is not an
    installable package, so its folder goes on the path."""
    if given:
        sys.path.insert(0, str(given))
    import legato

    # legato/ has no __init__.py (a namespace package), so legato.__file__ is None: use the folder it was found in
    return Path(next(iter(legato.__path__))).resolve().parent


def render(source: Path, work: Path, dpi: int) -> list[Path]:
    """One PNG per page (an image input is used as it is)."""
    if source.suffix.lower() in IMAGE_SUFFIXES:
        return [source]
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(source))
    pages = []
    for i in range(len(doc)):
        image = doc[i].render(scale=dpi / 72).to_pil().convert("RGB")
        path = work / f"page_{i + 1}.png"
        image.save(path)
        pages.append(path)
    doc.close()
    return pages


def stack(pages: list[Path], work: Path) -> Path:
    """The pages one under another, as Legato-2 reads a PDF."""
    if len(pages) == 1:
        return pages[0]
    from PIL import Image

    images = [Image.open(p).convert("RGB") for p in pages]
    width = max(im.width for im in images)
    tall = Image.new("RGB", (width, sum(im.height for im in images)), "white")
    y = 0
    for im in images:
        tall.paste(im, (0, y))
        y += im.height
    path = work / "score_tall.png"
    tall.save(path)
    return path


def read_legato2(pages: list[Path], work: Path, model: str, device: str) -> list[str]:
    from legato.pipeline import Legato2  # type: ignore[import-not-found]

    omr = Legato2.from_pretrained(model, device=device)
    log(f"LENTO_PAGE 1/{len(pages)}")
    return [omr(str(stack(pages, work)))]


def read_legato1(pages: list[Path], model: str, device: str, beams: int) -> list[str]:
    import torch
    from PIL import Image
    from transformers import AutoProcessor, GenerationConfig

    from legato.models import LegatoModel

    net = LegatoModel.from_pretrained(model).to(device=device)
    if device.startswith("cuda"):
        net = net.half()
    processor = AutoProcessor.from_pretrained(model)
    config = GenerationConfig(max_length=2048, num_beams=beams, repetition_penalty=1.1)
    abcs = []
    for i, page in enumerate(pages, start=1):
        log(f"LENTO_PAGE {i}/{len(pages)}")
        inputs = processor(images=[Image.open(page).convert("RGB")], truncation=True, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            out = net.generate(**inputs, generation_config=config, use_model_defaults=False)
        abcs.append(processor.batch_decode(out.tolist(), skip_special_tokens=True)[0])
    return abcs


def to_musicxml(abc: str, root: Path) -> ET.Element:
    """ABC -> MusicXML with Legato's own clean-up and its copy of abc2xml."""
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from utils.convert import cleanup_abc  # type: ignore[import-not-found]

        abc = cleanup_abc(abc)
    except Exception as exc:  # the clean-up is a nicety; abc2xml copes with most raw output
        log(f"LENTO_NOTE ABC clean-up skipped: {exc}")
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "utils" / "abc2xml.py"), "-"],
        input=abc.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    text = res.stdout.decode("utf-8", "replace").strip()
    if res.returncode != 0 or not text:
        raise RuntimeError(f"abc2xml could not convert Legato's ABC: {res.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    return ET.fromstring(text)


def join(scores: list[ET.Element]) -> ET.Element:
    """Append the measures of later pages to the first page's parts, by position, renumbering them."""
    first = scores[0]
    parts = first.findall("part")
    count = max((len(p.findall("measure")) for p in parts), default=0)
    for later in scores[1:]:
        added = 0
        for k, part in enumerate(later.findall("part")):
            if k >= len(parts):
                break
            measures = part.findall("measure")
            for n, measure in enumerate(measures, start=1):
                measure.set("number", str(count + n))
                parts[k].append(measure)
            added = max(added, len(measures))
        count += added
    return first


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="guangyangmusic/legato-2")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--beams", type=int, default=1)
    parser.add_argument("--abc", type=Path, help="also save the raw ABC here")
    parser.add_argument("--root", type=Path, help="the Legato repository (default: wherever legato imports from)")
    args = parser.parse_args()

    root = legato_root(args.root)
    with tempfile.TemporaryDirectory(prefix="legato_pages_") as tmp:
        work = Path(tmp)
        pages = render(args.source, work, args.dpi)
        if not pages:
            raise RuntimeError("the PDF has no pages")
        try:
            import legato.pipeline  # noqa: F401  # type: ignore[import-not-found]

            has_pipeline = True
        except ImportError:
            has_pipeline = False
        if has_pipeline:
            log("LENTO_READER legato2-pipeline")
            abcs = read_legato2(pages, work, args.model, args.device)
        else:
            model = args.model
            if model.rstrip("/").endswith("legato-2"):
                # Legato-2 needs its pipeline (system detector + context); without it, read with the first model
                model = "guangyangmusic/legato"
                log("LENTO_NOTE this Legato code has no Legato-2 pipeline; reading with guangyangmusic/legato instead")
            log(f"LENTO_READER legato-model-per-page {model}")
            abcs = read_legato1(pages, model, args.device, args.beams)

    if args.abc:
        args.abc.write_text("\n\n%% next page\n\n".join(abcs), encoding="utf-8")
    score = join([to_musicxml(abc, root) for abc in abcs])
    args.output.write_bytes(ET.tostring(score, encoding="utf-8", xml_declaration=True))
    log("LENTO_DONE")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"LENTO_ERROR {type(exc).__name__}: {exc}")
        sys.exit(1)
