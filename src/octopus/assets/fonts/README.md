# Redistributable release fonts

This is the canonical production font asset directory. The Python wheel/worker, native Rust
exporter and frontend all use these same inputs. Fonts are app-local; no system install occurs.

Noto Sans SC regular/bold replaces Microsoft YaHei and SimHei. Noto Serif SC regular/bold replaces
SimSun (and provides a serif fallback for KaiTi; it is not a brush-style equivalent). Liberation
Sans 2.1.5 regular/bold/italic/bold-italic replaces Arial. Unsupported requests use Noto Sans SC.
These substitutions are stylistic; Chinese glyph metrics/pixels differ from Microsoft fonts.
The manifest records actual Unicode coverage shared by each family's faces. A text element that
needs unavailable glyphs (for example Chinese requested in Arial) uses a bundled CJK face; Latin
Arial text keeps Liberation Sans. Font metadata and visible text are not rewritten.

sources.json pins original download URLs, upstream revisions and checksums. Noto static TTF
instances at weight 400/700 are generated using fontTools 4.60.2 for PDF/native compatibility.
The family names remain Noto Sans SC/Noto Serif SC; modified fonts do not use the reserved name
Source. The Liberation faces are unmodified. All fonts retain OFL 1.1 terms and copyright notices;
licenses/ contains the complete notices/texts shipped in the application and frontend assets.

Verify committed inputs without network access:

```sh
python3 scripts/prepare_fonts.py --verify
```

Reproduce downloads/static instances from this repository root:

```sh
uv run --no-project --with fonttools==4.60.2 --with zstandard==0.25.0 \
  python scripts/prepare_fonts.py
```

Sources are cached under ignored build/font-sources/ (or use --cache with a workspace cache).
Existing cached sources are still hash-verified. Regeneration verifies pinned build-tool versions;
review manifest hashes before committing any intentional font update. Microsoft font binaries
must never be added here, to the frontend, or to release packages.

Source engine tests default to the reference profile. OCTOPUS_FONT_PROFILE=release selects the
release profile for source-engine/Python export checks. Frozen workers always use release fonts;
native release exports load only the eight embedded faces, and source/debug native exports use
system fonts unless release is selected. Original score settings and reference corpus bytes stay
unchanged; the profile changes SVG font requests at the engine boundary. The source CLI renderer
continues to produce reference SVGs for corpus auditing.

App preview loads bundled font faces before mounting. Python PDF registration and raster export
use the same font files; release raster export disables system fonts. Native exports embed the
font inputs and do not require fonts installed on the host. PDF embeds text fonts, JPG contains
pixels; external standalone SVG viewers need the named Noto/Liberation fonts installed.
