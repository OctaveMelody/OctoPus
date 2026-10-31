# Production running and building environment

**English** | [简体中文](ENVIRONMENT.zh-CN.md)

This repository is self-contained. Its manifests, locks, setup script and builder must not
read development tests, audit packages, instructions or environments from OctoPus-dev.

## Repository layout

- `pyproject.toml`: Python package metadata, dependency declarations and optional extras.
- `uv.lock`: exact dependency versions; use `uv sync --locked` for reproducible installation.
- `.python-version`, `.node-version`, `.npm-version`, `rust-toolchain.toml`: toolchain versions.
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

Production setup: `python3 scripts/setup.py` on Linux or `py scripts/setup.py` on Windows. After
setup, the pinned OCR models are prepared and checksum-verified in the ignored
`build/ocr-model-cache` directory; a valid existing cache is reused offline. Setup needs access to
the official model host when one or more files are missing. Set `OCTOPUS_OCR_MODEL_DIR` to prepare
the cache elsewhere. Then run `python3 scripts/build_portable.py` on Linux or
`py scripts/build_portable.py` on Windows. The launcher locates the repository and its production
virtual environment, so it also works when called by full path from another working directory.
This keeps source-side package checks aligned with the dependencies collected into the frozen
worker.

## Locked dependencies

- Python 3.12 for native worker builds (`.python-version`); Python source supports 3.11+.
- Python runtime/export dependencies: `pyproject.toml` and `uv.lock`.
- OCR: the `transcription` extra pins `rapidocr==3.10.0`, `onnxruntime==1.30.0` and
  `opencv-python-headless==5.0.0.93`. Headless OpenCV still provides `cv2`; it omits GUI
  support. Do not install regular or contrib OpenCV alongside it. The sole Default profile
  uses PP-OCRv6 Small detection/recognition and the shared PP-OCRv4 Mobile orientation
  classifier. These multilingual weights cover English and Chinese without separate English
  models. CPU execution retains 2 intra-op / 1 inter-op threads. The three verified models
  are bundled offline; [model documentation](docs/OCR_MODELS.md) links checksums, attribution
  and preparation workflow.
- Worker freezing: `desktop-build` extra, PyInstaller 6.22.3.
- Node.js 22.23.3 (`.node-version`), npm 10.9.9 (`.npm-version`); frontend
  `ui/web/package-lock.json`.
- Rust 1.98.1 (`rust-toolchain.toml`), Cargo lock `ui/Cargo.lock`.
- Tauri CLI 2.11.5: `cargo install tauri-cli --version 2.11.5 --locked`.
- uv 0.12.21 was used to prepare/validate these locks. uv is a host setup tool.

Host tools may be installed globally or in a workspace tool directory on PATH. The builder finds
tools by command name and does not assume a machine-specific installation directory. On Windows it
uses the standard Visual Studio locator to load the x64 compiler environment when needed; on Linux
it checks the required desktop development libraries before compiling. Python `.venv`,
frontend `ui/web/node_modules`, and all `build/`/`dist/` outputs belong to this repository and
are ignored. A fresh clone can use ordinary installed host tools without the development repo.

## Linux host packages

