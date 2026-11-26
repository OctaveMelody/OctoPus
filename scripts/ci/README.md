# Native package CI checks

## Local-only default

These commands run CI checks on the current machine. They do not contact GitHub or dispatch,
inspect, or wait for GitHub Actions. Treat a request to "test CI" or "test the workflow" as a local
run unless the user explicitly asks for a hosted GitHub operation.

`build_package.py` runs formatting, locked Python environment sync, OCR-model preparation, native
package build, Rust Clippy/tests, and package smoke check. Local runs apply `cargo fmt --all` before
building; GitHub Actions uses `cargo fmt --all -- --check` so the workflow does not modify its
checkout. Build on the matching native host:

| Package | Required host |
| --- | --- |
| `linux-appimage` | Linux x86_64 |
| `windows-installer` | Windows x64 |
| `windows-portable` | Windows x64 |
| `macos-dmg` | Apple Silicon macOS |

Install the same tool versions used by the workflow before running the script:

- Python 3.12, uv, Node.js from `.node-version`, and npm from `.npm-version`.
- Rust 1.98.1 with `rustfmt` and `clippy`, plus Tauri CLI 2.11.5:
  `cargo install tauri-cli --version 2.11.5 --locked`.
- On Linux, install `build-essential`, `pkg-config`, `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`,
  `libayatana-appindicator3-dev`, `librsvg2-dev`, and `poppler-utils`.
- On Windows, use the Microsoft C++ build tools required by the native Tauri builder.
- On macOS, use an Apple Silicon host with Xcode 27 and its command-line tools installed,
  matching the workflow's `xcode-27` runner.

Run from the production repository root. The script syncs the locked Python extras and prepares
the pinned OCR models before building:

```sh
python scripts/ci/build_package.py --package linux-appimage
python scripts/ci/build_package.py --package windows-installer
python scripts/ci/build_package.py --package windows-portable
python scripts/ci/build_package.py --package macos-dmg
```

Only run the command for the host you're using. The script sets CI's Rust profile defaults and
rejects a package/host mismatch. It writes packages under `dist/`, which can contain ignored local
build outputs. Run from a clean checkout at the desired source commit when reproducing a release.

In a sandbox with a read-only home directory, set `UV_CACHE_DIR` and, on Linux, `XDG_DATA_HOME` to
writable temporary directories before running the command. Leave `XDG_CACHE_HOME` unchanged when
it contains Tauri's cached AppRun binary; overriding it can make Tauri try to download that helper.

Linux AppImage and Windows portable runs include the package smoke check. The macOS workflow relies
on the builder's DMG validation. Windows installer installation smoke remains restricted to the
isolated GitHub Actions runner; local Windows runs still perform the installer build and full Rust
checks, then report that single smoke step as skipped.

The workflow runs the current package runner from `github.workflow_sha` against its selected
`source_sha`. It stages the runner and smoke checker under the runner temporary directory, then
removes the nested helper checkout before the build-source digest runs. This keeps the workflow
tools outside the product source inputs while retaining builds of older release commits. The
workflow-only staging flag is not needed for local runs.

## Format automatically before committing

Install the tracked pre-commit hook once in each production checkout:

```sh
git config core.hooksPath .githooks
```

When a commit includes staged Rust changes, the hook runs `cargo fmt --all`. If formatting changes
Rust files, or Rust changes remain unstaged, it stops the commit so you can review and stage the
updates before retrying. Commits without staged Rust files skip the hook.
