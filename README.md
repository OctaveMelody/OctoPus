# OctoPus -- Oct (Octave) + Pus (JianPu): The Ultimate Numbered Notation Editor

**English** | [简体中文](README.zh-CN.md)

OctoPus is a desktop Jianpu score editor with live SVG preview, image/PDF transcription into
reviewable drafts, and SVG, PDF and JPEG export.

This production repository contains the application source, packaging configuration, offline
Python worker and JPS examples. It builds independently of the development repository,
OctoPus-dev, which holds tests, audits, reference output and development tools.

## Features

- Edit Jianpu scores in JPS (Jianpu Script), with live SVG preview.
- Import JPG/PNG/PDF references through the file picker or by dropping a file into the
  Original Image/PDF panel; transcribe them into JPS drafts for review.
- Export rendered scores as SVG, JPEG or PDF.

## Planned improvements

- Improve transcription accuracy.
- Export LilyPond source and MusicXML.
- Import MusicXML and convert it to JPS.
- Import and recognize staff-notation sheet music as JPS.

These items are planned; image/PDF transcription currently produces provisional Jianpu drafts.

## User Manual

Open **Help → User Manual** in the app, or read the [offline English/Chinese manual](docs/user-manual/index.html).
The manual covers UI workflows, supported JPS notation, limitations and planned improvements.
It uses language tabs and is included with installation and portable packages. Matching
[English PDF](docs/PDF/OctoPus-User-Manual-en.pdf) and
[Chinese PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf) versions are available.

## Setup

[Environment instructions](ENVIRONMENT.md) define the independent runtime and build environment.
Install Python 3.11+, uv, Node.js 20.19+ with npm, Rust 1.92+ and Tauri CLI 2.11.5, then run:

```sh
python3 scripts/setup.py
```

Linux native builds also need GTK/WebKit development packages and Poppler tools; see
[the Linux prerequisites](ENVIRONMENT.md#linux-host-packages). The build uses uv to provision
Python 3.12 and locked worker-build dependencies. Build on the target operating system;
the Python worker is not cross-compiled.

## Build

From this repository root, build on Linux:

```sh
python3 build.py --bundles deb
```

On Windows, use a native Windows build environment:

```powershell
python build.py --bundles nsis
# Or: python build.py --bundles msi
```

Every build creates installation packages and a verified portable application under
`dist/<Rust target triple>/`. Temporary native/frontend/worker build files stay under `build/`.
Both directories are ignored by Git. Linux builds include the Debian bundle needed for the
portable resource layout, even when another package type is requested.

## Run the portable application

On Linux x86_64:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `dist/<Rust target triple>/portable/octopus.exe`.
Keep the entire portable folder together: it includes the engine and 65 score examples.
Linux needs the host GTK/WebKit runtime libraries and Poppler tools; Windows needs WebView2.
The portable build contains the Python worker and does not need a separate Python installation.
The preceding successful portable build is retained under `portable.previous/`.

## Fonts

Release fallback and backup fonts are external files, shared by preview and exports.
Linux: `usr/lib/OctoPus/fonts`; Windows: `lib/OctoPus/fonts` beside the executable.
The macOS resource mapping is `Contents/Resources/lib/OctoPus/fonts` (native builds pending).
Keep these files and their license notices with the program. OS font preference is unchanged.

Each role prefers its installed OS font. If that family is unavailable, OctoPus uses the
bundled fallback, including in production portable builds. Linux checks the Windows-preferred
families through exact fontconfig matches; without a match or fontconfig it uses the fallback.

| Setting | Windows / Linux OS preference | macOS OS preference | Bundled fallback | Bundled glyph backup |
| --- | --- | --- | --- | --- |
| HeiTi-1 (default) | Microsoft YaHei | PingFang SC | MiSans Regular | Noto Sans SC → Noto Serif SC |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei | Noto Sans SC → Noto Serif SC |
| SongTi | SimSun | Songti SC | SimZhiSong | Noto Sans SC → Noto Serif SC |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai Regular | Noto Sans SC → Noto Serif SC |
| FangSong | FangSong | STFangsong | Zhuque Fangsong Regular | Noto Sans SC → Noto Serif SC |

The backup column describes missing-glyph coverage, not another selectable role. When a
bundled family lacks characters in a text element, the renderer chooses Noto Sans SC if it
covers that text, then Noto Serif SC if it does. If neither covers it, Noto Sans SC is the final
request; this cannot guarantee every character is available. Noto Sans/Serif include Regular
and Bold faces. Latin **Arial** requests use bundled **Liberation Sans** in Regular, Italic,
Bold and Bold Italic.

Note styles are **Regular, Italic and Bold**. Saved `HeiTi` remains an alias for HeiTi-2;
untouched legacy settings remain compatible. Development reference tests use installed
Microsoft fonts. Production also prefers its configured OS fonts; fallback fonts can differ
in metrics and pixels. Microsoft font files are not bundled, installed or redistributed.

Open **Preferences** to change the interface language and select OS or bundled fonts for each
role. Missing OS fonts are disabled and use the bundled fallback. Choices are stored locally
and apply to preview and SVG/PDF/JPG export without changing the saved score.

PDF exports embed fonts; JPEG stores pixels. External SVG viewers need the named fonts.
The Python ReportLab PDF path uses the bundled role fallback when an installed font has
unsupported CFF outlines. See the [font guide](src/octopus/assets/fonts/README.md) for details
and license notices. MiSans is credited in the application and shipped with Xiaomi's full
license; Zhuque v0.212 is an upstream technical preview. All bundled font notices are retained.

## Repository contents

- `src/octopus/` and `ui/`: application source and the offline Python worker.
- `docs/user-manual/index.html`: the packaged, tab-switchable English/Chinese user manual.
- `samples/jps_files/`: 65 bundled score examples.
- `samples/jps_files_pretty/`: additional source material.
- `OctoPus-dev` (separate repository): tests, audits, reference output and development tools.