Ubuntu/Debian native builds require:

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev poppler-utils
```

An installed Debian application uses the package-manager-resolved GTK/WebKit/runtime libraries
and `poppler-utils`; its bundled Python worker needs no separate Python installation. Retain
its neighboring engine/examples/docs resources. Linux production packages include the verified
score-font set. Windows/macOS desktop builds use installed OS fonts and compatible installed
substitutes without the 13 application score-font faces. The offline manual carries small Noto
Sans SC subsets separately. Microsoft YaHei/SimHei/SimSun/Arial are needed for authoritative
corpus comparisons, which live in development. Font replacement changes rendering and is not
proof of reference parity.

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

## Batch export and desktop capabilities

The production Python CLI provides safe folder export (existing files are retained):

```sh
uv run --locked octopus batch-export scores --out combined.pdf
uv run --locked octopus batch-export scores --out-dir exported --format pdf --recursive
uv run --locked octopus batch-export scores --out-dir images --format png --dpi 300
```

`ui.engine` exposes diagnostics-only `parse` and PNG capability in its desktop handshake.
Transcription emits correlated bounded progress frames followed by one final result; native
cancellation stops the dedicated process tree and invalidates the pending draft. The preview
worker is independent. Legacy HTTP/file/recovery protocol and audit entry points live only in
OctoPus-dev and are excluded from production Python/native distributions.

Desktop protocol 2.0.0 accepts only the managed reference path on transcription requests and
does not include an OCR mode field in requests or results. Older protocol versions and stale
mode fields are rejected. New and Append use the sole Default profile for every PDF page and
crop. The profile does not become part of JPS; all drafts still require review against the
source.

`VITE_UPDATE_CHECK_ENABLED=false` hides Help → Check for Update when building the frontend.
Default builds keep it visible; this flag does not disable installed update checking code or
change the version. Use it only when a distribution intentionally omits that menu item.

## Build packages

During development, build only the portable by default. Do not build installers or other
variants unless the user explicitly asks for them. Run `python3 scripts/build_portable.py` on
Linux/macOS or `py scripts/build_portable.py` on Windows. Use `--bundles appimage` on Linux,
`--bundles nsis` on Windows, or `--bundles dmg` on macOS only when a package is explicitly needed.
To build only a Windows installer while retaining portable-tree smoke checks, add
`--no-portable-zip`. GitHub Actions provides independent manual workflows for macOS DMG, Windows
installer, Windows portable ZIP, and Linux AppImage builds, plus an all-in-one workflow that also
runs for published releases. Every manual workflow accepts an optional `source_ref` branch, tag, or
commit. Each run resolves one immutable source commit and passes it to every selected package job.
Published-release events build the event's tag; manual runs with an empty `source_ref` fall back to
the nearest published release tag in the selected commit's history. The optional `release_tag`
attaches packages only when its destination tag peels to the resolved source commit; mismatches are
rejected before upload. macOS builds target Apple Silicon and declare macOS 11.0 as the minimum
version.
Rust formatting is checked on pushes and pull requests, and again before package setup. Before
upload, Windows installer/portable and Linux AppImage jobs extract or install the built artifact
and exercise its packaged worker with a handshake, score render, and OCR request. These checks do
not launch or verify the desktop GUI.
Omitting `--bundles` selects portable-only mode. The launcher uses the pinned repository
environment; the builder checks Python, Node/npm, Rust/Cargo, Tauri CLI, and native system
prerequisites before beginning the build. It builds the frontend and worker first, then invokes
Tauri once with its nested prebuild hook disabled. Rust/PyInstaller target architecture must
match the native Python host; worker cross-compilation is unsupported. macOS packaging is
performed on a native Apple Silicon host. The published package workflow runs the macOS build on
GitHub's `macos-26` runner and validates the mounted DMG's app bundle and resources before upload.
Packages are currently unsigned and not notarized.

For a Linux x86_64 AppImage, use
`python3 scripts/build_portable.py --bundles appimage`. If linuxdeploy completes deployment but
AppImage finalization cannot download its runtime, the builder uses the cached AppImage runtime
and appimagetool. Deployment diagnostics are saved in `build/cargo/appimage-build.log`; other
deployment failures stop the build. To retry only final
packaging after such a failure, run
`python3 scripts/build_portable.py --package-appimage-only` (include the same `--target` if the
original build specified one). The resume command requires a verified complete deployment matching
the current production commit; older unverified staging records require a full build. Use
`--incremental` on local rebuilds to
let Cargo reuse release compilation data; it uses more disk. The frozen worker's PyInstaller cache
is retained under `build/pyinstaller-cache`; remove that directory to force a clean
worker analysis after changing the build environment.

Published files use `OctoPus_{version}_{arch}_{os}_{purpose}.{ext}` with `x64` or `arm64` and
`win64` or `linux`. Linux AppImages omit the purpose suffix, for example
`OctoPus_1.0.0-RC3_x64_linux.AppImage`. Windows builds create a portable ZIP such as
`OctoPus_1.0.0-RC3_x64_win64_portable.zip`; `--bundles nsis` also creates a setup executable such
as `OctoPus_1.0.0-RC3_x64_win64_setup.exe`. The installer-only workflow adds
`--no-portable-zip`, so it uploads only the setup executable. The checked
`dist/<target-triple>/portable/` tree is kept for local launch and inspection.
Windows ZIP publication retries transient sharing locks. If it still fails, the previous portable
tree is restored and the existing ZIP is retained.

The manually assigned app version is the single SemVer value in the repository-root `VERSION`
file. Store it without a leading `v`; the current value is `1.0.0-RC3`. Update `VERSION`
intentionally for a release. Git tags and the clock do not change the app version. `build.py`
validates this value and injects it into Tauri and the frontend, so `package.json` and source
literals are not the app version source.

The update checker compares this SemVer value with GitHub's latest stable release. SemVer
prerelease identifiers are case-sensitive: `1.0.0-RC3` sorts before `1.0.0-beta3`. Before
publishing this version, verify that the existing `beta3` release is marked as a prerelease, or
choose an identifier whose SemVer ordering matches the intended release sequence.

The numeric build number is the count of commits reachable from the `HEAD` of the OctoPus
product repository (`git rev-list --count HEAD`). The short SHA shown alongside it identifies
that exact product commit. `build.py` resolves Git metadata relative to its own file, so invoking
the production script from OctoPus-dev does not use OctoPus-dev's commit count or SHA. Changes in
OctoPus-dev alone therefore do not alter the production version or build identity. Fetch full
product Git history; shallow repositories are rejected because they cannot produce the complete
commit count. A dirty product checkout can change the binary without changing its commit-based
identity, so commit product-source changes before creating a release build. Use
`scripts/build_portable.py` for packaging; calling Tauri directly bypasses this version and
build-number generation.

For an explicitly requested package, pass `--bundles appimage` on Linux or `--bundles nsis` on
native Windows (with Microsoft C++ Build Tools and WebView2 installed), or `--bundles dmg` on
macOS. `build.py` builds the
frontend/worker/native app under `build/`, places the checked portable tree under
`dist/<target-triple>/portable/`, and publishes packages in `dist/<target-triple>/` using the
filename convention above. Directory publication retries transient access errors, falls back to
copying the verified staged tree, and restores the previous output on failure. The portable
builder preserves its previous output until the worker, fonts, glyphs,
manual, examples and license checks pass. Each repository has its own locks; update them
intentionally with `uv lock`/npm/Cargo and validate the resulting change.

## Release fonts

Pinned font assets and their OFL, IPA and Xiaomi MiSans licenses are in
`src/octopus/assets/fonts/`. Linux release packaging verifies their hashes and stages them
beside the worker for preview and native export. Windows/macOS desktop packaging omits the 13
application score-font faces; its native resolver uses preferred installed families and
compatible installed substitutes. The two small Noto Sans SC manual subsets and PDF.js standard
fonts are separate documentation/import resources. See the [font asset guide](src/octopus/assets/fonts/README.md).
The source engine retains its reference profile; use `OCTOPUS_FONT_PROFILE=release` for Linux
release-policy checks. Reference font files stay outside Git.

## Portable production testing

Every native build publishes an untracked portable tree under
`dist/<target-triple>/portable/`. Installation packages are produced only when `--bundles` is
specified; Windows builds also create the named portable ZIP. The builder verifies
worker/font/glyph assets, a Chinese render, example bytes and the
packaged user manual before replacing the portable output. `portable.previous/` retains the last
successful portable build.

On Linux, run from any working directory:

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

On Windows, run `dist/<target-triple>/portable/octopus.exe`. Keep the complete portable
folder together. Linux still requires the host GTK/WebKit libraries and Poppler tools; Windows
requires WebView2. This is an application-local production testing tree, not a static OS runtime.
Both build/ and dist/ are ignored by Git. Linux portable includes its verified score-font set;
Windows portable uses installed system fonts and compatible installed substitutes without the
13 application score-font faces.

The Linux release font directory is `usr/lib/OctoPus/fonts/`, next to the worker and its
manifest/license resources. Windows/macOS desktop packages do not stage that directory or
application score-font faces. Source/CLI builds continue to use repository assets where their
font profile requires them. Keep the complete Linux portable tree together. The offline manual's
small Noto subsets and PDF.js standard fonts are not score-font payloads.
Bundled OCR packages and default model attributions are listed in
[THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).
