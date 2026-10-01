# Application fonts

The settings panel offers HeiTi-1, HeiTi-2, SongTi, KaiTi and FangSong. Each installed
system family is preferred independently on Windows/macOS; a missing family uses its
bundled fallback. Linux production uses the fallbacks. Source/debug reference builds
prefer matching installed Microsoft fonts on Linux as well.

| Role | Windows | macOS | Bundled regular face |
| --- | --- | --- | --- |
| HeiTi-1 | Microsoft YaHei | PingFang SC | MiSans v4.009 |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei v1.305 |
| SongTi | SimSun | Songti SC | SimZhiSong v1.103 |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai v1.522 |
| FangSong | FangSong | STFangsong | Zhuque Fangsong v0.212 |

Saved HeiTi remains an alias for HeiTi-2. New documents use HeiTi-2/Bold. Existing
note presets remain Regular/Italic/Bold (a/c/b); legacy values and untouched settings
remain readable. The five fallback families supply regular faces, without synthetic
weights. Noto Sans/Serif regular/bold back up missing glyphs; four Liberation Sans
styles cover Latin/Arial. Thirteen TTF faces are bundled, with ten notices/licenses.
Zhuque is upstream's technical-preview release; its actual unmodified family name is
Zhuque Fangsong (technical preview). Its missing characters use the Noto backup.

Windows/macOS font files remain on their host and are never redistributed or installed
by OctoPus. macOS collection inspection selects the requested family and closest weight,
rather than the collection's first face. Preview and native exports retain supported
system fonts, including CFF outlines. Python's ReportLab PDF path cannot embed CFF;
that path explicitly uses the corresponding bundled fallback. TrueType collection faces
are extracted temporarily for Python PDF registration, without changing their metadata
or outlines. FontTools 4.60.2 supports collection inspection; native exports load host
fonts on Windows/macOS and all bundled faces. PDFs embed text fonts; JPGs contain pixels.
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
require no development repository or download helper. The worker, native exporter, wheel
and frontend all consume the same canonical production assets and complete notices.
OCTOPUS_FONT_PROFILE=release enables production font policy for source checks. Frozen
workers always use production policy, even when a reference override is supplied.
