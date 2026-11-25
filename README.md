# PDF to MusicXML Batch Converter & Open-Source VST Player

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

## Practice web app

`web/` is the practice app for PC, phone and tablet: slowed playback with loops, count-in and metronome,
recording, note-by-note intonation and timing feedback, and a tuner, all in the browser. Live at
https://danmosier.github.io/Lento/. See [web/README.md](web/README.md).

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
cd ..\PDF_to_MusicXML_project
uv venv --python 3.12
uv pip install -e ".[dev]"
uv pip install winrt-runtime winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr winrt-Windows.Storage.Streams
```

No CUDA toolkit is needed: the `cuda` extra installs the CUDA and cuDNN libraries.

## Running

```powershell
.venv\Scripts\python.exe convert_pdfs.py                                   # GUI
.venv\Scripts\pdf-to-musicxml.exe "C:\path\to\pdfs" --output-dir "C:\out"  # command line
```

`--gpu force` (default) fails unless CUDA is really in use. `--gpu auto` and `--gpu no` allow the CPU.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -m "not homr_gpu"                 # fast
.venv\Scripts\python.exe -m pytest -m homr_gpu -s -W ignore          # real homr, prints accuracy
.venv\Scripts\python.exe tests\compare_musicxml.py reference.mxl output.musicxml
```

Any `name.pdf` with a matching `name.mxl` or `name.musicxml` under `tests/fixtures` becomes an accuracy test.
Export flags, measured accuracy and orchestral limits are described in [docs/accuracy.md](docs/accuracy.md).
Minimum scores go in `tests/fixtures/baselines.json`, for example `{"name": {"pitch_f1": 0.9, "strict_f1": 0.85}}`.
Scores without a baseline are measured and printed, then skipped.
