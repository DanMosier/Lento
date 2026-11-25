"""Runs inside homr's environment:  python homr_bridge.py trace.json <homr arguments>

Starts homr's own main() and, on the side, records what homr knows but does not report: how sure the decoder
was of each symbol, and whether the layout of a page was lost. As long as every system has the same instruments it
only observes, and the score homr writes is unchanged. Where instruments come and go, homr would mix them up; the
score is then read one system at a time instead (system_reader.py), if it has labels to tell them apart.
If homr's internals move in an update, the trace holds an error and homr still runs.
"""

import importlib.util
import json
import sys
from pathlib import Path

trace_path = Path(sys.argv[1])
sys.argv = ["homr", *sys.argv[2:]]
trace: dict = {"pages": []}

import homr.main as homr_main  # noqa: E402


class LayoutChanged(BaseException):
    """Ends homr's own run. Not an Exception, so that homr does not report it as a failure."""


def load(name: str):
    """Import a file from this folder. The folder is not on the path: its names could hide homr's modules."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def observe() -> None:
    import numpy as np
    from homr import pdf_utils, staff_parsing
    from homr.autocrop import autocrop_with_offset
    from homr.system_repair import _layout
    from homr.transformer.decoder_inference import ScoreDecoder

    def top_probability(logits) -> float:
        z = logits[0, -1].astype(np.float64)
        z = np.exp(z - z.max())
        return float(z.max() / z.sum())

    class Recorder:
        """Stands in for the decoder's session and looks at each step's output."""

        def __init__(self, net, binding) -> None:
            self.net, self.binding = net, binding
            self.steps: list[list[float]] = []

        def run_with_iobinding(self, iobinding) -> None:
            self.net.run_with_iobinding(iobinding=iobinding)
            try:
                outputs = self.binding.get_outputs()
                self.steps.append([top_probability(outputs[i].numpy()) for i in (0, 1, 2)])  # rhythm, pitch, accidental
            except Exception as exc:
                trace["error"] = repr(exc)

    generate = ScoreDecoder.generate
    parse_staffs = homr_main.parse_staffs
    process_image = homr_main.process_image
    assign_parts = staff_parsing._assign_parts
    run_homr = homr_main.run_homr
    crops: list[tuple[int, int, int, int]] = []
    watch: dict = {"on": True, "layout": None}

    def traced_generate(self, *args, **kwargs):
        net, recorder = self.net, Recorder(self.net, self.io_binding)
        self.net = recorder
        try:
            symbols = generate(self, *args, **kwargs)
        finally:
            self.net = net
        read = [
            round(min(step) if symbol.rhythm.startswith("note") else step[0], 3)
            for symbol, step in zip(symbols, recorder.steps)
        ]
        if trace["pages"]:
            trace["pages"][-1]["reads"].append(read)
        return symbols

    def traced_process_image(*args, **kwargs):
        trace["pages"].append({"page": len(trace["pages"]) + 1, "reads": [], "systems": [], "flattened": False})
        return process_image(*args, **kwargs)

    def flattened(staffs) -> bool:
        return len({len(system.staffs) for system in staffs}) > 1 and assign_parts(staffs) is None

    def recorded_autocrop(image):
        result, (x, y) = autocrop_with_offset(image)
        crops.append((int(x), int(y), image.shape[1], image.shape[0]))
        return result

    def traced_run_homr(images, config, xml_generator_args) -> None:
        try:
            run_homr(images, config, xml_generator_args)
            return
        except LayoutChanged as change:
            trace["layout_changed"] = str(change)
            trace["pages"] = []
            watch["on"] = False
        out = str(Path(images[0]).with_suffix(".musicxml"))
        try:
            for name in ("instruments", "system_merge"):
                load(name)
            done = load("system_reader").read(images, sys.argv[-1], crops, config, xml_generator_args, trace, out)
        except Exception as exc:
            print(f"Reading system by system failed: {exc!r}", file=sys.stderr)
            raise
        if not done:
            trace["pages"] = []
            run_homr(images, config, xml_generator_args)  # no labels to go by: homr's own reading, flagged

    def traced_parse_staffs(debug, staffs, *args, **kwargs):
        if watch["on"]:
            # What homr takes for the instruments of this page; across pages it goes by their order alone
            layout = max((_layout(system) for system in staffs), key=len)
            watch["layout"] = watch["layout"] or layout
            if flattened(staffs) or layout != watch["layout"]:
                raise LayoutChanged(f"page {len(trace['pages'])}")
        voices = parse_staffs(debug, staffs, *args, **kwargs)
        page = trace["pages"][-1]
        page["systems"] = [len(system.staffs) for system in staffs]
        page["parts"] = len(voices)
        page["flattened"] = flattened(staffs)
        return voices

    ScoreDecoder.generate = traced_generate
    homr_main.parse_staffs = traced_parse_staffs
    homr_main.process_image = traced_process_image
    homr_main.run_homr = traced_run_homr
    pdf_utils.autocrop = recorded_autocrop


try:
    observe()
except Exception as exc:
    trace["error"] = repr(exc)


def report_pages() -> None:
    """Prints "LENTO_PAGE i/n" as homr starts each page, so Lento can show how far a PDF has got."""
    run, process = homr_main.run_homr, homr_main.process_image
    pages = {"done": 0, "total": 0}

    def counted_run(images, *args, **kwargs):
        pages["done"], pages["total"] = 0, len(images)
        return run(images, *args, **kwargs)

    def counted_process(*args, **kwargs):
        pages["done"] += 1
        if pages["total"]:
            print(f"LENTO_PAGE {min(pages['done'], pages['total'])}/{pages['total']}", flush=True)
        return process(*args, **kwargs)

    homr_main.run_homr, homr_main.process_image = counted_run, counted_process


try:
    report_pages()
except Exception as exc:  # homr's internals moved: no page progress, the conversion still runs
    trace["pages_error"] = repr(exc)

try:
    homr_main.main()
finally:
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
