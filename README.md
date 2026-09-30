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

Production preview and exports use bundled Noto Sans SC, Noto Serif SC and Liberation Sans
fonts, with their OFL licenses. No font installation is needed. Microsoft YaHei/SimHei requests
map to Noto Sans SC, SimSun to Noto Serif SC, and Arial to Liberation Sans with Chinese fallback.
PDF exports embed fonts; JPEG exports contain pixels. External SVG viewers need the named fonts
installed. [Font assets and reproducible preparation](src/octopus/assets/fonts/README.md) describe
checksums, sources and licenses.

Development reference tests use installed Microsoft fonts; their metrics and pixels differ from
the open-font production substitutions. The production repository contains no Microsoft font files.
`samples/jps_files/` supplies bundled examples; `samples/jps_files_pretty/` is additional source material.
