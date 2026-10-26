# OctoPus — Jianpu Editor

**English** | [简体中文](README.zh-CN.md)

**OctoPus: Octave + Jianpu for editing numbered-notation scores.**

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

OctoPus uses RapidOCR with ONNX Runtime to turn score images and PDFs into JPS drafts. Small,
blurred or overlapping marks may be missed or misread, so check each draft against the source before
using it. OctoPus flags low note-number agreement and substantial differences between the draft and
the source. A finding can open the related scan region and, when available, the corresponding note.

## Planned improvements

- Continue improving image and PDF transcription accuracy over the long term.
- Add audio playback, MIDI export.
- Add LilyPond and MusicXML export.
- Import MusicXML and convert it to JPS.
- Add optional LLM support for more accurate image and PDF transcription.

## User manual

Open **Help → User Manual** in the application, or read the
[offline English/Chinese manual](docs/user-manual/index.html). It documents the editing workflow,
supported JPS notation and current limitations. The manual is included with installation and
portable packages. PDF editions are available in
[English](docs/PDF/OctoPus-User-Manual-en.pdf) and
[Chinese](docs/PDF/OctoPus-User-Manual-zh-CN.pdf).

For the source format specification, see [Tomato JPS Spec](https://github.com/yetist/jianpu-spec),
which OctoPus uses for JPS input.

## Fonts

Windows and macOS (upcoming) desktop builds use the preferred fonts installed on the system and compatible
installed substitutes when a preferred family is missing. Use **Help → Fonts** for official
installation instructions or to check again. These desktop builds do not bundle the application's
13 score-font faces. Linux portable and AppImage builds use the verified score-font set shipped
with the application directly.

## Build from source

See [environment instructions](ENVIRONMENT.md) for runtime and build requirements. Production
builds use the pinned Python, Node/npm and Rust versions plus Tauri CLI. Run the setup
script from the repository root:

```sh
python3 scripts/setup.py
```

Linux builds also require GTK/WebKit development packages and Poppler tools; see the
[Linux prerequisites](ENVIRONMENT.md#linux-host-packages). Build on the target operating system.
The Python worker is not cross-compiled.

Build a Linux portable application with:

```sh
python3 scripts/build_portable.py
```

On Windows, build the portable application with:

```powershell
py scripts\build_portable.py
```

The same launcher accepts `--bundles appimage` on Linux or `--bundles nsis` on Windows when a
package is explicitly needed. It locates the repository from its script path, validates build
prerequisites, and can be called from any working directory.

## Run the portable application

On Linux x86_64, run:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `octopus.exe` in `dist/<target>/portable/`. Keep the entire portable directory
together; it contains the application resources, Python worker and score examples. Linux requires
the host GTK/WebKit runtime libraries and Poppler tools. Windows requires WebView2.

## Disclaimer

OctoPus is released under the GNU General Public License, version 3. This software is provided free
of charge. The author makes no warranties and accepts no liability for any direct or indirect loss
arising from its use.

AI tools assist with development and will also be used for ongoing maintenance.
