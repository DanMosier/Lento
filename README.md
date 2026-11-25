# Lento

Tools for practicing music, starting with cello. Each tool stands on its own:

| Folder | What it is |
| --- | --- |
| `lento_convertpdf/` | **Lento_ConvertPDF**: Windows desktop app that turns sheet music PDFs into MusicXML (needs a GPU) |
| `lento_core/` | Shared code: reads a MusicXML score into a list of notes |
| `lento_practice/` | Python practice analyzer: compares a recording with the score |
| `lento_library/` | `lento-library` command: files scores into the Drive library and builds the `library.json` the app reads ([docs/library.md](docs/library.md)) |
| `app/` | The Lento app for PC, phone and tablet, one tab per feature: Practice, Library, Tuner ([live](https://danmosier.github.io/Lento/)) |
| `tests/convertpdf/`, `tests/practice/`, `tests/library/` | Tests for each tool (`tests/fixtures/` holds the converter's test scores) |
| `docs/` | Library setup, and accuracy notes for the converter and the practice analyzer |

## Lento_ConvertPDF

A standalone desktop tool to batch-transcribe sheet music PDFs into `.musicxml` files using **[homr](https://github.com/liebharc/homr)**, and preview the converted scores with an integrated **MusicXML Player** powered by the most popular open-source `.vst` / `.vst3` instrument plugins.

## Key Features

1. **Batch Folder Import & Per-File Selection**:
   - Imports all `.pdf` sheet music files from any chosen directory (with optional recursive subfolder scanning).
   - Interactive **`☑` / `☐` checkbox column** (plus *Select All*, *Deselect All*, *Invert Selection*, and *Select Unconverted Only* buttons) to choose which PDFs in the folder to convert.
2. **homr transcription on the GPU**:
   - Runs the real homr from its own environment, one call per PDF, with CUDA required by default.
   - No fallback: if homr cannot read a PDF, the file is marked failed with homr's reason and nothing is written.
3. **Integrated MusicXML Preview Player**:
   - Toggle between **5-Line Grand Staff Notation View** and **Multi-Instrument Color Piano-Roll View**.
   - Full transport controls: **Play ▶**, **Pause ⏸**, **Stop ⏹**, **Interactive Seek Slider**, **Tempo (BPM) override**, **Live Playhead Cursor**, and **Export to WAV**.
4. **Open-Source `.VST` / `.VST3` Instrument Sourcing & Rack**:
   - Automatically detects each instrument part in the converted MusicXML and assigns the top-recommended open-source VST plugin:
     - **Piano**: *Sfizz VST3 + Salamander Grand Piano V3* / *Dexed FM Synth VST3*
     - **Strings**: *Sfizz VST3 + Sonatina Symphonic / Virtual Playing Orchestra Strings* / *String Machine VST3*
     - **Woodwinds**: *Sfizz VST3 + Sonatina Symphonic Woodwinds*
     - **Brass**: *Sfizz VST3 + Virtual Playing Orchestra Brass* / *Odin 2 Hybrid Synth VST3*
     - **Guitar & Harp**: *Sfizz VST3 + FreePats Spanish Classical Guitar & Concert Harp*
     - **Organ & Harpsichord**: *setBfree Tonewheel & Pipe Organ VST3*
     - **Choir / Voice**: *Sfizz VST3 + Sonatina Symphonic Choir (SATB)*
     - **Percussion & Timpani**: *Geonkick Percussion & Timpani Synthesizer VST3*
     - **Universal Synth**: *Surge XT Open-Source Hybrid Synthesizer VST3*

## Lento app (PC, phone and tablet)

`app/` is the app that every feature goes into, each as its own tab and folder. **Practice**: slowed playback with
loops, count-in and metronome, recording, and note-by-note intonation and timing feedback. **Library**: browse and search
your score library in Google Drive and open a score into Practice ([setup](docs/library.md)). **Tuner**: live note and
cents with C G D A reference tones. Everything runs in the browser. Live at https://danmosier.github.io/Lento/.
See [app/README.md](app/README.md).

## Practice feedback

`lento-practice` compares a recording of you playing with its MusicXML score and reports intonation in cents, early or
late notes, and missed or wrong notes, with a colored copy of the score to open in MuseScore. See
[docs/practice.md](docs/practice.md).

```powershell
uv pip install -e ".[practice]"
.venv\Scripts\lento-practice.exe analyze score.musicxml take.wav
```

The repository holds independent features. `lento_core` is code they share; features may import it but never each other.

## Setup

The app expects homr in a sibling folder (`..\homr`). To use another location, set `HOMR_PYTHON` or the path in the GUI.

```powershell
# homr, from the parent folder of this project (needs Git, uv and Poetry)
git clone https://github.com/liebharc/homr
cd homr
$env:POETRY_VIRTUALENVS_IN_PROJECT = 'true'
poetry env use (uv python find 3.12)
poetry install --only main --extras cuda
poetry run homr --gpu force --init      # downloads the models

# this project
cd ..\Lento
uv venv --python 3.12
uv pip install -e ".[dev]"
uv pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage.Streams
```

No CUDA toolkit is needed: the `cuda` extra installs the CUDA and cuDNN libraries.

## Running

```powershell
.venv\Scripts\python.exe -m lento_convertpdf                              # GUI
.venv\Scripts\Lento_ConvertPDF.exe "C:\path\to\pdfs" --output-dir "C:\out"  # command line
.venv\Scripts\python.exe -m lento_convertpdf.build_exe                    # build dist\Lento_ConvertPDF.exe
```

`--gpu force` (default) fails unless CUDA is really in use. `--gpu auto` and `--gpu no` allow the CPU.

### Splitting a PDF of several pieces

A quick tool of its own (no homr or GPU needed). It proposes the pieces beside a preview of the pages; nothing is
written until you press Split, and the original is never changed. Check the proposals: scans are often cut wrongly.

```powershell
.venv\Scripts\python.exe -m lento_convertpdf.split_tool "C:\path\to\album.pdf"  # or no file, to browse for one
.venv\Scripts\python.exe -m lento_convertpdf.split_tool --install                 # right-click > Send to, and a desktop icon to drop PDFs on
```

The pieces go to a new folder beside the PDF, or to `inbox/` for a PDF in a Lento library's `pieces/`.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -m "not homr_gpu"                 # fast
.venv\Scripts\python.exe -m pytest -m homr_gpu -s -W ignore          # real homr, prints accuracy
.venv\Scripts\python.exe tests\convertpdf\compare_musicxml.py reference.mxl output.musicxml
```

Any `name.pdf` with a matching `name.mxl` or `name.musicxml` under `tests/fixtures` becomes an accuracy test.
Export flags, measured accuracy and orchestral limits are described in [docs/convertpdf-accuracy.md](docs/convertpdf-accuracy.md).
Minimum scores go in `tests/fixtures/baselines.json`, for example `{"name": {"pitch_f1": 0.9, "strict_f1": 0.85}}`.
Scores without a baseline are measured and printed, then skipped.

## License

Lento is free software under the [GNU General Public License](LICENSE), version 3 or (at your option) any later version.
It comes with no warranty. homr and MuseScore are separate programs with their own licenses, and so are the sounds
and plugins Lento uses.
