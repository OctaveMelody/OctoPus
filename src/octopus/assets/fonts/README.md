# Application fonts

The settings panel offers HeiTi, SongTi and KaiTi. On Windows, an installed SimHei,
SimSun or KaiTi is preferred independently for each role. A missing family uses its
bundled fallback: LXGW Neo XiHei v1.305, SimZhiSong v1.103 or LXGW WenKai Regular
v1.522, respectively. Production Linux uses those bundled fallbacks. Source/debug
reference builds prefer installed Microsoft reference fonts, including on Linux.
Legacy family names and note-style IDs remain readable. New documents use HeiTi
and Bold; note-style choices are Regular, Italic and Bold. They select the existing
numbered-note glyph sets; text font weight/style is a separate setting.

This directory is the canonical asset source for the Python worker, native Rust
exporter and frontend. Eleven TTF faces are bundled: the three chosen regular
faces, Noto Sans SC/Serif SC regular/bold backups, and four Liberation Sans styles
for Arial-compatible Latin text. Missing glyphs fall back to a bundled Noto face.
The three regular-only families use their supplied face without synthetic weights.
PDFs embed fonts; JPGs contain pixels. External SVG viewers need the named fonts.
Fonts are app-local and no system font is installed or replaced.

WenKai, Noto and Liberation use OFL 1.1. Neo XiHei and SimZhiSong use IPA Font
License 1.0. All original names, binary font data and complete notices are retained
for the three chosen faces. See [IPA restoration instructions](licenses/IPA-RESTORATION.txt)
for restoring the original IPA fonts in source and executable distributions.
That notice is included and verified with the font licenses in every package.
Noto static weights 400/700 are generated using fontTools 4.60.2; their names do
not use the reserved name Source. No Microsoft font binaries are redistributed.

sources.json pins URLs, versions and SHA-256 values. manifest.json records all
face/license hashes and shared Unicode coverage. Verify without network access:

```sh
python3 scripts/prepare_fonts.py --verify
```

Reproduce inputs from this repository root:

```sh
uv run --no-project --with fonttools==4.60.2 --with zstandard==0.25.0 \
  python scripts/prepare_fonts.py
```

Sources are cached under ignored build/font-sources/ (or --cache). Cached inputs
remain hash-verified. Review manifest changes before committing updates.

OCTOPUS_FONT_PROFILE=release enables production font policy in source exports.
Frozen workers always use that policy, with Windows system-family preference.
The native exporter embeds all eleven faces and loads host fonts on Windows or
in debug/reference mode. Python PDF and raster paths use the same selected files.
Release rasterization receives only explicit bundled/selected Windows files.
The browser preloads bundled faces before mounting. Existing reference corpus
bytes and the source CLI's auditing output remain unchanged.
