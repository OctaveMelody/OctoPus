# Agent and model instructions

This is the production repository. Read this file before changing or building the app. It is
self-contained: a production setup or build must not require OctoPus-dev, its virtual environment,
its development tools, or its working tree.

## Source of truth and sync with OctoPus-dev

OctoPus-dev's `AGENTS.md` directs production builds to this repository's
`scripts/build_portable.py`, which defaults to a production portable build and delegates to
`build.py`. Its `scripts/build-dev.sh` creates a separate development
executable and is not the release build. Follow the production `ENVIRONMENT.md` and the commands
below even when OctoPus-dev is unavailable. Do not build production from a dev checkout, a linked
source tree, or an experimental cross-compilation script.

When comparing against OctoPus-dev, use the exact OctoPus product commit selected for that build
(recorded by its `production-revision.txt` when present). OctoPus-dev's own branch and commit
history are never inputs to the product version or build number. For production packages, this
repository's `VERSION`, `uv.lock`, `ui/web/package-lock.json`, `ui/Cargo.lock`, `.python-version`,
`.node-version`, and `rust-toolchain.toml` are authoritative. The dev Python lock includes
development-only dependencies and is not a substitute for this repository's production lock.

## Chinese-language product copy

- In Chinese user-facing content, including READMEs and user manuals, use `章鱼简谱` as the
  product name. Keep `OctoPus` only in literal filenames, URLs, code/repository identifiers, or the
  paired English slogan below.
- Pair the bold English tagline **OctoPus: Octave + Jianpu for editing numbered-notation scores.**
  with the exact bold Chinese slogan **章鱼简谱：玩转八度，轻松制谱。** Do not translate the
  English tagline literally.

## Agent workflow

- Preserve existing user changes. Begin with `git status --short --branch`; do not reset or clean
  the checkout to make a build appear reproducible.
- State findings and validation evidence plainly. Complete the requested implementation and
  relevant verification before reporting.
- Route supported delegated work using the current host's available models:

  | Work | Model family | Reasoning effort |
  | --- | --- | --- |
  | Planning, investigation, analysis, diagnosis | Latest Sol | `high` |
  | Code review or independent fix verification | Latest Sol | `medium` |
  | Implementation, coding, refactoring | Latest Luna | `xhigh` |
  | Build, compile, bundle, package | Latest Luna | `medium` |
  | Simple factual lookup | Latest Luna | `medium` |

- Resolve “Latest” against the current host model list when assigning work. Use the exact
  supported model identifier and effort; do not silently substitute another family or effort.
  A user's explicit model choice takes precedence. Follow the active session's delegation rules.
- For mixed work, route analysis to Sol, implementation to Luna, and independent review to Sol.
  Build failures are diagnosed with Sol `high`; code changes to fix them use Luna `xhigh`;
  compilation/package work uses Luna `medium`. Do not claim a session changed models unless the
  host supports that change.
- Keep tests, audits, reference corpora, and development-only tooling in OctoPus-dev. Keep
  production runtime, packaging logic, and production dependency locks here.

## Windows x64 build environment

Build natively on Windows 10 or later, x64. Do not cross-compile the Python worker. Install:

- Git with full product history (shallow clones cannot generate the production build number).
- Visual Studio 2022 Build Tools with **Desktop development with C++**, MSVC v143, and a
  Windows 10/11 SDK. The production builder locates Visual Studio with `vswhere` and initializes
  its x64 environment; an x64 Native Tools or Developer PowerShell also works.
- Microsoft Edge WebView2 Evergreen Runtime.
- Python 3.12, uv 0.12.21, Node.js 22.23.3 with npm 10.9.9, and Rust/Cargo 1.98.1. The version
  pins are recorded in `.python-version`, `.node-version`, `.npm-version`, and
  `rust-toolchain.toml`;
  `ui/web/package-lock.json` and `ui/Cargo.lock` pin their dependencies.
- Tauri CLI 2.11.5, installed from its locked Cargo sources.

