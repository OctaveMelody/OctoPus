# Production running and building environment

**English** | [简体中文](ENVIRONMENT.zh-CN.md)

This repository is self-contained. Its manifests, locks, setup script and builder must not
read development tests, audit packages, instructions or environments from OctoPus-dev.

## Repository layout

- `pyproject.toml`: Python package metadata, dependency declarations and optional extras.
- `uv.lock`: exact dependency versions; use `uv sync --locked` for reproducible installation.
- `.python-version`, `.node-version`, `rust-toolchain.toml`: toolchain versions.
- `scripts/`: executable environment setup helpers.
- `.venv/`, `ui/web/node_modules/`: ignored, repository-local dependency installations.

`ENVIRONMENT.md` contains human-readable instructions. This uv project does not require a
separately maintained `requirements.txt`: declarations and locks are its source of truth.
For pip tooling, export one when needed (from this repository root):

```sh
uv export --locked --extra transcription --no-emit-project --output-file /tmp/octopus-requirements.txt
```

The export lists third-party dependencies; install this repository itself separately with
`python -m pip install --no-deps -e .` in your chosen virtual environment. Regenerate the export
after lock changes. See [uv project structure](https://docs.astral.sh/uv/guides/projects/).

Production setup: `python3 scripts/setup.py`; release packaging: `python3 build.py`.

## Locked dependencies

- Python 3.12 for native worker builds (`.python-version`); Python source supports 3.11+.
- Python runtime/export dependencies: `pyproject.toml` and `uv.lock`.
- OCR: `transcription` extra, RapidOCR 1.4.4 and its locked dependencies.
- Worker freezing: `desktop-build` extra, PyInstaller 6.22.3.
- Node.js 22.23.3 (`.node-version`), npm 10.9.9; frontend `ui/web/package-lock.json`.
- Rust 1.98.1 (`rust-toolchain.toml`), Cargo lock `ui/Cargo.lock`.
- Tauri CLI 2.11.5: `cargo install tauri-cli --version 2.11.5 --locked`.
- uv 0.12.21 was used to prepare/validate these locks. uv is a host setup tool.

Host tools may be installed globally or in a workspace tool directory on PATH. Python `.venv`,
frontend `ui/web/node_modules`, and all `build/`/`dist/` outputs belong to this repository and
are ignored. A fresh clone can use ordinary installed host tools without the development repo.

## This workspace's shared tools (Linux)

From this production directory, activate the already installed workspace tools directly;
no development script or environment is needed:

```sh
export PATH="$PWD/../.tools/bin:$PWD/../.tools/node-v22.23.3-linux-x64/bin:$PWD/../.tools/cargo/bin:$PATH"
export RUSTUP_HOME="$PWD/../.tools/rustup"
export CARGO_HOME="$PWD/../.tools/cargo"
export UV_CACHE_DIR="$PWD/../.tools/uv-cache"
export npm_config_cache="$PWD/../.tools/npm-cache"
```

For a separate clone using normally installed host tools, omit this activation block.

## Linux host packages

Ubuntu/Debian native builds require:

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev poppler-utils
```

An installed Debian application uses the package-manager-resolved GTK/WebKit/runtime libraries
and `poppler-utils`; its bundled Python worker needs no separate Python installation. Retain
its neighboring engine/examples/docs resources. Bundled fonts cover the supported rendering roles;
Microsoft YaHei/SimHei/SimSun/Arial are needed for authoritative corpus comparisons, which live
in development. Font replacement changes rendering and is not proof of reference parity.

## Setup and run from source

From this directory with uv/Node/Rust available:

```sh
python3 scripts/setup.py
uv run --locked --extra transcription octopus render samples/jps_files/Symbols.jps --out-dir build/symbols
uv run --locked --extra transcription python -m ui.engine
```

The worker reads JSON-lines on stdin and writes responses on stdout. For Python-only runtime
setup use `python3 scripts/setup.py --runtime-only`. The optional `pixel` extra supports
browser-DOM SVG export and requires `uv run --extra pixel playwright install chromium`; it is
not bundled into the offline worker. Pytest, Ruff, mypy and development evidence are excluded
from this repository's Python dependency extras.

## Build packages

An unspecified build request means production only, including the portable executable.
Development executables are built only on an explicit request, using the support repository's
build instructions.

Install the pinned Tauri CLI, then run `python3 build.py --bundles deb` on Linux. On native
Windows use `python build.py --bundles nsis` or `--bundles msi`, with Microsoft C++ Build Tools
and WebView2 installed. Rust/PyInstaller target architecture must match the native Python host;
worker cross-compilation is unsupported. macOS packaging is deferred.

`build.py` builds the frontend/worker/native app under `build/` and copies packages to
`dist/<target-triple>/`. The worker builder preserves its previous output until a new bundle
has passed glyph checks and handshake/render smoke tests. Each repository has its own locks;
update them intentionally with `uv lock`/npm/Cargo and validate the resulting change.

## Release fonts

Pinned font assets and their OFL, IPA and Xiaomi MiSans licenses are in src/octopus/assets/fonts/. Packaging verifies their
hashes and includes them in the worker, preview and native exporter. Builds need no font download
or system font installation. See [font asset guide](src/octopus/assets/fonts/README.md).
The source engine defaults to reference fonts; use `OCTOPUS_FONT_PROFILE=release` for release-policy
checks. Packaged workers/native exports prefer the configured installed OS families independently
for each role, then use bundled substitutions when a family is missing. This also applies to
production portable builds. Reference font files stay outside Git. See the [font tables](README.md#fonts).

## Portable production testing

Every native `python build.py` build also publishes an untracked portable tree under
`dist/<target-triple>/portable/`, alongside installation packages. Linux builds include a Debian
bundle to obtain the matching resource layout, even when another bundle type is requested.
The builder verifies worker/font/glyph assets, a Chinese render, example bytes and the packaged user manual before replacing
the portable output. `portable.previous/` retains the last successful portable build.

On Linux, run from any working directory:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `dist/<target-triple>/portable/octopus.exe`. Keep the complete portable
folder together. Linux still requires the host GTK/WebKit libraries and Poppler tools; Windows
requires WebView2. This is an application-local production testing tree, not a static OS runtime.
Both build/ and dist/ are ignored by Git. Fonts are bundled and no font installation is needed.
