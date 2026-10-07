# OctoPus — Jianpu Editor

**English** | [简体中文](README.zh-CN.md)

OctoPus is a desktop editor for Jianpu (numbered musical notation). Scores are authored in JPS
(Jianpu Script) and rendered as a live SVG preview. The application can also transcribe Jianpu
images and PDF files into editable JPS drafts and export scores to SVG, PDF, PNG or JPEG.

The About dialog displays **v1.0-Beta** and the tagline “OctoPus: Oct(Octave) + Pus (JianPu) = The ultimate numbered notation editor.”

## Project background

OctoPus adopts the JPS format from [Tomato JianPu](http://zhipu.lezhi99.com) and aims to match
its rendered output through an independent parser and score renderer. It adds
automatic note grouping for 6/8, 9/8 and 12/8 meters, as well as image and PDF transcription.

This production repository contains the application, packaging configuration, offline Python
worker and JPS examples. Tests, audits, reference output and development tools are maintained in
the separate OctoPus-dev repository.

## Features

- Edit JPS source with a live score preview.
- Group short notes automatically by dotted-quarter beats in 6/8, 9/8 and 12/8; use JPS `~` and
  `^` for custom joins and splits.
- Transcribe JPG, PNG and PDF score images into JPS drafts. Source-region findings support review,
  and a running transcription can be cancelled.
- Export scores as SVG, PDF, PNG or JPEG. Raster exports support 96 and 300 DPI.
- Choose Normal or Transcription layouts and maximize, restore or close individual panels;
  closing a panel preserves its content.
- Use keyboard shortcuts and batch-export folders with the Python CLI.

## Transcription

Image and PDF recognition uses RapidOCR with ONNX Runtime. Results are provisional drafts and
should be compared with the source before use. Small, blurred or overlapping marks may be missed or
misread. OctoPus reports review findings when note-number agreement is low or the rendered draft
differs substantially from the source; a finding can open the related scan region and, when
available, the corresponding note.

## Planned improvements

- Improve image and PDF transcription accuracy.
- Add audio playback, MIDI export, and LilyPond and MusicXML export.
- Import MusicXML and convert it to JPS.
- Recognize staff-notation images and PDFs as JPS.

## User manual

Open **Help → User Manual** in the application, or read the
[offline English/Chinese manual](docs/user-manual/index.html). It documents the editing workflow,
supported JPS notation and current limitations. The manual is included with installation and
portable packages. PDF editions are available in
[English](docs/PDF/OctoPus-User-Manual-en.pdf) and
[Chinese](docs/PDF/OctoPus-User-Manual-zh-CN.pdf).

## Build from source

See [environment instructions](ENVIRONMENT.md) for runtime and build requirements. Source builds
require Python 3.11+, uv, Node.js 20.19+ with npm, Rust 1.92+ and Tauri CLI 2.11.5. Run the setup
script from the repository root:

```sh
python3 scripts/setup.py
```

Linux builds also require GTK/WebKit development packages and Poppler tools; see the
[Linux prerequisites](ENVIRONMENT.md#linux-host-packages). Build on the target operating system.
The Python worker is not cross-compiled.

Build a Linux package and portable application with:

```sh
python3 build.py --bundles deb
```

On Windows, use a native Windows build environment:

```powershell
python build.py --bundles nsis
# Or: python build.py --bundles msi
```

Packages and the portable application are written to a platform-specific subdirectory of `dist/`.
Temporary build files are written to `build/`.

## Run the portable application

On Linux x86_64, run:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `octopus.exe` in `dist/<target>/portable/`. Keep the entire portable directory
together; it contains the application resources, Python worker and score examples. Linux requires
the host GTK/WebKit runtime libraries and Poppler tools. Windows requires WebView2.

## Fonts

Font roles use configured system fonts when available and bundled, licensed alternatives otherwise.
Font preferences are set in **Preferences**. PDF exports embed fonts; external SVG viewers require
access to the fonts referenced by the score. See the [font guide](src/octopus/assets/fonts/README.md)
for font mappings, fallback behavior and license details.

## Repository contents

- `src/octopus/` and `ui/`: application source and offline Python worker.
- `docs/user-manual/index.html`: packaged English/Chinese user manual.
- `docs/THIRD_PARTY_NOTICES.md`: OCR model, RapidOCR and ONNX Runtime license notices.
- `samples/jps_files/`: 65 bundled score examples.
- OctoPus-dev: tests, audits, reference output and development tools.

OctoPus is licensed under the GNU General Public License, version 3 or later
(GPL-3.0-or-later), without any warranty. The full license is in [LICENSE](LICENSE) and is
included with Python distributions and native application resources.