The build launcher checks the pinned versions. Run these commands manually only when diagnosing
a host setup:

```powershell
python --version
uv --version
node --version
npm --version
rustc --version
cargo --version
```

Install the pinned Tauri CLI if `cargo tauri --version` is not already 2.11.5:

```powershell
cargo install tauri-cli --version 2.11.5 --locked
cargo tauri --version
```

From the repository root, prepare the production-only virtual environment and frontend
dependencies:

```powershell
python scripts/setup.py
```

This runs `uv sync --locked --extra transcription --extra desktop-build` and `npm ci` using this
repository's manifests. Do not replace it with `uv sync` against OctoPus-dev or `npm install`.

## Build the production application

From the repository root (or pass the full script path from any working directory):

```powershell
# Default, matching OctoPus-dev's production-only default:
py scripts\build_portable.py

# Only when an installer is explicitly required:
py scripts\build_portable.py --bundles nsis
```

The default creates the portable application and a ZIP named
`OctoPus_{version}_x64_win64_portable.zip`. The NSIS command additionally creates a setup file
named `OctoPus_{version}_x64_win64_setup.exe`. Linux AppImages use
`OctoPus_{version}_{arch}_linux.AppImage`; the architecture label is `x64` or `arm64`. Outputs are
under `dist\<target-triple>\`; build intermediates are under `build\`. Keep the complete
`portable` directory together when moving or testing it.
macOS builds run natively on Apple Silicon with `--bundles dmg` and produce
`OctoPus_{version}_arm64_macos.dmg`. The production `desktop-packages` workflow builds Windows and
Apple Silicon macOS packages on published releases and supports manual dispatch; macOS DMGs are
validated before upload and are currently unsigned and not notarized.
Use `scripts/build_portable.py`, not `cargo tauri build` directly. The launcher finds the
repository and its virtual environment regardless of the current directory. The production
builder discovers tools through `PATH` (and initializes Visual Studio on Windows), verifies
pinned tool versions and system prerequisites, builds the frontend and worker once, then compiles
Tauri with the prebuild hook disabled for that invocation. It validates assets, the manually
assigned SemVer from `VERSION`, and the product-commit build number before compiling.

## Bit-for-bit parity with OctoPus-dev

OctoPus-dev's canonical production instruction invokes this same `build.py`; parity therefore
means building the same production source inputs, on the same Windows x64 MSVC target, with the
same bundle type and pinned toolchains. OctoPus-dev's development-only setup is not part of that
release input. To compare against a dev-produced artifact:

1. Use the exact OctoPus product commit being compared. If OctoPus-dev has a
   `production-revision.txt`, use its pinned product SHA. Fetch the product repository's full Git
   history. Ensure all production source and configuration changes in both builds are identical;
   a matching `HEAD` does not include local uncommitted changes.
2. Use the same target (`x86_64-pc-windows-msvc`), bundle selection, dependency locks, Python,
   Node/npm, Rust/Cargo, Tauri CLI, Visual Studio toolset, and Windows SDK. Do not use the GNU
   cross-target or the dev executable.
3. Check the manually assigned version from `VERSION`, the commit-count build number from the
   OctoPus product history, and the short product commit SHA. Git tags, build time, and
   OctoPus-dev's own commits do not affect these values. The production script resolves Git
   metadata relative to its own file.
4. Compare SHA-256 for the same installer file. For a portable build, compare SHA-256 for every
   file under `dist\x86_64-pc-windows-msvc\portable\`, matching relative paths as well as bytes.
   A successful build or matching version is not proof of byte identity; report parity only when
   the relevant hashes match.

The dependency locks and toolchain hints pin the application inputs, but the repository does not
normalize every Windows SDK, MSVC servicing level, package-tool timestamp, or build-host detail.
Independent builds on different machines are therefore not guaranteed to be byte-for-byte equal
by documentation alone. If hashes differ, record the exact source diff, build version, host/tool
versions, and artifact hashes; do not claim identity or change source to hide the difference.
