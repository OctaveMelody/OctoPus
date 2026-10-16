# Application fonts

**English** | [简体中文](README.zh-CN.md)

Page Settings offers the score roles HeiTi-1, HeiTi-2, SongTi, KaiTi and FangSong. Font
source is selected automatically by the desktop target; users do not choose OS versus bundled
fonts in Preferences.

- Windows and macOS desktop builds use the preferred installed family for each role below.
  When it is unavailable, the application searches compatible installed faces and provides
  official installation help. These desktop packages omit the 13 application score-font faces.
- Linux production portable and AppImage builds use the verified bundled family in the table
  directly, independently of conflicting system fonts. Noto faces back up missing glyphs.
- Source/reference and Python/CLI profiles retain checked-in font assets for development and
  command-line export. This is distinct from the frozen Windows/macOS desktop worker.

The offline manual separately includes two small Noto Sans SC subsets (regular and bold) for
readable Chinese documentation without network access. PDF.js standard fonts are also separate:
they support imported-PDF viewing and are not score fonts.

| Role | Preferred installed Windows family | Preferred installed macOS family | Linux bundled regular face |
| --- | --- | --- | --- |
| HeiTi-1 | Microsoft YaHei | PingFang SC | MiSans v4.009 |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei v1.305 |
| SongTi | SimSun | Songti SC | SimZhiSong v1.103 |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai v1.522 |
| FangSong | FangSong | STFangsong | Zhuque Fangsong v0.212 |

Saved HeiTi remains an alias for HeiTi-2. New documents use HeiTi-1/Bold. Existing
note presets remain Regular/Italic/Bold (a/c/b); legacy values and untouched settings
remain readable. The five Linux role families supply regular faces, without synthetic
weights. Noto Sans/Serif regular/bold back up missing glyphs; four Liberation Sans
styles cover Latin/Arial. The source asset set contains thirteen TTF faces and ten
notices/licenses; Linux release packages include this score-font set.
Zhuque is upstream's technical-preview release; its actual unmodified family name is
Zhuque Fangsong (technical preview). Its missing characters use the Noto backup.

System font files remain on their host and are never redistributed or installed by OctoPus.
macOS collection inspection selects the requested family and closest weight, rather than the
collection's first face. The native desktop exporters retain supported installed fonts, including
CFF outlines; Linux exports use the verified bundled faces. Python's source/CLI ReportLab PDF path
cannot embed CFF and uses the corresponding source-profile replacement. TrueType collection faces
are extracted temporarily for Python PDF registration, without changing metadata or outlines.
FontTools 4.60.2 supports collection inspection. Native PDF embeds text fonts; JPG contains pixels.
External SVG viewers need the requested fonts. No font is globally installed or replaced.

WenKai, Noto, Zhuque and Liberation use OFL 1.1. Neo XiHei/SimZhiSong use IPA Font
License 1.0; [original IPA restoration](licenses/IPA-RESTORATION.txt) is documented.
MiSans uses Xiaomi's own license, permitting use in applications with attribution and
notice retention; it is not OFL and must not be modified or distributed separately as
font software. The application About panel credits Xiaomi MiSans. Its unmodified font
and complete official agreement (PDF plus extracted text) accompany the application.
Original names/binaries/notices are retained. Noto static weights 400/700 are generated
with FontTools 4.60.2 and do not use the reserved name Source.

sources.json pins source/archive hashes, members, versions and notices. manifest.json
records face/license hashes and shared family coverage. Verify independently in production:

```sh
python3 build_desktop_engine.py --verify-fonts
```

Downloads, extraction and regeneration are development support work. From OctoPus-dev:

```sh
uv run --no-sync --with zstandard==0.25.0 python tools/prepare_release_fonts.py
```

The helper targets ../OctoPus/src/octopus/assets/fonts and caches pinned sources in ignored
OctoPus-dev/build/font-sources/. Production builds only verify/use committed inputs and
require no development repository or download helper. Source workers, exporters and wheels
consume canonical assets for their selected profile. Linux desktop preview loads its font set
from the native-managed resource directory; Windows/macOS frozen frontends omit score faces.
OCTOPUS_FONT_PROFILE=release enables Linux production policy for source checks. Frozen workers
always use their target-specific production policy, even when a reference override is supplied.

The verified Linux score-font set is staged beside the worker at
`usr/lib/OctoPus/fonts`, with its manifest and complete license notices. Keep the complete Linux
portable tree together. Windows/macOS desktop bundles do not stage these application score fonts;
their native resolver uses installed system faces and compatible installed substitutes. The
source/CLI profile still needs its checked-in font assets. Do not infer bundle policy from a
leftover font directory in an existing installation.
