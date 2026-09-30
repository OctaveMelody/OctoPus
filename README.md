# OctoPus production source

This directory contains the application source, packaging configuration, offline worker builder,
and the two JPS example collections. It needs no files from the GPT-Tomato development directory.
Tests, audits, reference SVGs and development tools stay there.

[Production requirements](requirements.md) define the independent runtime/build environment.
Run `python3 setup_environment.py` to install its locked Python/frontend dependencies.

Install Rust 1.92+ with Tauri CLI 2.11.5, Node.js 20.19+ with npm, and `uv`. Debian builds also
need `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev` and
`poppler-utils`. Python 3.12 and locked Python build dependencies are installed by `uv` during the build.
Run on the target operating system; the PyInstaller worker is not cross-compiled.

From this directory, build a Debian package on Linux:

```sh
python3 build.py --bundles deb
```

On Windows, run `python build.py --bundles nsis` or `python build.py --bundles msi` in a native
Windows build environment. `build.py` installs the locked frontend dependencies when needed,
builds the frontend and worker through Tauri, then copies finished installation packages to
`dist/<Rust target triple>/`. Native binaries, the worker, frontend assets and temporary build
files stay under `build/`. Both directories are ignored by Git. `samples/jps_files/` is bundled
as application examples; `samples/jps_files_pretty/` is kept as source material.

The package includes the offline Python worker beside the native application and all 65 bundled
JPS examples. Keep the extracted executable with its neighboring engine and examples resources.
