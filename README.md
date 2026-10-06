# OctoPus — A Desktop Editor for Jianpu

**English** | [简体中文](README.zh-CN.md)

OctoPus is a desktop editor for Jianpu (numbered musical notation). It offers a live SVG preview,
turns Jianpu images and PDFs into editable JPS drafts for review, and exports scores to SVG, PDF,
PNG and JPEG.

Whether you are preparing a score for practice or sharing it with a group, you can edit and check
the music in OctoPus before exporting it.

## Project background

OctoPus began as an independent effort to reproduce the score rendering of the
[Tomato JianPu Editor](http://zhipu.lezhi99.com), using its visible output as a reference. Tomato's
script-based JPS format makes Jianpu scores convenient to prepare. Because the original editor is
closed source, OctoPus cannot extend its existing code. It provides its own parser and renderer
instead, and adds automatic note grouping for meters such as 6/8, 9/8 and 12/8,
along with image and PDF transcription into JPS drafts that can be edited and rendered again.

This production repository contains the application source, packaging configuration, offline
Python worker and JPS examples. It builds independently of the development repository,
OctoPus-dev, which contains tests, audits, reference output and development tools.

## Features

- Write and edit Jianpu scores in JPS (Jianpu Script), with a live SVG preview.
- Group short notes automatically by dotted-quarter beats in 6/8, 9/8 and 12/8;
  use JPS `~` and `^` for custom joins and splits.
- Import JPG, PNG and PDF score images from the file picker or by dropping a file into the
  Original Image/PDF panel, then turn them into JPS drafts for review.
- Export scores as SVG, PDF, PNG or JPEG. Raster exports support 96 and 300 DPI.
- Review clickable source regions and warnings during transcription, or cancel a running job.
- Reopen recent scores, use keyboard shortcuts and batch-export folders with the Python CLI.

## Transcription drafts

Transcription can recognize stacked time signatures and slightly skewed note rows. It can also
capture visible dynamics and expression marks (`p`, `pp`, `ppp`, `mp`, `mf`, `f`, `ff`, `fff`,
`rit` and `dim`) as JPS decorations. Fermatas use `&yc`; words such as `cres`, `cresc`,
`crescendo` and `decrescendo` are preserved as quoted JPS annotations. Graphic crescendo and
diminuendo hairpins can be attached to notes or sustain dashes. Image and PDF recognition is
powered by RapidOCR + ONNX.

Compact accompaniment written above a braced multi-voice system can be recognized as a
`{bz ...}` overlay, even when its printed digits are close in size to the melody. Faint duration
strokes are recognized only when nearby dark marks support them. In the rendered score, BZ
overlays stay aligned to the melody's beat grid and the other voices.

Transcriptions are drafts and need to be checked against the source. Review the lyrics, rhythm,
octave marks, voice grouping, and which note or sustain dash each decoration belongs to. Small,
blurred or crowded marks can still be missed or misread.

The recognizer conservatively filters repeated headers and footers, along with page numbers that
fall outside the score area. When note-number agreement is low, or the rendered draft differs
substantially from the source, OctoPus adds a review finding. Select a finding to inspect the
source region and, when possible, the matching note. These checks help focus review; they do not
guarantee a complete transcription. Editing the source clears outdated highlights.

## Planned improvements

- Improve image and PDF transcription accuracy.
- Audio preview, MIDI export, and LilyPond/MusicXML export.
- Import MusicXML and convert it to JPS.
- Import and recognize staff-notation sheet music as JPS.

These features are planned. Image and PDF transcription currently produces provisional Jianpu
drafts for review.

## User Manual

Open **Help → User Manual** in the app, or read the
[offline English/Chinese manual](docs/user-manual/index.html). It covers the main workflows,
supported JPS notation, current limitations and planned improvements. The manual has language
tabs and is included with installation and portable packages. Matching
[English PDF](docs/PDF/OctoPus-User-Manual-en.pdf) and
[Chinese PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf) versions are available.

## Setup

[Environment instructions](ENVIRONMENT.md) define the independent runtime and build environment.
The tools below are needed only if you plan to run or package OctoPus from source.
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

Every build creates installation packages and a verified portable application in a
platform-specific subfolder of `dist/`. Temporary native, frontend and worker build files stay
under `build/`. Both directories are ignored by Git. Linux builds include the Debian bundle needed
for the portable resource layout, even when another package type is requested.

## Run the portable application

On Linux x86_64:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `octopus.exe` from the `portable/` folder inside the generated `dist/` directory.
Keep the entire portable folder together: it includes the engine and 65 score examples.
Linux needs the host GTK/WebKit runtime libraries and Poppler tools; Windows needs WebView2.
The portable build contains the Python worker and does not need a separate Python installation.
The preceding successful portable build is retained under `portable.previous/`.

## Fonts

OctoPus uses installed system fonts when available and bundled alternatives when they are not.
Preview and exports use the same font choices. Keep the `fonts` directory and its license notices
with the portable application.

| Setting | Windows / Linux preference | macOS preference | Bundled alternative | Missing-glyph backup |
| --- | --- | --- | --- | --- |
| HeiTi-1 (default) | Microsoft YaHei | PingFang SC | MiSans Regular | Noto Sans SC → Noto Serif SC |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei | Noto Sans SC → Noto Serif SC |
| SongTi | SimSun | Songti SC | SimZhiSong | Noto Sans SC → Noto Serif SC |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai Regular | Noto Sans SC → Noto Serif SC |
| FangSong | FangSong | STFangsong | Zhuque Fangsong Regular | Noto Sans SC → Noto Serif SC |

Open **Preferences** to change the interface language and choose a system or bundled font for each
role. If a preferred system font is unavailable, the option is disabled and the bundled alternative
is used. These settings are saved locally and apply to preview and SVG, PDF, PNG and JPEG exports;
they do not change the score file.

PDF exports embed fonts. JPEG exports contain pixels, and external SVG viewers need access to the
fonts named in the score. See the [font guide](src/octopus/assets/fonts/README.md) for details.

<details>
<summary>Font fallback and export details</summary>

The missing-glyph backup column lists fonts used when the selected family does not contain a
character; it is not another selectable role. The renderer tries Noto Sans SC and then Noto Serif
SC. If neither contains a character, complete coverage cannot be guaranteed. Noto Sans and Noto
Serif include Regular and Bold faces. Latin **Arial** requests use bundled **Liberation Sans** in
Regular, Italic, Bold and Bold Italic.

Note styles are **Regular, Italic and Bold**. Saved `HeiTi` remains an alias for HeiTi-2, and
existing settings remain compatible. Development reference tests use installed Microsoft fonts.
Production also prefers configured system fonts; fallback fonts can differ in metrics and pixels.
Microsoft font files are not bundled or redistributed.

The Python ReportLab PDF path uses a bundled fallback if an installed font has unsupported CFF
outlines. MiSans is credited in the application and shipped with Xiaomi's full license; Zhuque
v0.212 is an upstream technical preview. All bundled font notices are retained.

</details>

## Repository contents

- `src/octopus/` and `ui/`: application source and the offline Python worker.
- `docs/user-manual/index.html`: the packaged, tab-switchable English/Chinese user manual.
- `docs/THIRD_PARTY_NOTICES.md`: OCR model, RapidOCR and ONNX Runtime license notices.
- `samples/jps_files/`: 65 bundled score examples.
- `OctoPus-dev` (separate repository): tests, audits, reference output and development tools.

The project is licensed under GPL-3.0-or-later; the full text is in [LICENSE](LICENSE) and
travels with Python distributions and native resources.
