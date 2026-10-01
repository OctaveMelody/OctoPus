# OctoPus by OctaveMelody

**English** | [简体中文](README.zh-CN.md)

OctoPus is a desktop Jianpu score editor with live SVG preview, image/PDF transcription into
reviewable drafts, and SVG, PDF and JPEG export. LilyPond conversion is not currently available.

This production repository contains the application source, packaging configuration, offline
Python worker and JPS examples. It builds independently of the development repository,
OctoPus-dev, which holds tests, audits, reference output and development tools.

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

## Fonts and examples

Settings offer HeiTi-1, HeiTi-2, SongTi, KaiTi and FangSong. Windows prefers
Microsoft YaHei, SimHei, SimSun, KaiTi and FangSong; macOS prefers PingFang SC,
Heiti SC, Songti SC, Kaiti SC and STFangsong. Each missing family falls back to
MiSans Regular, Neo XiHei, SimZhiSong, WenKai Regular or Zhuque Fangsong, respectively.
Linux production also prefers those Microsoft families when installed, using exact
fontconfig matches; otherwise it uses the bundled fallbacks. This applies to portable
builds as well. Saved HeiTi still means HeiTi-2.
Noto provides missing glyph coverage and Liberation Sans covers Latin Arial requests.
PDF embeds fonts; JPEG stores pixels. External SVG viewers need the named fonts.
[Font guide](src/octopus/assets/fonts/README.md) explains licenses, macOS collection
selection, Python PDF's CFF fallback and original IPA font restoration. MiSans is credited
in the application and shipped with Xiaomi's full license; Zhuque v0.212 is a technical preview.

Note styles remain Regular, Italic and Bold. Untouched legacy settings stay compatible.

Development reference tests use installed Microsoft fonts. Production prefers the configured
system fonts too; bundled substitutions can differ in metrics and pixels when a match is missing. The production repository contains no Microsoft font files.
`samples/jps_files/` supplies bundled examples; `samples/jps_files_pretty/` is additional source material.
