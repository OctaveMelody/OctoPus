# OctoPus — Jianpu Editor

**English** | [简体中文](README.zh-CN.md)

**OctoPus: Oct (Octave) + Pus (Jianpu) = the ultimate numbered-notation editor.**

OctoPus is a desktop editor for Jianpu (numbered musical notation). Scores are written in JPS
(Jianpu Script) and rendered as a live SVG preview. The application can also transcribe images
and PDF files of Jianpu scores into editable JPS drafts and export scores to SVG, PDF, PNG or JPEG.

## Project background

OctoPus adopts the JPS format from [Tomato JianPu](http://zhipu.lezhi99.com) and aims to match
Tomato JianPu's rendered output with its own parser and score renderer. It also adds automatic note
grouping in 6/8, 9/8 and 12/8 meters, along with image and PDF transcription.

## Features

- Edit JPS source with a live score preview.
- Transcribe score images (JPG or PNG) and PDF files into editable JPS drafts.
- Export scores as SVG, PDF, PNG or JPEG. Raster exports support 96 and 300 DPI.
- The app offers Normal and Transcription layouts.

## Transcription

Image and PDF recognition uses RapidOCR with ONNX Runtime. Recognition produces provisional drafts
that should be checked against the source before use. Small, blurred or overlapping marks may be
missed or misread. OctoPus reports review findings when note-number agreement is low or the rendered
draft differs substantially from the source. A finding can open the related scan region and, when
available, the corresponding note.

## Planned improvements

- Continue improving image and PDF transcription accuracy over the long term.
- Add audio playback, MIDI export, and LilyPond and MusicXML export.
- Import MusicXML and convert it to JPS.

## User manual

Open **Help → User Manual** in the application, or read the
[offline English/Chinese manual](docs/user-manual/index.html). It documents the editing workflow,
supported JPS notation and current limitations. The manual is included with installation and
portable packages. PDF editions are available in
[English](docs/PDF/OctoPus-User-Manual-en.pdf) and
[Chinese](docs/PDF/OctoPus-User-Manual-zh-CN.pdf).
The manual's PDF links open a save dialog in the desktop app and download the PDF in a browser.

For the source format specification, see [Tomato JPS Spec](https://github.com/yetist/jianpu-spec),
which OctoPus uses for JPS input.

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

For each font role, OctoPus uses the configured system font when available and otherwise falls back
to a bundled font with a compatible license. Configure font preferences in **Preferences**. PDF
exports embed fonts; external SVG viewers require access to the fonts referenced by the score. See
the [font guide](src/octopus/assets/fonts/README.md) for font mappings, fallback behavior and
license details.

## Disclaimer

OctoPus is released under the GNU General Public License, version 3. This software is provided free
of charge. The author makes no warranties and accepts no liability for any direct or indirect loss
arising from its use.

AI-assisted coding is used to develop this software, and the same approach will be used for ongoing
maintenance.
